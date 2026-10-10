#!/usr/bin/env python3
"""Original unity/WOLA timing diagnostic. NOT a pitch-shifter benchmark.

Run: python architecture-experiment.py
Requires NumPy. Writes results.json next to this script.

At frame end t, analyse x[t-N+1:t+1]. The synthesis window is nonzero
only on the newest L samples. Schedule each reconstructed sample at its
original absolute sample index plus D=L-1. An extra whole-frame FIFO is
not used. FFT/iFFT are intentionally a unity spectral operation.
"""
from __future__ import annotations

import json
from pathlib import Path
import platform

import numpy as np


def make_windows(n_fft: int, synthesis_length: int, hop: int):
    assert n_fft > synthesis_length
    assert synthesis_length % hop == 0
    overlaps = synthesis_length // hop
    assert overlaps >= 2 and synthesis_length % 2 == 0
    peak = n_fft - synthesis_length // 2
    n = np.arange(n_fft, dtype=np.float64)
    analysis = np.empty(n_fft, dtype=np.float64)
    analysis[:peak] = np.sin(0.5 * np.pi * n[:peak] / peak)
    analysis[peak:] = np.cos(
        0.5 * np.pi * (n[peak:] - peak) / (n_fft - peak)
    )
    q = np.arange(synthesis_length, dtype=np.float64)
    # Periodic Hann, normalized to a unit sum across L/hop overlaps.
    product = (1.0 - np.cos(2.0 * np.pi * q / synthesis_length)) / overlaps
    synthesis = np.zeros(n_fft, dtype=np.float64)
    synthesis[-synthesis_length:] = product / analysis[-synthesis_length:]
    return analysis, synthesis


def stream_unity(x, analysis, synthesis, hop, delay):
    """Sample-indexed scheduler with zero-initialized prehistory and drain.

    Frame operations are batched for convenience; their availability is
    asserted at frame-end timestamps. No nonzero output is scheduled before
    a frame's input exists. This simulates the causal schedule, not RT CPU.
    """
    n_fft = len(analysis)
    n_out = len(x) + delay
    output = np.zeros(n_out + n_fft + hop, dtype=np.float64)
    negative_schedule_count = 0
    first_nonzero_synthesis = int(np.flatnonzero(synthesis)[0])
    for t in range(hop - 1, n_out + hop, hop):
        start = t - n_fft + 1
        block = np.zeros(n_fft, dtype=np.float64)
        lo = max(0, start)
        hi = min(len(x), t + 1)
        if hi > lo:
            block[lo - start:hi - start] = x[lo:hi]
        reconstructed = np.fft.irfft(np.fft.rfft(block * analysis), n=n_fft)
        reconstructed *= synthesis
        earliest = start + first_nonzero_synthesis + delay
        if earliest < t:
            negative_schedule_count += 1
        indices = start + np.arange(n_fft) + delay
        valid = (indices >= 0) & (indices < len(output))
        output[indices[valid]] += reconstructed[valid]
    assert negative_schedule_count == 0
    return output[:n_out], negative_schedule_count


def main():
    n_fft, synthesis_length, hop, sample_rate = 2048, 384, 96, 48000
    delay = synthesis_length - 1
    a, s = make_windows(n_fft, synthesis_length, hop)
    product = a * s
    cola_by_phase = np.array([product[p::hop].sum() for p in range(hop)])
    rng = np.random.default_rng(20261008)
    tests = {
        "white_noise": rng.standard_normal(48000) * 0.1,
        "dc": np.ones(48000) * 0.25,
        "tone_41_203hz": np.sin(2 * np.pi * 41.203 * np.arange(48000) / sample_rate),
        "tone_82_407hz": np.sin(2 * np.pi * 82.407 * np.arange(48000) / sample_rate),
    }
    records = {}
    for name, x in tests.items():
        y, schedule_errors = stream_unity(x, a, s, hop, delay)
        expected = np.pad(x, (delay, 0))
        error = y - expected
        records[name] = {
            "max_abs_error": float(np.max(np.abs(error))),
            "rms_error": float(np.sqrt(np.mean(error**2))),
            "relative_error_db": float(20 * np.log10(
                max(np.linalg.norm(error), 1e-300) / np.linalg.norm(expected))),
            "noncausal_frame_schedules": schedule_errors,
        }
    impulse_delays = []
    impulse_errors = []
    # Probe every input position modulo the hop; one favourable alignment
    # would not validate a stream's declared latency.
    for phase in range(hop):
        x = np.zeros(n_fft + hop)
        x[phase] = 1.0
        y, _ = stream_unity(x, a, s, hop, delay)
        impulse_delays.append(int(np.argmax(np.abs(y))) - phase)
        impulse_errors.append(float(np.max(np.abs(y - np.pad(x, (delay, 0))))))
    positive_synthesis = s > 0
    result = {
        "purpose": "Unity WOLA reconstruction and exact sample schedule only; no pitch shift implemented or measured",
        "environment": {"python": platform.python_version(), "numpy": np.__version__},
        "configuration": {
            "sample_rate": sample_rate,
            "analysis_fft_samples": n_fft,
            "analysis_history_ms": 1000 * n_fft / sample_rate,
            "synthesis_support_samples": synthesis_length,
            "synthesis_support_ms": 1000 * synthesis_length / sample_rate,
            "hop_samples": hop,
            "frame_rate_hz": sample_rate / hop,
            "scheduled_delay_samples": delay,
            "scheduled_delay_ms": 1000 * delay / sample_rate,
            "extra_output_fifo_samples": 0,
        },
        "windows": {
            "cola_max_abs_deviation_from_one": float(np.max(np.abs(cola_by_phase - 1))),
            "minimum_analysis_on_positive_synthesis_support": float(np.min(a[positive_synthesis])),
            "maximum_synthesis_coefficient": float(np.max(s)),
            "minimum_synthesis_coefficient": float(np.min(s)),
            "analysis_energy_centroid_samples_before_frame_end": float(
                (n_fft - 1) - np.dot(np.arange(n_fft), a*a) / np.sum(a*a)),
            "note": "Window division remains bounded here because product and analysis both approach zero together.",
        },
        "unity_tests": records,
        "impulse_tests": {
            "tested_hop_phases": hop,
            "measured_delays_samples": sorted(set(impulse_delays)),
            "worst_max_abs_error": max(impulse_errors),
        },
        "limitations": [
            "No frequency remapping, phase propagation, transient treatment, or instrument audio was tested.",
            "Perfect reconstruction at unity does not imply low artifacts after spectrum modification.",
            "Long historical analysis can cause stale estimates even when output availability is short.",
            "Delay excludes host/device buffers and FFT execution time; an extra FIFO changes the accounting.",
            "No CPU performance, VST3 compatibility, or competitor quality claim follows from this diagnostic.",
        ],
    }
    destination = Path(__file__).with_name("results.json")
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(destination), "configuration": result["configuration"],
                      "impulse_tests": result["impulse_tests"], "windows": result["windows"]}, indent=2))


if __name__ == "__main__":
    main()
