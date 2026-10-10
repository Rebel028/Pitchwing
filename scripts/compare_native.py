#!/usr/bin/env python3
"""Bounded native/reference parity checks; audio scratch stays under /tmp."""

import argparse
import hashlib
import json
import platform
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "transport"))
sys.path.insert(0, str(ROOT / "experiments" / "corpus"))
from engine import TransportEngine as OriginalTransportEngine
from stable_reference import StableTransportEngine
from audit_stems import decode_pcm


def synthetic_fixtures():
    rate = 48000
    clock = np.arange(6143) / rate
    random = np.random.default_rng(20261008)
    yield {"name": "unity_noise_dc_low_sine", "sample_rate": rate, "semitones": 0.0,
           "samples": 0.1 * random.standard_normal(len(clock)) + 0.12
           + 0.2 * np.sin(2 * np.pi * 30.867706 * clock), "blocks": [1, 127, 512]}
    clock = np.arange(16801) / rate
    yield {"name": "E1_down7", "sample_rate": rate, "semitones": -7.0,
           "samples": 0.3 * np.sin(2 * np.pi * 41.203445 * clock + 0.31), "blocks": [64, 257]}
    clock = np.arange(36007) / rate
    yield {"name": "B0_C1_up7", "sample_rate": rate, "semitones": 7.0,
           "samples": 0.2 * np.sin(2 * np.pi * 30.867706 * clock + 0.19)
           + 0.2 * np.sin(2 * np.pi * 32.703196 * clock + 0.71), "blocks": [64, 257]}
    clock = np.arange(16007) / rate
    yield {"name": "A4_down1", "sample_rate": rate, "semitones": -1.0,
           "samples": 0.3 * np.sin(2 * np.pi * 440.0 * clock + 0.23), "blocks": [64, 257]}
    for first_nonzero in (0, 96, 97):
        samples = np.zeros(4096)
        active_clock = np.arange(len(samples) - first_nonzero) / rate
        samples[first_nonzero:] = 0.3 * np.sin(2 * np.pi * 440.0 * active_clock + 0.23)
        yield {"name": "A4_down1_first_nonzero_{}".format(first_nonzero),
               "sample_rate": rate, "semitones": -1.0, "samples": samples,
               "blocks": [32, 64, 128], "windows": ["asymmetric"],
               "first_nonzero_frame": first_nonzero}


def preferred_excerpt(path):
    """Read only 9.2--15.7 s: preferred 9.7--15.7 s plus 0.5 s preroll."""
    with wave.open(str(path), "rb") as reader:
        rate, channels, width = reader.getframerate(), reader.getnchannels(), reader.getsampwidth()
        if reader.getcomptype() != "NONE" or rate != 44100 or channels < 1 or width != 3:
            raise ValueError("preferred source must remain integer PCM24 at 44100 Hz")
        start, count = round(9.2 * rate), round(6.5 * rate)
        if start + count > reader.getnframes():
            raise ValueError("preferred source is shorter than the selected 9.2--15.7 s interval")
        reader.setpos(start)
        payload = reader.readframes(count)
    if len(payload) != count * channels * width:
        raise ValueError("preferred excerpt data is truncated")
    samples = decode_pcm(payload, width, channels)[:, 0].copy()
    return {
        "name": "preferred_06_excerpt_down7", "sample_rate": rate, "semitones": -7.0,
        "samples": samples, "blocks": [32, 64, 128],
        "source": {"path": str(path), "read_start_frame": start, "read_frame_count": count,
                   "audition_start_seconds": 9.7, "audition_duration_seconds": 6.0,
                   "preroll_seconds": 0.5, "selected_channel": 0, "source_channels": channels,
                   "excerpt_encoded_sha256": hashlib.sha256(payload).hexdigest(),
                   "hash_scope": "selected interleaved PCM payload only; not the whole source"},
    }


def waveform_error(samples, reference):
    counts_match = len(samples) == len(reference)
    finite = bool(np.all(np.isfinite(samples)))
    result = {"frame_counts_match": counts_match, "all_finite": finite}
    if counts_match and finite:
        difference = samples - reference
        maximum = float(np.max(np.abs(difference))) if len(difference) else 0.0
        rms_error = float(np.sqrt(np.mean(difference * difference))) if len(difference) else 0.0
        reference_rms = float(np.sqrt(np.mean(reference * reference))) if len(reference) else 0.0
        result.update({"max_absolute_error": maximum, "rms_error": rms_error,
                       "error_rms_over_reference_rms": rms_error / reference_rms if reference_rms else None})
    return result


def write_float_wav(path, samples, sample_rate, latency_samples, block):
    """Store the existing complete stream as float32 WAV, including fact chunk."""
    encoded_samples = samples.astype("<f4")
    if not np.all(np.isfinite(encoded_samples)):
        raise ValueError("native listening stream is not representable as finite float32")
    payload = encoded_samples.tobytes()
    format_chunk = b"fmt " + struct.pack("<IHHIIHHH", 18, 3, 1, sample_rate,
                                        sample_rate * 4, 4, 32, 0)
    fact_chunk = b"fact" + struct.pack("<II", 4, len(samples))
    body = b"WAVE" + format_chunk + fact_chunk + b"data" + struct.pack("<I", len(payload)) + payload
    encoded = b"RIFF" + struct.pack("<I", len(body)) + body
    with path.open("xb") as stream:
        stream.write(encoded)
    audition_start = round(0.5 * sample_rate) + latency_samples
    return {"path": str(path), "codec": "IEEE float32 WAV", "sample_rate": sample_rate,
            "channels": 1, "frames": len(samples), "encoded_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(), "native_block_frames": block,
            "audition_start_frame": audition_start,
            "audition_end_frame_exclusive": audition_start + round(6.0 * sample_rate),
            "processing": "complete native stream; float32 encoding only; no crop, normalization, limiting, or resampling",
            "reference_variant": "native flat-spectrum stability fix; differs from the preserved original prototype"}


def compare_case(runner, scratch, fixture, window, tolerance, benchmark, listening_output=None):
    config = {"sample_rate": fixture["sample_rate"], "semitones": fixture["semitones"],
              "analysis_size": 2048 if window == "asymmetric" else 384,
              "synthesis_size": 384, "hop": 96, "window": window}
    reference_engine = StableTransportEngine(**config)
    samples = np.asarray(fixture["samples"], dtype=np.float64)
    reference = np.concatenate((reference_engine.process(samples), reference_engine.flush()))
    original = None
    if fixture["name"] == "preferred_06_excerpt_down7":
        original_engine = OriginalTransportEngine(**config)
        original = np.concatenate((original_engine.process(samples), original_engine.flush()))
    input_path = scratch / "input.f64"
    samples.astype("<f8", copy=False).tofile(input_path)
    results = []
    for block in fixture["blocks"]:
        output_path = scratch / ("output-{}-{}-{}.f64".format(fixture["name"], window, block))
        command = [str(runner), "--input", str(input_path), "--output", str(output_path),
                   "--sample-rate", str(config["sample_rate"]), "--semitones", str(config["semitones"]),
                   "--analysis-size", str(config["analysis_size"]), "--synthesis-size", "384",
                   "--hop", "96", "--window", window, "--block", str(block)]
        if benchmark:
            command.append("--benchmark")
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, check=False)
        result = {"fixture": fixture["name"], "config": config, "block_frames": block,
                  "reference_frames": len(reference), "input_frames": len(samples),
                  "tolerance_max_absolute": tolerance, "reference_variant": "StableTransportEngine"}
        if "first_nonzero_frame" in fixture:
            result["first_nonzero_frame"] = fixture["first_nonzero_frame"]
        if "source" in fixture:
            result["source"] = fixture["source"]
        if completed.returncode != 0:
            result.update({"passed": False, "error": completed.stderr.strip(),
                           "runner_returncode": completed.returncode})
            results.append(result)
            continue
        native_report = json.loads(completed.stdout)
        native = np.fromfile(output_path, dtype="<f8")
        result["runner"] = native_report
        result["native_frames"] = len(native)
        error = waveform_error(native, reference)
        result.update(error)
        counts_match = error["frame_counts_match"]
        latency_match = native_report["latency_samples"] == reference_engine.latency_samples
        result["frame_counts_match"] = counts_match
        result["declared_latency_matches"] = latency_match
        if counts_match and result["all_finite"]:
            result["passed"] = error["max_absolute_error"] <= tolerance and latency_match
        else:
            result["passed"] = False
        if original is not None:
            result["original_prototype_comparison"] = {
                "reference_variant": "preserved original TransportEngine",
                "used_for_acceptance": False,
                **waveform_error(native, original),
            }
            if listening_output is not None and block == 128:
                if result["passed"]:
                    result["listening_output"] = write_float_wav(
                        listening_output, native, fixture["sample_rate"], native_report["latency_samples"], block)
                else:
                    result["listening_output_not_written"] = "native/stable parity failed"
        results.append(result)
        output_path.unlink()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", type=Path, required=True, help="built pitchwing_render executable")
    parser.add_argument("--output", type=Path, help="explicit new JSON report; default stdout")
    parser.add_argument("--tolerance", type=float, default=1e-10)
    parser.add_argument("--benchmark", action="store_true", help="include bounded process-call timing")
    parser.add_argument("--skip-stem", action="store_true", help="explicit synthetic-only check")
    parser.add_argument("--stem", type=Path, default=ROOT / "stems" / "06.wav")
    parser.add_argument("--listening-output", type=Path,
                        help="explicit new /tmp float32 WAV of the native preferred excerpt")
    parser.add_argument("--archive-stem-input", type=Path,
                        help="explicit new /tmp raw f64 excerpt input for bounded timing reruns")
    args = parser.parse_args()
    if not args.runner.is_file():
        parser.error("native runner does not exist")
    if not np.isfinite(args.tolerance) or args.tolerance <= 0:
        parser.error("tolerance must be finite and positive")
    if args.output is not None:
        if args.output.exists():
            parser.error("output already exists; select a new path")
        if not args.output.parent.is_dir():
            parser.error("output parent directory does not exist")
    if not args.skip_stem and not args.stem.is_file():
        parser.error("preferred 06.wav is missing; supply --stem or explicitly use --skip-stem")
    audio_paths = [path for path in (args.listening_output, args.archive_stem_input) if path is not None]
    if args.skip_stem and audio_paths:
        parser.error("listening/archive output requires the preferred stem case")
    for path in audio_paths:
        if Path("/tmp") not in path.resolve().parents:
            parser.error("listening/archive outputs must be under /tmp")
        if path.exists() or not path.parent.is_dir():
            parser.error("listening/archive output must be a new path in an existing directory")
    all_outputs = audio_paths + ([args.output] if args.output is not None else [])
    if len({path.resolve() for path in all_outputs}) != len(all_outputs):
        parser.error("each requested output must use a different path")
    source_paths = [Path(__file__).resolve(), ROOT / "tools" / "pitchwing_render.cpp",
                    ROOT / "include" / "pitchwing" / "Engine.hpp", ROOT / "src" / "Engine.cpp",
                    ROOT / "experiments" / "transport" / "engine.py",
                    ROOT / "experiments" / "transport" / "stable_reference.py",
                    ROOT / "experiments" / "corpus" / "audit_stems.py"]
    result = {
        "schema_version": 2,
        "purpose": "native parity with an explicit deterministic stability variant; known DSP defects remain",
        "reference_variant": {
            "class": "StableTransportEngine",
            "original_file_preserved": "experiments/transport/engine.py",
            "flat_spectrum_policy": "nonzero interior relative spread <=1e-12 selects candidate bin 1",
            "peak_cap_tie_order": "magnitude then bin index, retaining the greatest 64",
            "acceptance_reference": "stable variant, not the original prototype",
        },
        "environment": {"python": sys.version.split()[0], "numpy": np.__version__,
                        "platform": platform.platform()},
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in source_paths if path.is_file()},
        "runner_sha256": hashlib.sha256(args.runner.read_bytes()).hexdigest(),
        "tolerance_max_absolute": args.tolerance,
        "stem_included": not args.skip_stem,
        "limitations": [
            "Parity preserves the reference's unresolved-dyad and shifted-DC defects.",
            "The deterministic flat-spectrum fix changes output from the original prototype and requires listening.",
            "These are static-ratio mono tests, not quality or supported-tuning guarantees.",
            "Timing under WSL is not a target-native live callback deadline result.",
            "Raw scratch is removed except explicitly requested /tmp listening/input artifacts.",
        ],
        "cases": [],
    }
    runner = args.runner.resolve()
    with tempfile.TemporaryDirectory(prefix="pitchwing-native-parity-", dir="/tmp") as directory:
        scratch = Path(directory)
        for fixture in synthetic_fixtures():
            for window in fixture.get("windows", ("asymmetric", "symmetric")):
                result["cases"].extend(compare_case(runner, scratch, fixture, window,
                                                    args.tolerance, args.benchmark))
        if not args.skip_stem:
            fixture = preferred_excerpt(args.stem)
            if args.archive_stem_input is not None:
                payload = fixture["samples"].astype("<f8", copy=False).tobytes()
                with args.archive_stem_input.open("xb") as stream:
                    stream.write(payload)
                result["archived_stem_input"] = {
                    "path": str(args.archive_stem_input), "format": "mono little-endian float64 raw",
                    "frames": len(fixture["samples"]), "sample_rate": fixture["sample_rate"],
                    "sha256": hashlib.sha256(payload).hexdigest(), "source": fixture["source"],
                }
            result["cases"].extend(compare_case(runner, scratch, fixture, "asymmetric",
                                                args.tolerance, args.benchmark, args.listening_output))
    result["case_count"] = len(result["cases"])
    result["passed"] = all(case["passed"] for case in result["cases"])
    result["failed_cases"] = ["{}/{}/block{}".format(case["fixture"], case["config"]["window"],
                                                    case["block_frames"])
                              for case in result["cases"] if not case["passed"]]
    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
        print("{}: {} native/reference cases; wrote {}".format(
            "PASS" if result["passed"] else "FAIL", result["case_count"], args.output))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
