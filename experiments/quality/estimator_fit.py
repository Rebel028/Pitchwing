"""Image-aware lobe fit for the LiveEngine analysis window.

Model per bin k near a peak: X[k] = a*A(w_k - w) + conj(a)*A(w_k + w), where A is
the complex spectrum of the asymmetric analysis window (time origin at the
newest sample).  Fit w by 1-D search on 3 bins; compare with parabola and IF.
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
OS = 64  # table oversampling per bin
# window spectrum with time origin at the newest sample (index N-1): A(w) = sum w[n] e^{-j w (n-(N-1))}
pad = np.zeros(N * OS)
pad[:N] = analysis
table = np.fft.fft(pad) * np.exp(1j * (2 * np.pi * np.arange(N * OS) / (N * OS)) * (N - 1))
tab_bins = np.fft.fftfreq(N * OS) * N  # in bins, -N/2..N/2


def A(offset_bins):
    """Interpolate table at offset (bins), vectorised."""
    pos = (offset_bins * OS) % (N * OS)
    i0 = np.floor(pos).astype(int)
    f = pos - i0
    i1 = (i0 + 1) % (N * OS)
    return table[i0] * (1 - f) + table[i1] * f


def model(X, k, wbins):
    ks = np.array([k - 1, k, k + 1])
    Ap = A(ks - wbins)
    Am = A(ks + wbins)
    # solve for complex a minimising |X - a Ap - conj(a) Am|^2: linear in (re a, im a)
    # X = a Ap + conj(a) Am  ->  real 6x2 system
    M = np.zeros((6, 2))
    rhs = np.zeros(6)
    for i in range(3):
        # a = x + j y: a*Ap = (x + jy)Ap, conj(a)*Am = (x - jy)Am
        M[2 * i] = [Ap[i].real + Am[i].real, -Ap[i].imag + Am[i].imag]
        M[2 * i + 1] = [Ap[i].imag + Am[i].imag, Ap[i].real - Am[i].real]
        rhs[2 * i] = X[ks[i]].real
        rhs[2 * i + 1] = X[ks[i]].imag
    sol, *_ = np.linalg.lstsq(M, rhs, rcond=None)
    resid = M @ sol - rhs
    return float(resid @ resid)


def fit(X, k, w0):
    # coarse-to-fine search +-0.6 bin around w0 (bins)
    lo, hi = w0 - 0.6, w0 + 0.6
    for _ in range(4):
        grid = np.linspace(lo, hi, 13)
        cost = [model(X, k, g) for g in grid]
        j = int(np.argmin(cost))
        lo, hi = grid[max(j - 1, 0)], grid[min(j + 1, 12)]
    return 0.5 * (lo + hi)


def run(f, frames=400, start=1.0, second=None):
    true = 2 * np.pi * f / fs
    out = {"par": [], "if": [], "fit": []}
    prev = None
    t0 = int(start * fs)
    for m in range(frames):
        n0 = t0 + m * H
        t = np.arange(n0 - N + 1, n0 + 1)
        x = np.cos(true * t)
        if second:
            x = x + second[1] * np.cos(2 * np.pi * second[0] / fs * t + 0.7)
        X = np.fft.rfft(x * analysis)
        mag = np.abs(X)
        k = int(np.argmax(mag[1:-1])) + 1
        a, b, c = np.log(mag[k - 1]), np.log(mag[k]), np.log(mag[k + 1])
        frac = 0.5 * (a - c) / (a - 2 * b + c)
        wpar = k + np.clip(frac, -0.5, 0.5)
        out["par"].append(wpar)
        if prev is not None:
            cross = X[k] * np.conj(prev[k])
            res = np.angle(cross * np.exp(-1j * binw * k * H))
            w = k + res / H / binw
            out["if"].append(w if abs(w - wpar) <= 2 else wpar)
        else:
            out["if"].append(wpar)
        out["fit"].append(fit(X, k, wpar))
        prev = X
    tb = f / fs * N
    cents = lambda v: 1200 * np.log2(np.array(v) / tb)
    return {key: cents(v) for key, v in out.items()}


if __name__ == "__main__":
    import sys
    print("window |A| dB at bin offsets:", " ".join(f"{d}:{20*np.log10(abs(A(d))/abs(A(0))):.0f}" for d in [1, 2, 3, 4, 6, 8, 12, 16, 24]))
    cases = [("B0", 30.87), ("E1", 41.20), ("F#1", 46.25), ("E2", 82.41), ("A2", 110.0), ("E3", 164.81), ("A4", 440.0)]
    for name, f in cases:
        r = run(f)
        print(f"{name:4s} bin={f/fs*N:6.3f} " + "  ".join(f"{k}: mean {v.mean():+6.2f} pp {np.ptp(v):6.2f}" for k, v in r.items()))
    print("-- with 2nd harmonic at -6 dB (E2 + 164.8 Hz) and E2+G#2 dyad")
    r = run(82.41, second=(164.82, 0.5))
    print("E2+h2 " + "  ".join(f"{k}: mean {v.mean():+6.2f} pp {np.ptp(v):6.2f}" for k, v in r.items()))
    r = run(82.41, second=(103.83, 1.0))
    print("E2+G#2 " + "  ".join(f"{k}: mean {v.mean():+6.2f} pp {np.ptp(v):6.2f}" for k, v in r.items()))
