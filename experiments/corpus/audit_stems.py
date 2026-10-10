#!/usr/bin/env python3
"""Audit integer-PCM WAVs once each; emit measurements and excerpt references.

No audio is rewritten. Inputs are found nonrecursively. JSON goes to stdout
unless an explicit new --output path is supplied.
"""

import argparse
import hashlib
import io
import json
import math
import platform
import sys
import wave
from pathlib import Path

import numpy as np


def decode_pcm(payload, sample_width, channels):
    """Decode interleaved signed little-endian PCM16/24/32 into N,C float64.

    The caller must establish integer PCM from the WAV format header; raw float
    data cannot be distinguished from integer PCM by examining its bytes.
    Negative full scale maps to -1; positive full scale maps just below +1.
    """
    if sample_width not in (2, 3, 4):
        raise ValueError("only signed integer PCM16, PCM24, and PCM32 are supported")
    if not isinstance(channels, int) or channels < 1:
        raise ValueError("channels must be a positive integer")
    if len(payload) % (sample_width * channels):
        raise ValueError("PCM payload does not contain a whole number of frames")
    if sample_width == 3:
        octets = np.frombuffer(payload, dtype=np.uint8).reshape(-1, 3)
        integers = (octets[:, 0].astype(np.int32)
                    | (octets[:, 1].astype(np.int32) << 8)
                    | (octets[:, 2].astype(np.int32) << 16))
        integers = (integers ^ 0x800000) - 0x800000
    else:
        integers = np.frombuffer(payload, dtype="<i{}".format(sample_width))
    return (integers.astype(np.float64) / (1 << (8 * sample_width - 1))).reshape(-1, channels)


def load_pcm_wav(path):
    """Return (N,C float64 samples, rate, metadata), with one encoded-file read.

    SHA-256 covers the same bytes decoded through wave/BytesIO. Decoding uses
    65536-frame chunks, retaining only this source file and its output array.
    stdlib wave rejects float/compressed WAVs (and unsupported extensible WAVs).
    """
    path = Path(path)
    encoded = path.read_bytes()
    digest = hashlib.sha256(encoded).hexdigest()
    try:
        with wave.open(io.BytesIO(encoded), "rb") as reader:
            channels = reader.getnchannels()
            width = reader.getsampwidth()
            sample_rate = reader.getframerate()
            frames = reader.getnframes()
            if reader.getcomptype() != "NONE" or width not in (2, 3, 4):
                raise ValueError("requires uncompressed integer PCM16/24/32 WAV")
            if channels < 1 or sample_rate < 1:
                raise ValueError("invalid WAV channel count or sample rate")
            samples = np.empty((frames, channels), dtype=np.float64)
            position = 0
            while position < frames:
                count = min(65536, frames - position)
                payload = reader.readframes(count)
                if len(payload) != count * channels * width:
                    raise ValueError("truncated WAV sample data")
                samples[position:position + count] = decode_pcm(payload, width, channels)
                position += count
    except (wave.Error, EOFError) as error:
        raise ValueError("unsupported or malformed WAV: {}".format(error)) from error
    metadata = {
        "source_name": path.name,
        "encoded_bytes": len(encoded),
        "sha256": digest,
        "sample_rate": sample_rate,
        "channels": channels,
        "sample_width_bytes": width,
        "pcm_bits": 8 * width,
        "frame_count": frames,
        "duration_seconds": frames / sample_rate,
        "format": "signed little-endian integer PCM",
    }
    return samples, sample_rate, metadata


def coarse_envelope(samples, sample_rate, window_seconds=0.05):
    """RMS across all channels, without stereo summation/cancellation."""
    hop = max(1, round(window_seconds * sample_rate))
    envelope = []
    for start in range(0, len(samples), hop):
        block = samples[start:start + hop]
        envelope.append(float(np.sqrt(np.mean(block * block))))
    return np.asarray(envelope), hop


def candidate_excerpts(envelope, hop, frame_count, sample_rate,
                       max_seconds=6.0, max_candidates=3):
    """Choose references using only threshold crossings and coarse RMS changes."""
    envelope = np.asarray(envelope, dtype=np.float64)
    if frame_count == 0 or not len(envelope) or max_candidates < 1:
        return [], None
    peak = float(np.max(envelope))
    # 45 dB below the strongest RMS bin, with an absolute -120 dBFS floor.
    threshold = max(1e-6, peak * 10.0 ** (-45.0 / 20.0))
    active = envelope >= threshold
    if not np.any(active):
        return [], threshold
    count = min(frame_count, max(1, int(math.floor(max_seconds * sample_rate))))
    pre_roll = round(0.25 * sample_rate)
    starts = np.flatnonzero(active & ~np.concatenate(([False], active[:-1])))
    selected = []

    def consider(start_frame, reason):
        start_frame = int(np.clip(start_frame, 0, frame_count - count))
        end_frame = start_frame + count
        for previous in selected:
            overlap = max(0, min(end_frame, previous["start_frame"] + previous["frame_count"])
                          - max(start_frame, previous["start_frame"]))
            if overlap > 0.75 * min(count, previous["frame_count"]):
                return False
        first_bin = start_frame // hop
        stop_bin = min(len(envelope), (end_frame + hop - 1) // hop)
        if not np.any(active[first_bin:stop_bin]):
            return False
        selected.append({
            "start_frame": start_frame,
            "frame_count": count,
            "start_seconds": start_frame / sample_rate,
            "duration_seconds": count / sample_rate,
            "selection_reason": reason,
        })
        return True

    consider(int(starts[0]) * hop - pre_roll, "first_rms_activity_threshold_crossing")
    bins_per_excerpt = max(1, int(math.ceil(count / hop)))
    # Prefix sums keep scoring bounded and avoid repeatedly scanning audio.
    power_prefix = np.concatenate(([0.0], np.cumsum(envelope * envelope)))
    changes = np.concatenate(([0.0], np.abs(np.diff(envelope))))
    change_prefix = np.concatenate(([0.0], np.cumsum(changes)))
    indices = np.arange(len(envelope))
    ends = np.minimum(len(envelope), indices + bins_per_excerpt)
    for scores, reason in (
            (change_prefix[ends] - change_prefix[indices], "largest_sum_of_coarse_rms_changes"),
            (power_prefix[ends] - power_prefix[indices], "largest_sum_of_coarse_rms_squared")):
        if len(selected) >= max_candidates:
            break
        # Stable tie handling makes references reproducible on the same input.
        for index in np.argsort(-scores, kind="stable"):
            if consider(int(index) * hop, reason):
                break
    if len(selected) < max_candidates:
        for index in starts[1:]:
            consider(int(index) * hop - pre_roll, "later_rms_activity_threshold_crossing")
            if len(selected) >= max_candidates:
                break
    return selected[:max_candidates], threshold


def audit_samples(samples, sample_rate, sample_width=3):
    """Measure one decoded source; no pitch, technique, or quality inference."""
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim != 2 or samples.shape[1] < 1:
        raise ValueError("samples must have shape (frames, channels)")
    if sample_rate < 1 or sample_width not in (2, 3, 4):
        raise ValueError("invalid sample rate or integer PCM width")
    if not np.all(np.isfinite(samples)):
        raise ValueError("sample array contains nonfinite values")
    frames, channels = samples.shape
    sums = np.zeros(channels)
    squares = np.zeros(channels)
    minimum = np.full(channels, np.inf)
    maximum = np.full(channels, -np.inf)
    positive_endpoints = np.zeros(channels, dtype=np.int64)
    negative_endpoints = np.zeros(channels, dtype=np.int64)
    zero_samples = np.zeros(channels, dtype=np.int64)
    positive_endpoint = 1.0 - 1.0 / (1 << (8 * sample_width - 1))
    stereo_products = 0.0
    different_stereo_frames = 0
    for start in range(0, frames, 65536):
        block = samples[start:start + 65536]
        sums += np.sum(block, axis=0)
        squares += np.sum(block * block, axis=0)
        minimum = np.minimum(minimum, np.min(block, axis=0))
        maximum = np.maximum(maximum, np.max(block, axis=0))
        positive_endpoints += np.count_nonzero(block == positive_endpoint, axis=0)
        negative_endpoints += np.count_nonzero(block == -1.0, axis=0)
        zero_samples += np.count_nonzero(block == 0.0, axis=0)
        if channels == 2:
            stereo_products += float(np.dot(block[:, 0], block[:, 1]))
            different_stereo_frames += int(np.count_nonzero(block[:, 0] != block[:, 1]))
    means = sums / frames if frames else np.zeros(channels)
    powers = squares / frames if frames else np.zeros(channels)
    channel_results = []
    for channel in range(channels):
        channel_results.append({
            "channel_index": channel,
            "peak_absolute": float(max(abs(minimum[channel]), abs(maximum[channel]))) if frames else 0.0,
            "minimum": float(minimum[channel]) if frames else None,
            "maximum": float(maximum[channel]) if frames else None,
            "rms": float(np.sqrt(powers[channel])),
            "dc_mean": float(means[channel]),
            "positive_pcm_endpoint_samples": int(positive_endpoints[channel]),
            "negative_pcm_endpoint_samples": int(negative_endpoints[channel]),
            "exact_zero_samples": int(zero_samples[channel]),
        })
    stereo = None
    if channels == 2:
        variances = np.maximum(0.0, powers - means * means)
        # Exact constant channels have undefined correlation, even if the
        # subtraction above leaves a tiny positive roundoff remainder.
        variances = np.where(maximum > minimum, variances, 0.0)
        denominator = float(np.sqrt(variances[0] * variances[1]))
        covariance = stereo_products / frames - means[0] * means[1] if frames else 0.0
        stereo = {
            "left_right_exactly_equal": different_stereo_frames == 0,
            "different_frame_count": different_stereo_frames,
            "pearson_correlation": float(np.clip(covariance / denominator, -1.0, 1.0))
            if denominator > 0 else None,
            "correlation_undefined_reason": None if denominator > 0 else "one or both channels have zero variance",
        }
    envelope, hop = coarse_envelope(samples, sample_rate)
    candidates, threshold = candidate_excerpts(envelope, hop, frames, sample_rate)
    return {
        "channel_statistics": channel_results,
        "stereo": stereo,
        "coarse_rms_envelope": {
            "window_frames": hop,
            "window_seconds": hop / sample_rate,
            "last_window_frame_count": (frames - (len(envelope) - 1) * hop) if len(envelope) else 0,
            "aggregation": "sqrt(mean(sample_squared)) across frames and channels; final bin may be shorter",
            "values": [float(value) for value in envelope],
        },
        "candidate_activity_rms_threshold": threshold,
        "candidate_excerpts": candidates,
    }


def audit_wav(path):
    samples, sample_rate, metadata = load_pcm_wav(path)
    result = {"source": str(path), "metadata": metadata}
    result.update(audit_samples(samples, sample_rate, metadata["sample_width_bytes"]))
    for candidate in result["candidate_excerpts"]:
        candidate["source"] = str(path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("stems"))
    parser.add_argument("--output", type=Path, help="explicit new JSON file; default stdout")
    args = parser.parse_args()
    if not args.input_dir.is_dir():
        parser.error("input directory does not exist: {}".format(args.input_dir))
    paths = sorted(path for path in args.input_dir.glob("*.wav") if path.is_file())
    if not paths:
        parser.error("no nonrecursive *.wav inputs found in {}".format(args.input_dir))
    if args.output is not None:
        if args.output.exists():
            parser.error("output already exists; choose a new path")
        if not args.output.parent.is_dir():
            parser.error("output parent directory does not exist")
    result = {
        "schema_version": 1,
        "purpose": "source inventory, amplitude/channel measurements, and excerpt references only",
        "environment": {"python": sys.version.split()[0], "numpy": np.__version__,
                        "platform": platform.platform()},
        "source_read_policy": "one encoded-file read per input; hash and chunk decoding use those same in-memory bytes",
        "audit_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": [
            "Endpoint counts do not prove clipping occurred or that clipping is absent.",
            "RMS activity is not a note, pitch, transient, or playing-technique label.",
            "Correlation and exact equality describe these samples, not instrument topology.",
            "Candidate times use 50 ms RMS bins and are not precise musical event boundaries.",
            "No audio is rewritten; original sources and levels are preserved.",
        ],
        "sources": [], "errors": [],
    }
    for path in paths:
        try:
            result["sources"].append(audit_wav(path))
        except (OSError, ValueError) as error:
            result["errors"].append({"source": str(path), "error": str(error)})
    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
        print("Wrote audit for {} source(s) to {}".format(len(result["sources"]), args.output))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
