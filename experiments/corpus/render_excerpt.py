#!/usr/bin/env python3
"""Render one short diagnostic excerpt; originals are never rewritten.

Uses the rejected transport candidate. Outputs are mono float WAVs at the
original input rate, with matched scheduled delay and conservative drain.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import wave

import numpy as np

from audit_stems import decode_pcm

ENGINE_DIRECTORY = Path(__file__).resolve().parents[1] / "transport"
sys.path.insert(0, str(ENGINE_DIRECTORY))
from engine import TransportEngine


def signal_metrics(samples):
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    rms = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0
    return {
        "peak": peak,
        "peak_dbfs": 20 * math.log10(peak) if peak else None,
        "rms": rms,
        "rms_dbfs": 20 * math.log10(rms) if rms else None,
        "samples_above_full_scale": int(np.count_nonzero(np.abs(samples) > 1)),
    }


def write_float_wav(path, samples, sample_rate, ffmpeg):
    # Float WAV preserves over-range values instead of silently clipping PCM.
    if not np.all(np.isfinite(samples)) or np.max(np.abs(samples)) > np.finfo(np.float32).max:
        raise ValueError("output cannot be represented as finite float32 WAV")
    subprocess.run(
        [ffmpeg, "-v", "error", "-nostdin", "-f", "f64le", "-ar", str(sample_rate),
         "-ac", "1", "-i", "pipe:0", "-c:a", "pcm_f32le", "-n", str(path)],
        input=np.asarray(samples, dtype="<f8").tobytes(), check=True)


def render_excerpt(source_path, start_s, duration_s, channel, output_dir):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is missing; ask the user before installing it")
    if output_dir.exists():
        raise FileExistsError("choose a new output directory to preserve previous renders")
    if not math.isfinite(start_s) or start_s < 0:
        raise ValueError("start must be finite and nonnegative")
    if not math.isfinite(duration_s) or not 0 < duration_s <= 6:
        raise ValueError("duration must be positive and at most six seconds")
    before = source_path.stat()
    with wave.open(str(source_path), "rb") as source:
        if source.getcomptype() != "NONE":
            raise ValueError("expected uncompressed integer PCM WAV")
        sample_rate, channels = source.getframerate(), source.getnchannels()
        sample_width, source_frames = source.getsampwidth(), source.getnframes()
        if channel < 0 or channel >= channels:
            raise ValueError("selected channel is outside the input channel range")
        start = round(start_s * sample_rate)
        if start >= source_frames:
            raise ValueError("excerpt starts beyond the recording")
        count = min(round(duration_s * sample_rate), source_frames - start)
        if count <= 0:
            raise ValueError("excerpt contains no samples")
        context_start = max(0, start - round(0.5 * sample_rate))
        preroll = start - context_start
        source.setpos(context_start)
        payload = source.readframes(preroll + count)
    after = source_path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("source changed while reading the excerpt")
    decoded = decode_pcm(payload, sample_width, channels)
    if len(decoded) != preroll + count:
        raise ValueError("truncated PCM payload")
    samples = decoded[:, channel]
    if not np.all(np.isfinite(samples)):
        raise ValueError("nonfinite source samples")

    outputs = {}
    engine_parameters = dict(sample_rate=sample_rate, analysis_size=2048,
                             synthesis_size=384, hop=96, window="asymmetric")
    for semitones in (0, -2, -7):
        engine = TransportEngine(semitones=semitones, **engine_parameters)
        pieces = [engine.process(samples[start:start + 127])
                  for start in range(0, len(samples), 127)]
        pieces.append(engine.flush())
        outputs[semitones] = np.concatenate(pieces)
    delay = engine.latency_samples
    dry = np.zeros(len(outputs[0]), dtype=np.float64)
    dry[delay:delay + len(samples)] = samples
    unity_error = float(np.max(np.abs(outputs[0] - dry)))
    if unity_error > 1e-10:
        raise RuntimeError("original-rate delayed identity failed: {}".format(unity_error))

    output_dir.mkdir(parents=True, exist_ok=False)
    variants = {"dry-delay383.wav": dry, "minus2.wav": outputs[-2], "minus7.wav": outputs[-7]}
    records = []
    for name, result in variants.items():
        path = output_dir / name
        write_float_wav(path, result, sample_rate, ffmpeg)
        records.append({"file": name, "frames": len(result), **signal_metrics(result)})
    metadata = {
        "purpose": "diagnostic listening from a rejected research candidate, not a quality claim",
        "source": str(source_path), "source_bytes": before.st_size,
        "source_mtime_ns": before.st_mtime_ns,
        "source_sample_rate": sample_rate, "source_channels": channels,
        "selected_channel_zero_based": channel, "source_frames": source_frames,
        "excerpt_start_frame": start, "excerpt_frame_count": count,
        "source_context_start_frame": context_start, "preroll_frames": preroll,
        "context_pcm_sha256": hashlib.sha256(payload).hexdigest(),
        "selected_context_channels_sample_identical": bool(
            all(np.array_equal(decoded[:, 0], decoded[:, c]) for c in range(1, channels))),
        "engine_parameters": engine_parameters,
        "engine_sha256": hashlib.sha256((ENGINE_DIRECTORY / "engine.py").read_bytes()).hexdigest(),
        "scheduled_delay_samples": delay,
        "scheduled_delay_ms": 1000 * delay / sample_rate,
        "audition_interval_in_outputs_frames": [preroll + delay, preroll + delay + count],
        "unity_maximum_absolute_error": unity_error,
        "output_encoding": "mono IEEE float32 WAV; no normalization, limiting, fades, or resampling",
        "output_timeline": "includes source preroll, scheduled delay, and full conservative flush tail",
        "input_context_metrics": signal_metrics(samples), "outputs": records,
        "output_metric_domain": "float64 arrays before float32 WAV encoding; rounding may change stored sample values",
        "limitations": [
            "Mono diagnostic, not stereo engine validation.",
            "A delayed dry reference matches scheduling for timbre comparisons, not a live latency test.",
            "No tuning-error ground truth is inferred from guitar recordings.",
            "Original labels and processing status must come from the user.",
            "Cuts may be audible at file boundaries; no fades alter measured samples.",
        ],
    }
    (output_dir / "render.json").write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n")
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--start", type=float, required=True, help="seconds into original source")
    parser.add_argument("--duration", type=float, default=6, help="at most six seconds")
    parser.add_argument("--channel", type=int, required=True, help="zero-based source channel; no downmix")
    parser.add_argument("--output-dir", type=Path, required=True, help="new directory, preferably under /tmp")
    args = parser.parse_args()
    result = render_excerpt(args.source, args.start, args.duration, args.channel, args.output_dir)
    print(json.dumps({"output_dir": str(args.output_dir), "source": result["source"],
                      "unity_error": result["unity_maximum_absolute_error"],
                      "delay_ms": result["scheduled_delay_ms"], "outputs": result["outputs"]}, indent=2))


if __name__ == "__main__":
    main()
