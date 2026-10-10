"""Conditioning of a short-frame two-lobe amplitude fit with known frequencies.

Historian option (2026-10-10 multires gauntlet): take w1, w2 from a longer
analysis, fit X[k] = sum_i a_i A(w_k - w_i) + conj(a_i) A(w_k + w_i) over the
merged region's bins of the N=2048 frame. Report condition number, amplitude
error (dB) and frame-to-frame amplitude p-p for stationary dyads, with the
frequencies exact or biased by a few cents. Usage: python3 twolobe_probe.py
"""
import numpy as np

from estimator_fit import A, N, analysis, fs

H = 96


def design(freqs, ks):
    cols = []
    for f in freqs:
        w = f / fs * N
        Ap, Am = A(ks - w), A(ks + w)
        cols += [Ap + Am, 1j * (Ap - Am)]  # re a, im a
    M = np.array(cols).T
    return np.vstack([M.real, M.imag])


def run(freqs, amps, ks, bias_cents):
    t = np.arange(int(1.5 * fs) + N)
    rng = np.random.default_rng(1)
    ph = rng.uniform(0, 2 * np.pi, len(freqs))
    x = sum(a * np.cos(2 * np.pi * f / fs * t + p) for f, a, p in zip(freqs, amps, ph))
    est = [f * 2 ** (b / 1200) for f, b in zip(freqs, bias_cents)]
    M = design(est, ks)
    cond = np.linalg.cond(M)
    mags = []
    for start in range(int(0.5 * fs), int(1.5 * fs), H):
        X = np.fft.fft(x[start:start + N] * analysis)[ks]
        sol, *_ = np.linalg.lstsq(M, np.concatenate([X.real, X.imag]), rcond=None)
        mags.append([2 * abs(complex(sol[2 * i], sol[2 * i + 1])) for i in range(len(freqs))])
    mags = np.array(mags)
    err = 20 * np.log10(mags.mean(0) / amps)
    pp = 20 * np.log10(mags.max(0) / mags.min(0))
    return cond, err, pp


if __name__ == "__main__":
    cases = {"E2+G#2 0.9 bin": [82.41, 103.83], "E2+A2 1.2 bin": [82.41, 110.0],
             "E2+F#2 0.45 bin": [82.41, 92.5], "F#1+A#1 0.6 bin": [46.25, 58.27]}
    for name, fr in cases.items():
        ks = np.arange(0, 9)
        for bias in ([0, 0], [2, -2], [5, -5], [10, 0]):
            c, e, p = run(fr, np.array([0.25, 0.25]), ks, bias)
            print(f"{name:16s} bias {bias!s:9s} cond {c:8.1f}  amp err dB {np.round(e, 2)}  "
                  f"frame p-p dB {np.round(p, 2)}")


def cost2(X, ks, w1, w2):
    M = design([w1 * fs / N, w2 * fs / N], ks)
    rhs = np.concatenate([X.real, X.imag])
    sol, *_ = np.linalg.lstsq(M, rhs, rcond=None)
    r = M @ sol - rhs
    return float(r @ r), sol


def fit2(X, ks, lo, hi):
    """Two-tone frequency fit (bins) by coarse grid + 2-D refinement."""
    best = (np.inf, lo, hi)
    for w1 in np.arange(lo, hi, 0.1):
        for w2 in np.arange(w1 + 0.2, hi, 0.1):
            c, _ = cost2(X, ks, w1, w2)
            if c < best[0]:
                best = (c, w1, w2)
    c, w1, w2 = best
    step = 0.05
    for _ in range(14):
        cands = [(cost2(X, ks, w1 + i * step, w2 + j * step)[0], w1 + i * step, w2 + j * step)
                 for i in (-1, 0, 1) for j in (-1, 0, 1)]
        c, w1, w2 = min(cands)
        step *= 0.6
    return w1, w2, c


def short_only(freqs, amps, ks, noise_db=None, decay_s=None, harm=False):
    t = np.arange(int(0.6 * fs) + N)
    rng = np.random.default_rng(2)
    x = sum(a * np.cos(2 * np.pi * f / fs * t + rng.uniform(0, 6.3)) for f, a in zip(freqs, amps))
    if harm:
        x = x + sum(0.5 * a * np.cos(4 * np.pi * f / fs * t + rng.uniform(0, 6.3)) for f, a in zip(freqs, amps))
    if decay_s:
        x = x * np.exp(-t / fs / decay_s)
    if noise_db is not None:
        x = x + 10 ** (noise_db / 20) * rng.standard_normal(len(t))
    errs = []
    for start in range(int(0.1 * fs), int(0.6 * fs), 4 * H):
        X = np.fft.fft(x[start:start + N] * analysis)[ks]
        w1, w2, _ = fit2(X, ks, ks[0] - 0.5 if ks[0] > 0 else 0.05, ks[-1] + 0.5)
        errs.append([1200 * np.log2(w1 * fs / N / freqs[0]), 1200 * np.log2(w2 * fs / N / freqs[1])])
    e = np.array(errs)
    return np.abs(e.mean(0)).round(1), (e.max(0) - e.min(0)).round(1)


if __name__ == "__main__":
    print("short-frame two-tone frequency fit, ks 0..6: |mean err| cents, p-p cents")
    ks = np.arange(0, 7)
    for name, fr in {"E2+G#2": [82.41, 103.83], "E2+F#2": [82.41, 92.5], "F#1+A#1": [46.25, 58.27]}.items():
        for label, kw in {"clean": {}, "noise -60": {"noise_db": -60}, "noise -40": {"noise_db": -40},
                          "decay 1 s": {"decay_s": 1.0}, "harmonics": {"harm": True}}.items():
            print(f"{name:8s} {label:10s}", *short_only(fr, [0.25, 0.25], ks, **kw))
