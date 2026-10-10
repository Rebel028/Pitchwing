#!/usr/bin/env python3
"""Real-material gate: render user guitar excerpts and compare levels with dry.

Synthetic fixtures (stationary tones, smooth gates) missed a transient blow-up
in step 9 (peaks 359x full scale at pick attacks). Every engine step must pass
this gate as well. Cases: stems/06.wav channel 0, 9.2-15.7 s at -7/-2, and
stems/chord.wav (whole DI) at +-12, 44.1 kHz.

Per case: wet peak, samples above full scale, wet/dry RMS, and the attack
envelope ratio: 5 ms max-abs blocks of the latency-aligned wet over the dry
maximum within +-25 ms, where that is above -20 dB re the largest (max, p99).
Fails when the wet peak exceeds 1.25x the dry peak or the envelope ratio max/p99
exceeds 2/1.5 (steps 4 and 8, the builds the user accepted, reach 1.11, 1.47
and 1.31; step 10 reached 255x peak).

Usage: real_material_gate.py --render NAME=BIN [--render ...] --scratch DIR
       --out JSON [--stems DIR]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "corpus"))
from audit_stems import load_pcm_wav  # noqa: E402

CASES = [("06", "06.wav", 9.2, 15.7, (-7, -2)), ("chord", "chord.wav", 0.0, None, (12, -12))]
RATE = 44100
LATENCY = 439  # pitchwing_live_render at 44.1 kHz
BLOCK = round(0.005 * RATE)
SPREAD = 5  # blocks
PEAK_LIMIT = 1.25
ENVELOPE_LIMIT = 2.0
ENVELOPE_P99_LIMIT = 1.5


def envelope(x):
    count = len(x) // BLOCK
    return np.abs(x[:count * BLOCK]).reshape(count, BLOCK).max(axis=1)


def metrics(dry, wet):
    aligned = wet[LATENCY:LATENCY + len(dry)]
    dry_env, wet_env = envelope(dry), envelope(aligned)
    # Low notes (F#1: 22 ms period) make 5 ms blocks waveform-shaped; compare
    # with the dry level within +-25 ms, not the dry block itself.
    padded = np.pad(dry_env, SPREAD, mode="edge")
    dry_env = np.lib.stride_tricks.sliding_window_view(padded, 2 * SPREAD + 1).max(axis=1)
    loud = dry_env > 0.1 * dry_env.max()
    ratio = wet_env[loud] / dry_env[loud]
    peak = float(np.abs(wet).max())
    result = {
        "peak": peak,
        "dry_peak": float(np.abs(dry).max()),
        "over_full_scale": int((np.abs(wet) > 1.0).sum()),
        "rms_ratio": float(np.sqrt(np.mean(aligned ** 2) / np.mean(dry ** 2))),
        "envelope_ratio_max": float(ratio.max()),
        "envelope_ratio_p99": float(np.percentile(ratio, 99)),
        "envelope_ratio_max_at_s": float(np.flatnonzero(loud)[ratio.argmax()] * BLOCK / RATE),
    }
    result["pass"] = bool(np.isfinite(peak) and peak <= PEAK_LIMIT * result["dry_peak"]
                          and result["envelope_ratio_max"] <= ENVELOPE_LIMIT
                          and result["envelope_ratio_p99"] <= ENVELOPE_P99_LIMIT)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--render", action="append", required=True, help="NAME=path to pitchwing_live_render")
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stems", type=Path, default=Path(__file__).resolve().parents[1] / "stems")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output exists; choose a new path to preserve evidence")
    if not args.stems.is_dir():  # worktrees have no stems/; use the main checkout's
        args.stems = Path(__file__).resolve().parents[4] / "stems"
    args.scratch.mkdir(parents=True, exist_ok=True)
    renders = dict(item.split("=", 1) for item in args.render)
    report = {"latency": LATENCY, "peak_limit": PEAK_LIMIT, "envelope_limit": ENVELOPE_LIMIT,
              "envelope_p99_limit": ENVELOPE_P99_LIMIT, "cases": {}}
    failed = False
    for name, wav, start, stop, shifts in CASES:
        source = args.scratch / f"{name}.f64"
        if not source.exists():
            samples, rate, _ = load_pcm_wav(args.stems / wav)
            if rate != RATE:
                raise ValueError(f"{wav}: expected {RATE} Hz, got {rate}")
            stop_index = len(samples) if stop is None else round(stop * rate)
            np.ascontiguousarray(samples[round(start * rate):stop_index, 0], dtype=np.float64).tofile(source)
        dry = np.fromfile(source)
        jobs = []
        for label, binary in renders.items():
            for shift in shifts:
                output = args.scratch / f"{label}-{name}_{shift}.f64"
                jobs.append((label, shift, output, subprocess.Popen(
                    [binary, str(source), str(output), str(RATE), str(shift), "64"], stdout=subprocess.DEVNULL)))
        for label, shift, output, process in jobs:
            if process.wait() != 0:
                raise RuntimeError(f"{label} failed on {name} {shift}")
            result = metrics(dry, np.fromfile(output))
            report["cases"][f"{label}/{name}/{shift:+d}"] = result
            failed = failed or not result["pass"]
            print(f"{label:10s} {name:5s} {shift:+3d}  peak {result['peak']:8.3f} (dry {result['dry_peak']:.3f})"
                  f"  >1 {result['over_full_scale']:6d}  rms {result['rms_ratio']:.3f}"
                  f"  env max {result['envelope_ratio_max']:7.2f} @{result['envelope_ratio_max_at_s']:6.2f}s"
                  f" p99 {result['envelope_ratio_p99']:.2f}  {'pass' if result['pass'] else 'FAIL'}")
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
