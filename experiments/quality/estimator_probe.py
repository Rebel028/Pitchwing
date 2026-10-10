"""Replicate LiveEngine.findRegions omega estimators on a stationary tone.

Prints per-frame parabola and IF estimates (cents vs true) for several tone
frequencies so the E2 +7/-4.7 cent bias can be attributed.
"""
import numpy as np

fs = 48000.0
N = 2048
H = 96
L = 384
pivot = N - L // 2
idx = np.arange(N)
analysis = np.where(idx < pivot, np.sin(np.pi * idx / (2.0 * pivot)),
                    np.cos(np.pi * (idx - pivot) / (2.0 * (N - pivot))))
binw = 2 * np.pi / N


def estimates(f, frames=1000, start=1.0):
    true = 2 * np.pi * f / fs
    par, inst = [], []
    prev = None
    t0 = int(start * fs)
    for m in range(frames):
        n0 = t0 + m * H
        t = np.arange(n0 - N + 1, n0 + 1)  # history ends at newest sample
        x = np.cos(true * t) * analysis
        X = np.fft.rfft(x)
        mag = np.abs(X)
        k = int(np.argmax(mag[1:-1])) + 1
        a, b, c = np.log(mag[k - 1]), np.log(mag[k]), np.log(mag[k + 1])
        frac = 0.5 * (a - c) / (a - 2 * b + c)
        omega = binw * (k + np.clip(frac, -0.5, 0.5))
        par.append(omega)
        if prev is not None:
            cross = X[k] * np.conj(prev[k])
            res = np.angle(cross * np.exp(-1j * binw * k * H))
            w = binw * k + res / H
            inst.append(w if abs(w - omega) <= 2 * binw else omega)
        prev = X
    par = np.array(par[1:])
    inst = np.array(inst)
    cents = lambda w: 1200 * np.log2(w / true)
    return k, cents(par), cents(inst)


for name, f in [("B0", 30.87), ("E1", 41.20), ("F#1", 46.25), ("E2", 82.41),
                ("A2", 110.0), ("E3", 164.81), ("A4", 440.0)]:
    k, cp, ci = estimates(f)
    print(f"{name:4s} f={f:7.2f} bin={f/fs*N:6.3f} peakbin={k}  parabola mean {cp.mean():+7.2f} c (pp {np.ptp(cp):6.2f})"
          f"  IF mean {ci.mean():+7.2f} c (pp {np.ptp(ci):6.2f})")
