#!/usr/bin/env python3
"""Window study: Q1 origin of hop-rate lines, Q2 window-tail trade, Q3 onset lag.

Q1/Q3 render through pitchwing_live_render; Q2 is NumPy only. The NumPy frame
model reproduces LiveEngine::prepareFrame/renderRegion for a steady tone with
exact omega: window A, FFT, engine peak picking (local maxima >= 1e-4 of the
largest, midpoint partition, parabola omega, IF accepted within 2 bins), each
region's bins x2, IFFT, last L samples times S*exp(j*omega_r*u*n), OLA at hop H,
plus the unrotated DC term dc*S. Output is aligned with the input (no D delay).
"""
import argparse, json, os, subprocess
import numpy as np

FS, H, L, N, D = 48000, 96, 384, 2048, 479
PI = np.pi
BIN = FS / N
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def window(F=192, shape='cos'):
    pivot = N - F
    idx = np.arange(N)
    A = np.sin(PI * idx / (2 * pivot))
    t = (idx[pivot:] - pivot) / F
    A[pivot:] = {'cos': np.cos(PI * t / 2),
                 'cos02': 0.2 + 0.8 * np.cos(PI * t / 2),
                 'hann': 0.5 * (1 + np.cos(PI * t)),
                 'blackman': 0.42 + 0.5 * np.cos(PI * t) + 0.08 * np.cos(2 * PI * t)}[shape]
    return A


def synthesis(A):
    return (1 - np.cos(2 * PI * np.arange(L) / L)) / 4 / A[N - L:]


def pou_error(A, S):
    w = (A[N - L:] * S).reshape(4, H).sum(0)
    return float(np.abs(w - 1).max())


def tone(f, amp=0.3, dur=4.0):
    return amp * np.sin(2 * PI * f * np.arange(int(dur * FS)) / FS)


def engine_regions(A, f, amp=0.3):
    """Regions the engine forms on a steady windowed tone: [(lo, hi, omega_hz)]."""
    M = np.abs(np.fft.rfft(tone(f, amp, dur=0.05)[:N] * A))
    pk = [b for b in range(1, N // 2) if M[b] >= M[b - 1] and M[b] > M[b + 1] and M[b] >= M.max() * 1e-4]
    regs = []
    for i, p in enumerate(pk):
        lo = 1 if i == 0 else (pk[i - 1] + p) // 2 + 1
        hi = N // 2 if i + 1 == len(pk) else (p + pk[i + 1]) // 2 + 1
        a, b, c = np.log(np.maximum(M[p - 1:p + 2], 1e-300))
        den = a - 2 * b + c
        fr = (p + np.clip(0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0, -0.5, 0.5)) * BIN
        if abs(fr - f) <= 2 * BIN:  # IF estimate of the tone's own leakage passes the gate
            fr = f
        regs.append((lo, hi, round(float(fr), 2)))
    return regs


def model(x, u, A, S, regions, dc=True, ideal_hz=None, amp=0.3):
    xp = np.concatenate([np.zeros(N), x])
    y = np.zeros(len(xp))
    q = np.arange(L)
    for m in range((len(xp) - N) // H):
        X = np.fft.rfft(xp[m * H:m * H + N] * A)
        n_abs = m * H + N - L + q
        out = np.zeros(L)
        if ideal_hz is not None:  # hypothesis (a): the windowed frame as a pure complex exponential
            w = 2 * PI * ideal_hz / FS
            out = S * np.real(amp * A[N - L:] * np.exp(1j * (w * n_abs - PI / 2)) * np.exp(1j * w * u * n_abs))
        else:
            for lo, hi, fr in regions:
                Z = np.zeros(N, complex)
                Z[lo:hi] = 2 * X[lo:hi]
                out += S * np.real(np.fft.ifft(Z)[N - L:] * np.exp(2j * PI * fr * u / FS * n_abs))
            if dc:
                out += S * X[0].real / N
        y[m * H + N - L:m * H + N] += out
    return y[N:]


def spectrum(y, t0=1.0, nfft=2 ** 17):
    seg = y[int(t0 * FS):int(t0 * FS) + nfft] * np.hanning(nfft)
    return np.fft.rfftfreq(nfft, 1 / FS), np.abs(np.fft.rfft(seg)) ** 2


def analyse(y, f_in, f_shift, kmax=3, half=5.0):
    freqs, Y = spectrum(y)
    band = lambda f: Y[(freqs >= f - half) & (freqs <= f + half)].sum()
    dB = lambda p: round(float(10 * np.log10(max(p, 1e-30))), 1)
    ref = band(f_shift)
    hop = {}
    mask = np.ones_like(Y, bool)
    for k in range(-kmax, kmax + 1):
        f = f_shift + k * FS / H
        if 0 < f < FS / 2:
            if k:
                hop[f'{k:+d}'] = dB(band(f) / ref)
            mask &= ~((freqs >= f - half) & (freqs <= f + half))
    res = {'hop_dB': hop, 'residual_dB': dB(Y[mask].sum() / ref),
           'ghost_dB': dB(band(f_in) / ref) if abs(f_in - f_shift) > 2 * half else None}
    Ym = np.where(mask, Y, 0)
    peaks = np.flatnonzero((Ym[1:-1] > Ym[:-2]) & (Ym[1:-1] > Ym[2:])) + 1
    peaks = peaks[np.argsort(Ym[peaks])[::-1]]
    top = []
    for p in peaks:
        if all(abs(freqs[p] - f) > 20 for f, _ in top):
            top.append((round(float(freqs[p]), 1), dB(Y[p] / ref)))
        if len(top) == 5:
            break
    res['top_residual_peaks'] = top
    res['max_nontone_dB'] = max(list(hop.values()) + [t[1] for t in top]) if hop or top else None
    return res


def predicted_lines(f, u, regions):
    """Slice mechanism: each region re-emits its slice of the tone skirt at f*(1)+omega_r*u - k*FS/H."""
    out = {}
    for lo, hi, fr in regions:
        car = f + fr * u
        out[f'{fr}'] = sorted(set(round(abs(car - k * FS / H), 1) for k in range(0, 4) if abs(car - k * FS / H) < FS / 2))
    return out


def render(x, semis, exe, scratch, tag):
    inp, out = os.path.join(scratch, tag + '.f64'), os.path.join(scratch, tag + '.out.f64')
    x.astype('<f8').tofile(inp)
    subprocess.run([exe, inp, out, str(FS), f'{semis:g}', '32'], check=True, stdout=subprocess.DEVNULL)
    return np.fromfile(out, '<f8')[D:D + len(x)]


def q1(exe, scratch):
    A = window(); S = synthesis(A)
    cases = [(1000, s) for s in (7, 12, -2, -7, 0.0001, 0)] + [(3000, 7), (300, 7)]
    out = {}
    for f, s in cases:
        u = 2 ** (s / 12) - 1; fsh = f * (1 + u)
        x = tone(f)
        regs = engine_regions(A, f)
        meas = analyse(render(x, s, exe, scratch, f'q1_{f}_{s:g}'), f, fsh)
        mod = analyse(model(x, u, A, S, regs), f, fsh)
        one = analyse(model(x, u, A, S, [(1, N // 2, f)]), f, fsh)
        one_nodc = analyse(model(x, u, A, S, [(1, N // 2, f)], dc=False), f, fsh)
        ideal = model(x, u, A, S, regs, ideal_hz=f)
        ideal_err = float(f"{np.abs(ideal[FS:3 * FS] - tone(fsh)[FS:3 * FS]).max():.2g}")
        pred = predicted_lines(f, u, regs)
        allpos = [p for v in pred.values() for p in v]
        out[f'{f}Hz_{s:g}'] = {
            'f_shift': round(fsh, 2), 'delta_hz': round(f * u, 2), 'engine_regions': regs,
            'render': meas, 'model_engine_regions': mod, 'model_one_region': one,
            'model_one_region_no_dc': one_nodc, 'model_ideal_exp_max_err': ideal_err,
            'predicted_slice_lines': pred,
            'render_peaks_on_predicted': sum(any(abs(p - q) <= 2 for q in allpos) for p, _ in meas['top_residual_peaks'])}
        print(f, s, regs, '\n  render', meas['hop_dB'], meas['residual_dB'], meas['top_residual_peaks'][:4],
              '\n  model ', mod['hop_dB'], mod['residual_dB'], mod['top_residual_peaks'][:4],
              '\n  1reg', one['hop_dB'], one['residual_dB'], '| nodc', one_nodc['residual_dB'], '| ideal', ideal_err)
    return out


def q2():
    rows = []
    hann4 = (1 - np.cos(2 * PI * np.arange(L) / L)) / 4
    pad = 16
    x1k, x300 = tone(1000, dur=2.5), tone(300, dur=2.5)
    for shape in ('cos', 'cos02', 'hann', 'blackman'):
        for F in (192, 256, 320, 384):
            A = window(F, shape); S = synthesis(A)
            W = np.abs(np.fft.rfft(A, pad * N)); W /= W[0]
            side = {str(b): round(float(20 * np.log10(W[int(b * pad)])), 1) for b in (1.75, 2, 3.5, 7, 10)}
            w3 = 2 * int(np.argmax(W < 10 ** (-3 / 20))) / pad
            tail = slice(L - 48, L)
            age = float(((N - 1 - np.arange(N - L, N)) * A[N - L:] ** 2).sum() / (A[N - L:] ** 2).sum() / FS * 1e3)
            r1k, r300 = engine_regions(A, 1000), engine_regions(A, 300)
            rows.append({'shape': shape, 'F': F, 'sidelobe_dB': side, 'mainlobe_3dB_bins': w3,
                         'A_support_start': round(float(A[N - L]), 4), 'A_end': float(f'{A[-1]:.3g}'),
                         'invA_max': round(float(1 / A[-1]), 1),
                         'S_end_re_max_dB': round(float(20 * np.log10(S[-1] / S.max())), 1),
                         'S_max': round(float(S.max()), 3),
                         'tail48_gain_dB': round(float(10 * np.log10((S[tail] ** 2).sum() / (hann4[tail] ** 2).sum())), 1),
                         'pou_err': float(f'{pou_error(A, S):.1g}'), 'mean_age_last_L_ms': round(age, 2),
                         'regions_1k': len(r1k), 'regions_300': len(r300),
                         'ripple_1bin_1k_dB': analyse(model(x1k, BIN / 1000, A, S, r1k), 1000, 1000 + BIN)['max_nontone_dB'],
                         'ripple_1bin_300_dB': analyse(model(x300, BIN / 300, A, S, r300), 300, 300 + BIN)['max_nontone_dB']})
            print(rows[-1])
    return rows


def chord(dur=4.0):
    tn = np.arange(FS) / FS
    env = np.minimum(tn / 0.001, 1) * np.exp(-np.log(1000) * tn / 0.5)
    note = sum(env * np.sin(2 * PI * f0 * h * tn) / h for f0 in (82.407, 123.47, 164.81, 207.65) for h in range(1, 11))
    note *= 0.3 / np.abs(note).max()
    return np.tile(note, int(dur))


def onset_metrics(x, y):
    env = lambda s: np.sqrt(np.convolve(s * s, np.ones(240) / 240)[:len(s)])  # causal 5 ms RMS
    ex, ey = env(x), env(y)

    def cross(e, o):
        seg = e[o:o + int(0.1 * FS)]; th = 0.5 * seg.max(); i = int(np.argmax(seg >= th))
        return (i - 1 + (th - seg[i - 1]) / (seg[i] - seg[i - 1])) / FS * 1e3

    def t90(s, o):
        c = np.cumsum(s[o:o + int(0.06 * FS)] ** 2)
        return float(np.searchsorted(c, 0.9 * c[-1]) / FS * 1e3)

    per = [{'lag50_ms': round(cross(ey, o) - cross(ex, o), 3), 't90_in_ms': round(t90(x, o), 2),
            't90_out_ms': round(t90(y, o), 2),
            'e5ms_dB': round(float(10 * np.log10((y[o:o + 240] ** 2).sum() / (x[o:o + 240] ** 2).sum())), 2),
            'peak_ratio_dB': round(float(20 * np.log10(ey[o:o + 4800].max() / ex[o:o + 4800].max())), 2)}
           for o in range(0, len(x), FS)]
    mean = lambda k: round(float(np.mean([p[k] for p in per])), 3)
    return {'per_onset': per, 'mean_lag50_ms': mean('lag50_ms'),
            'mean_t90_delta_ms': round(mean('t90_out_ms') - mean('t90_in_ms'), 3), 'mean_e5ms_dB': mean('e5ms_dB')}


def q3(exe, scratch):
    x = chord()
    out = {}
    for s in (0, 0.0001, 7):
        y = render(x, s, exe, scratch, f'q3_{s:g}')
        out[f'{s:g}'] = onset_metrics(x, y)
        if s == 0:
            out['0']['max_abs_diff_vs_input'] = float(f"{np.abs(y - x).max():.2g}")
        print(s, {k: v for k, v in out[f'{s:g}'].items() if k != 'per_onset'})
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--render', default='/tmp/pitchwing-build-wt/pitchwing_live_render')
    ap.add_argument('--out', default=os.path.join(ROOT, 'docs/results/2026-10-10-window-study.json'))
    ap.add_argument('--scratch', default='/tmp/pitchwing-window')
    ap.add_argument('--only', default='q1,q2,q3')
    a = ap.parse_args()
    os.makedirs(a.scratch, exist_ok=True)
    A0 = window(); assert pou_error(A0, synthesis(A0)) < 1e-12
    res = {'config': {'fs': FS, 'H': H, 'L': L, 'N': N, 'D': D, 'fft': 2 ** 17, 'band_hz': 5}}
    only = a.only.split(',')
    if 'q1' in only: res['q1'] = q1(a.render, a.scratch)
    if 'q2' in only: res['q2'] = q2()
    if 'q3' in only: res['q3'] = q3(a.render, a.scratch)
    with open(a.out, 'w') as fh:
        json.dump(res, fh, separators=(',', ':'))
    print('wrote', a.out)
