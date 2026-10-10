"""Long-frame frequencies + short-frame amplitude split for merged low regions.

Design candidate after the 2026-10-10 multires gauntlet (historian option 3):
a past-heavy N_low = k*N analysis (same construction as the engine window)
supplies w for each long peak inside a merged short region; the short frame
fits only the complex amplitudes (linear least squares, image terms included).
Prints long-w error (cents, mean and p-p over frames) and short-fit amplitude
p-p (dB) for E2+G#2 / E2+F#2 / F#1+A#1 with harmonics, decay and noise.
"""
import numpy as np

fs, H, FALL = 48000.0, 96, 192
PASSES = 0
OS = 64


def window(n):
    pivot = n - FALL
    i = np.arange(n)
    return np.where(i < pivot, np.sin(np.pi * i / (2.0 * pivot)), np.cos(np.pi * (i - pivot) / (2.0 * (n - pivot))))


class Lobe:
    def __init__(self, n):
        self.n, self.w = n, window(n)
        pad = np.zeros(n * OS)
        pad[:n] = self.w
        self.t = np.fft.fft(pad)  # time origin at frame start, like the engine's FFT

    def __call__(self, off):
        pos = np.mod(np.asarray(off, float) * OS, self.n * OS)
        i0 = np.floor(pos).astype(int) % (self.n * OS)
        f = pos - np.floor(pos)
        return self.t[i0] * (1 - f) + self.t[(i0 + 1) % (self.n * OS)] * f


def design(lobe, wbins, ks):
    cols = []
    for w in wbins:
        p, m = lobe(ks - w), lobe(ks + w)
        cols += [p + m, 1j * (m - p)]
    M = np.array(cols).T
    return np.vstack([M.real, M.imag])


def solve(lobe, X, ks, wbins):
    M = design(lobe, wbins, ks)
    rhs = np.concatenate([X[ks].real, X[ks].imag])
    sol, *_ = np.linalg.lstsq(M, rhs, rcond=None)
    r = M @ sol - rhs
    return float(r @ r), sol


def fit1(lobe, X, k, centre=None):
    centre = k if centre is None else centre
    lo, hi = max(centre - 0.6, 0.0), centre + 0.6
    ks = np.array([k - 1, k, k + 1])
    for _ in range(5):
        g = np.linspace(lo, hi, 13)
        c = [solve(lobe, X, ks, [w])[0] for w in g]
        j = int(np.argmin(c))
        st = g[1] - g[0]
        lo, hi = g[j] - st, g[j] + st
    return 0.5 * (lo + hi)


def peaks(mag, kmax):
    big = mag[1:kmax].max()
    return [k for k in range(1, kmax) if mag[k] >= mag[k - 1] and mag[k] > mag[k + 1] and mag[k] > 1e-3 * big]


def case(freqs, k_long, noise_db=None, decay_s=None, harm=True, N=2048):
    NL = k_long * N
    sl, ll = Lobe(N), Lobe(NL)
    rng = np.random.default_rng(3)
    t = np.arange(int(1.0 * fs) + NL)
    x = np.zeros(len(t))
    for f in freqs:
        for h, a in ((1, 0.25), (2, 0.12), (3, 0.06), (4, 0.04)) if harm else ((1, 0.25),):
            x += a * np.cos(2 * np.pi * h * f / fs * t + rng.uniform(0, 6.3))
    if decay_s:
        x *= np.exp(-t / fs / decay_s)
    if noise_db is not None:
        x += 10 ** (noise_db / 20) * rng.standard_normal(len(t))
    werr, amps = [], []
    for end in range(NL + int(0.2 * fs), len(t), 4 * H):
        XL = np.fft.rfft(x[end - NL:end] * ll.w)
        pk = peaks(np.abs(XL), int(400 / fs * NL))
        ws = [fit1(ll, XL, k) for k in pk]
        # joint refit of clusters of close peaks: coordinate descent on each w,
        # amplitudes solved jointly over the cluster's bins
        groups, cur = [], [0]
        for i in range(1, len(pk)):
            if pk[i] - pk[i - 1] < 6:
                cur.append(i)
            else:
                groups.append(cur); cur = [i]
        groups.append(cur)
        for g in groups:
            if len(g) < 2:
                continue
            ks = np.arange(max(pk[g[0]] - 1, 0), pk[g[-1]] + 2)
            for _ in range(PASSES):
                for i in g:
                    lo, hi = ws[i] - 0.6, ws[i] + 0.6
                    for _ in range(4):
                        grid = np.linspace(lo, hi, 9)
                        c = [solve(ll, XL, ks, [ws[j] if j != i else w for j in g])[0] for w in grid]
                        m = int(np.argmin(c)); st = grid[1] - grid[0]
                        lo, hi = grid[m] - st, grid[m] + st
                    ws[i] = 0.5 * (lo + hi)
        hz = np.array(ws) * fs / NL
        got = [hz[np.argmin(np.abs(hz - f))] for f in freqs]
        werr.append([1200 * np.log2(g / f) for g, f in zip(got, freqs)])
        XS = np.fft.rfft(x[end - N:end] * sl.w)
        wsh = [h * N / NL for h in np.array(ws)]  # long bins -> short bins
        ks = np.arange(0, 7)  # merged region of the fundamentals plus margin
        inside = [w for w in wsh if w < 9.5]  # fundamentals and neighbours up to bin 9.5
        _, sol = solve(sl, XS, ks if len(inside) * 2 <= len(ks) * 2 else ks, inside) if len(inside) * 2 <= 14 else (0, None)
        a = [2 * abs(complex(sol[2 * i], sol[2 * i + 1])) / sl.w.sum() for i in range(len(inside))]
        amps.append([a[int(np.argmin(np.abs(np.array(inside) * fs / N - f)))] for f in freqs])
    e, a = np.array(werr), 20 * np.log10(np.array(amps))
    return e.mean(0).round(1), np.ptp(e, 0).round(1), a.mean(0).round(2), np.ptp(a, 0).round(2)


if __name__ == "__main__":
    print("k_long case: long-w mean cents, p-p cents | short amp mean dBFS (true -12.04), p-p dB")
    import sys
    PASSES = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    for k in (4,):
        for name, fr in {"E2+G#2": [82.41, 103.83], "E2+F#2": [82.41, 92.5], "F#1+A#1": [46.25, 58.27]}.items():
            for label, kw in {"harm": {}, "harm+n-60": {"noise_db": -60}, "harm+decay1s": {"decay_s": 1.0},
                              "harm+n-40": {"noise_db": -40}}.items():
                try:
                    print(k, f"{name:8s} {label:13s}", *case(fr, k, **kw))
                except Exception as ex:  # unresolved at this k: report, keep going
                    print(k, f"{name:8s} {label:13s} FAILED {type(ex).__name__}: {ex}")
