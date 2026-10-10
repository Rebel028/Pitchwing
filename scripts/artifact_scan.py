#!/usr/bin/env python3
"""Scan raw float64 mono audio for click-like discontinuities and HF bursts.

usage: artifact_scan.py <file.f64> <rate> [--ref ref.f64 --offset N] [--json out.json]

Reports per-second RMS, max |x[n]-x[n-1]| relative to a 20 ms RMS envelope,
counts of relative steps > 1, and absolute step positions > 0.03. With --ref,
the file is compared against a reference aligned by --offset samples (engine
latency), so wet/dry high-frequency (>2 kHz) energy ratios are printed per second.
Diagnostic only: thresholds are heuristics, not perceptual results.
"""
import argparse
import json
import sys

import numpy as np


def envelope(x, w):
    return np.sqrt(np.convolve(x * x, np.ones(w) / w, "same")) + 1e-9


def highpass(x, rate, cutoff=2000.0):
    spectrum = np.fft.rfft(x)
    spectrum[np.fft.rfftfreq(len(x), 1.0 / rate) < cutoff] = 0
    return np.fft.irfft(spectrum, len(x))


def scan(x, rate):
    w = int(0.02 * rate)
    d = np.abs(np.diff(x))
    r = d / envelope(x, w)[1:]
    steps = np.where(d > 0.03)[0]
    rows = []
    for sec in range(int(np.ceil(len(x) / rate))):
        s = slice(sec * rate, (sec + 1) * rate)
        rms = float(np.sqrt(np.mean(x[s] ** 2)) + 1e-12)
        rows.append({"t": sec, "rms_db": round(20 * np.log10(rms), 1),
                     "max_rel_step": round(float(r[s].max()), 3) if r[s].size else 0.0,
                     "rel_steps_gt1": int((r[s] > 1).sum()), "abs_steps_gt0p03": int(((steps >= s.start) & (steps < s.stop)).sum())})
    return rows, steps


def main():
    p = argparse.ArgumentParser()
    p.add_argument("file")
    p.add_argument("rate", type=int)
    p.add_argument("--ref")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--json")
    a = p.parse_args()
    x = np.fromfile(a.file)
    rows, steps = scan(x, a.rate)
    out = {"file": a.file, "rate": a.rate, "frames": len(x), "peak": float(np.abs(x).max()),
           "nonfinite": int((~np.isfinite(x)).sum()), "per_second": rows,
           "abs_steps_positions": steps.tolist()[:500]}
    if a.ref:
        ref = np.fromfile(a.ref)
        y = x[a.offset:a.offset + len(ref)]
        n = min(len(y), len(ref))
        yh, rh = highpass(y[:n], a.rate), highpass(ref[:n], a.rate)
        for row in out["per_second"]:
            s = slice(row["t"] * a.rate, (row["t"] + 1) * a.rate)
            if s.start >= n:
                break
            row["hf_wet_over_dry"] = round(float((yh[s] ** 2).sum() / ((rh[s] ** 2).sum() + 1e-18)), 3)
    for row in out["per_second"]:
        print(row)
    print("peak", out["peak"], "nonfinite", out["nonfinite"], "abs steps", len(steps))
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
