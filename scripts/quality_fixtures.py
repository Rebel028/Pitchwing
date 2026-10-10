#!/usr/bin/env python3
"""Render synthetic fixtures through pitchwing_live_render and measure the artifact
mechanisms predicted in docs/quality/2026-10-10-code-caveats.md (sections 1-3, 5-7).

usage: quality_fixtures.py [--render /tmp/pitchwing-build/pitchwing_live_render]
                           [--out docs/results/2026-10-10-fixtures.json]
                           [--scratch /tmp/pitchwing-fixtures] [--only unity,sidebands,...]

All fixtures are mono float64 at 48 kHz, block 32; the output is aligned to the
input by the engine latency D = L-1+H. NumPy only (no SciPy).
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from artifact_scan import envelope, highpass, scan  # noqa: E402

FS = 48000
H = int(FS * 0.002)
L = 4 * H
D = L - 1 + H
RENDER = "/tmp/pitchwing-build/pitchwing_live_render"
SCRATCH = "/tmp/pitchwing-fixtures"
RNG = np.random.default_rng(0)


def r(x, d=2):
    return round(float(x), d)


def db(p, ref=1.0):
    return r(10 * np.log10(p / ref + 1e-30), 1)


def ratio(semis):
    return 2 ** (semis / 12)


def t_axis(dur):
    return np.arange(int(dur * FS)) / FS


def tones(freqs, amps, dur, phases=None):
    t = t_axis(dur)
    phases = np.zeros(len(freqs)) if phases is None else phases
    return sum(a * np.sin(2 * np.pi * f * t + p) for f, a, p in zip(freqs, amps, phases))


def render(name, x, semis, control=None):
    """Run the native renderer; return output aligned to x (same length)."""
    src, dst = f"{SCRATCH}/{name}.f64", f"{SCRATCH}/{name}_out.f64"
    x.astype("<f8").tofile(src)
    cmd = [RENDER, src, dst, str(FS), str(semis), "32"]
    if control is not None:
        control.astype("<f8").tofile(f"{SCRATCH}/{name}_ctl.f64")
        cmd.append(f"{SCRATCH}/{name}_ctl.f64")
    subprocess.run(cmd, check=True, capture_output=True)
    y = np.fromfile(dst)
    return y[D:D + len(x)]


def bandpass(x, lo, hi):
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / FS)
    spec[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(spec, len(x))


def analytic(x):
    spec = np.fft.fft(x)
    spec[len(x) // 2 + 1:] = 0
    spec[1:len(x) // 2] *= 2
    return np.fft.ifft(spec)


def spectrum(x, nfft):
    """Hann-windowed power spectrum normalised so a full-scale sine gives 1.0."""
    w = np.hanning(len(x))
    spec = np.fft.rfft(x * w, nfft)
    return np.fft.rfftfreq(nfft, 1 / FS), (2 * np.abs(spec) / w.sum()) ** 2


def band_power(f, p, centre, half):
    return p[(f >= centre - half) & (f <= centre + half)].sum()


def seg(x, a, b):
    return x[int(a * FS):int(b * FS)]


def count_runs(mask):
    return int(np.sum(np.diff(mask.astype(int)) == 1))


# ---------------------------------------------------------------- fixture 1
def unity(out):
    """Caveat 5: nonunity -> exact unity resets rotations; expect a dip around T+D."""
    def dip_metrics(y, T, bands):
        res = {}
        for label, (lo, hi, period) in bands.items():
            env = envelope(bandpass(y, lo, hi), period)
            ref = env[int((T - 0.05) * FS):int(T * FS)].min()
            win = env[int(T * FS):int((T + 0.04) * FS)]
            res[label] = r(20 * np.log10(win.min() / ref), 1)
        return res

    x = tones([220, 1000], [0.25, 0.25], 2.0)
    bands = {"total_1ms": (0, FS / 2, 48), "p220": (100, 600, 218), "p1000": (600, 1500, 48)}
    rows = {}
    for i in range(10):
        T = 1.0 + 0.013 * i
        ctl = np.where(t_axis(2.0) < T, 3.0, 0.0)
        rows[f"T={T:.3f}"] = dip_metrics(render(f"unity_{i}", x, 3, ctl), T, bands)
    worst = {k: min(v[k] for v in rows.values()) for k in bands}
    ctl = np.where(t_axis(2.0) < 1.0, 0.0, 3.0)
    reverse = dip_metrics(render("unity_rev", x, 0, ctl), 1.0, bands)
    steady = dip_metrics(render("unity_steady", x, 3), 1.0, bands)
    out["unity_transition"] = {"pass_threshold_db": -1.0, "worst_dip_db": worst, "per_T": rows,
                               "reverse_0_to_3_db": reverse, "steady_plus3_control_db": steady}


# ---------------------------------------------------------------- fixture 2
def sidebands(out):
    """Caveat 3: brick-wall partition ringing -> lines at f_shift +- k*fs/H."""
    res = {}
    for pair in ([1000, 1082], [1000, 1703]):
        x = tones(pair, [0.25, 0.25], 4.0)
        for semis in (12, -2):
            y = seg(render(f"side_{pair[1]}_{semis}", x, semis), 1, 3)
            f, p = spectrum(y, 2 ** 17)
            lines, worst_sb, line_p = [], -200.0, 0.0
            for f0 in pair:
                expect = ratio(semis) * f0
                m = (f > expect - 30) & (f < expect + 30)
                fl = f[m][p[m].argmax()]
                lp = band_power(f, p, fl, 5)
                line_p += lp
                sb = max(band_power(f, p, fl + s * k * FS / H, 5) for k in (1, 2, 3) for s in (-1, 1))
                worst_sb = max(worst_sb, 10 * np.log10(sb / lp + 1e-30))
                lines.append({"expected_hz": r(expect, 1), "found_hz": r(fl, 1)})
            resid = p[(f > 20)].sum() - line_p
            pm = p.copy()
            for fl in (ln["found_hz"] for ln in lines):
                pm[(f > fl - 5) & (f < fl + 5)] = 0
            top = [i for i in np.argsort(pm)[::-1][:60] if 20 < f[i]]
            peaks = []
            for i in top:  # strongest residual peaks, 3 Hz apart
                if all(abs(f[i] - f[j]) > 3 for j in peaks):
                    peaks.append(i)
            res[f"{pair[0]}+{pair[1]}_{semis:+d}"] = {
                "lines": lines, "worst_hop_sideband_db": r(worst_sb, 1),
                "nonline_residual_db": db(resid, line_p),
                "beat_hz": r((pair[1] - pair[0]) * (ratio(semis) - 1), 1),
                "top_residual_peaks_hz_db": [[r(f[i], 1), db(band_power(f, p, f[i], 1), line_p)] for i in peaks[:3]]}
    out["hop_sidebands"] = {"pass_threshold_db": -50.0, "cases": res}


# ---------------------------------------------------------------- fixture 3
def chord(dur=8.0, tau=3.0):
    notes = [82.41, 110.0, 146.83, 196.0, 246.94]
    freqs = [n * h for n in notes for h in range(1, 13)]
    amps = [1 / h for _ in notes for h in range(1, 13)]
    x = tones(freqs, amps, dur, RNG.uniform(0, 2 * np.pi, len(freqs)))
    x *= np.exp(-t_axis(dur) / tau)
    return 0.4 * x / np.abs(x).max()


def crackle_metrics(y):
    env = envelope(bandpass(y, 1500, 6000), 48)
    n = int(0.05 * FS)
    blocks = env[:len(env) // n * n].reshape(-1, n)
    med = np.repeat(np.median(blocks, axis=1), n)  # shortcut: block median, not sliding
    exceed = env[:len(med)] > 4 * med
    frames = seg(y, 3, 8).reshape(-1, 480) * np.hanning(480)
    mag = np.abs(np.fft.rfft(frames, axis=1))
    return {"exceed_samples_3_8s": int(exceed[3 * FS:8 * FS].sum()),
            "exceed_events_3_8s": count_runs(exceed[3 * FS:8 * FS]),
            "flux_3_8s": r(np.abs(np.diff(mag, axis=0)).sum(), 3)}


def churn(out):
    """Caveat 2: noise-driven region churn; (ii) noisy input vs (iii) noise on clean output."""
    x = chord()
    white = RNG.standard_normal(len(x))
    res = {}
    for semis, level in ((5, -60), (-7, -60), (5, -40)):  # -40 dBFS is a sensitivity check
        noise = white * 10 ** (level / 20)
        clean = render(f"churn_clean_{semis}", x, semis)
        noisy = render(f"churn_noisy_{semis}_{level}", x + noise, semis)
        ii, iii = crackle_metrics(noisy), crackle_metrics(clean + noise)
        res[f"{semis:+d}_noise{level}dBFS"] = {
            "clean": crackle_metrics(clean), "noisy_input": ii, "noise_on_output": iii,
            "flux_ratio_ii_over_iii": r(ii["flux_3_8s"] / iii["flux_3_8s"], 3),
            "dry_input": crackle_metrics(x + noise)}
    out["churn_crackle"] = {"pass_flux_ratio_within": 0.2, "cases": res}


# ---------------------------------------------------------------- fixture 4
def if_pp_cents(y, lo, hi):
    z = analytic(bandpass(y, lo, hi))
    inst = np.diff(np.unwrap(np.angle(z))) * FS / (2 * np.pi)
    inst = seg(inst, 1, 5)
    n, hop = int(0.02 * FS), int(0.005 * FS)
    med = np.array([np.median(inst[i:i + n]) for i in range(0, len(inst) - n, hop)])
    med = med[med > 0]
    return r(1200 * np.log2(med.max() / med.min()), 1)


def warble(out):
    """Caveat 1: E2+G#2 merged into one region -> rigid translation and beat-rate FM."""
    x = tones([82.41, 103.83], [0.25, 0.25], 6.0)
    res = {"dry_if_pp_cents": if_pp_cents(x, 30, 200)}
    for semis in (-7, 7):
        y = render(f"warble_{semis}", x, semis)
        f, p = spectrum(seg(y, 1, 5), 2 ** 18)
        m = (f > 30) & (f < 300)
        fb, pb = f[m], p[m]
        peaks = [i for i in range(1, len(pb) - 1) if pb[i] > pb[i - 1] and pb[i] >= pb[i + 1]]
        top = sorted(peaks, key=lambda i: -pb[i])[:2]
        f1, f2 = sorted(fb[i] for i in top)
        amps = [np.sqrt(band_power(f, p, fl, 1.0)) for fl in (f1, f2)]
        line_p = sum(a * a for a in amps)
        outer = sum(band_power(f, p, fl, 1.0) for fl in (2 * f1 - f2, 2 * f2 - f1))
        res[f"{semis:+d}"] = {
            "if_pp_cents": if_pp_cents(y, 30, 200),
            "static_two_tone_same_amps_if_pp_cents": if_pp_cents(tones([f1, f2], amps, 6.0), 30, 200),
            "outer_beat_sidebands_re_lines_db": db(outer, line_p),
            "lines_hz": [r(f1, 2), r(f2, 2)],
            "expected_hz": [r(ratio(semis) * 82.41, 2), r(ratio(semis) * 103.83, 2)],
            "spacing_hz": r(f2 - f1, 2), "required_spacing_hz": r(ratio(semis) * 21.42, 2),
            "spacing_error_pct": r(100 * ((f2 - f1) / (ratio(semis) * 21.42) - 1), 1),
            "line_energy_fraction_30_300": r(line_p / pb.sum(), 3)}
    out["warble"] = {"pass": "p-p < 10 cents and spacing within 5 %", **res}


# ---------------------------------------------------------------- fixture 5
def dc_lowbin(out):
    """Caveats 6 and 7: DC term, unshifted low-bin ghost, sub-zero bin toggling."""
    res = {}
    x = 0.05 + tones([220], [0.3], 3.0)
    y = render("dc_offset", x, 7)
    f, p = spectrum(seg(y, 0.5, 2.9), 2 ** 17)
    res["dc_220_+7"] = {"hop_line_500hz_dbfs": db(band_power(f, p, FS / H, 5)),
                        "hop_line_1000hz_dbfs": db(band_power(f, p, 2 * FS / H, 5)),
                        "mean_dc_gain": r(seg(y, 0.5, 2.9).mean() / 0.05, 3),
                        "pass_hop_lines_dbfs": -80}
    x = tones([41.2], [0.5], 4.0)
    for semis in (-12, 12):
        y = render(f"e1_{semis}", x, semis)
        f, p = spectrum(seg(y, 1, 3), 2 ** 17)
        shifted = band_power(f, p, ratio(semis) * 41.2, 2)
        res[f"e1_{semis:+d}"] = {"ghost_41hz_re_shifted_db": db(band_power(f, p, 41.2, 2), shifted),
                                 "shifted_line_dbfs": db(shifted), "gain_db": db(shifted, 0.5 ** 2),
                                 "pass_ghost_db": -40}
    t = t_axis(6.0)
    fm = 82.41 * 2 ** (15 / 1200 * np.sin(2 * np.pi * 0.5 * t))
    x = 0.4 * np.sin(2 * np.pi * np.cumsum(fm) / FS)
    y = render("e2_vibrato", x, -12)
    env = np.abs(analytic(bandpass(y, 25, 60)))
    step_db = 20 * np.log10(env[48:] / env[:-48])
    steps = seg(np.abs(step_db) > 3, 1, 5)
    env_dry = np.abs(analytic(bandpass(x, 60, 110)))
    rel_step = lambda z: max(row["max_rel_step"] for row in scan(seg(z, 1, 5), FS)[0])
    res["e2_vibrato_-12"] = {"steps_gt3db_events_1_5s": count_runs(steps),
                             "max_rel_step_wet": r(rel_step(y), 3), "max_rel_step_dry": r(rel_step(x), 3),
                             "max_1ms_step_db": r(np.abs(seg(step_db, 1, 5)).max(), 2),
                             "dry_max_1ms_step_db": r(np.abs(20 * np.log10(seg(env_dry[48:] / env_dry[:-48], 1, 5))).max(), 2),
                             "gain_db": r(20 * np.log10(seg(env, 1, 5).mean() / seg(env_dry, 1, 5).mean()), 2)}
    out["dc_lowbin"] = res


# ---------------------------------------------------------------- fixture 6
def hf_junk(out):
    """+12 HF check: wet/dry >2 kHz energy per second and energy above 2x highest harmonic."""
    x = chord()
    y = render("hf_chord_12", x, 12)
    xh, yh = highpass(x, FS), highpass(y, FS)
    ratios = [float((yh[s:s + FS] ** 2).sum() / (xh[s:s + FS] ** 2).sum()) for s in range(FS, 6 * FS, FS)]
    top = 2 * 12 * 246.94
    f, p = spectrum(seg(y, 1, 6), 2 ** 18)
    out["hf_junk_+12"] = {"wet_over_dry_gt2k_per_second": [r(v, 2) for v in ratios],
                          "median": r(np.median(ratios), 2), "max": r(max(ratios), 2),
                          "real_di_reference_median": 21.8,
                          "above_2x_top_harmonic_hz": r(top, 0),
                          "energy_above_re_total_db": db(p[f > top].sum(), p.sum()),
                          "energy_above_dbfs": db(p[f > top].sum())}


def bend(out):
    """Multi-resolution risk: omega lag on an E2 bend of +2 st over 300 ms and back."""
    t = t_axis(3.0)
    semis = np.interp(t, [0, 1.0, 1.3, 2.0, 2.3, 3.0], [0, 0, 2, 2, 0, 0])
    f_in = 82.41 * 2 ** (semis / 12)
    phase = 2 * np.pi * np.cumsum(f_in) / FS
    x = 0.3 * np.sin(phase) + 0.15 * np.sin(2 * phase)
    res = {}
    for shift in (-7, 7):
        y = render(f"bend_{shift}", x, shift)
        want = ratio(shift) * f_in
        lo, hi = ratio(shift) * 70, ratio(shift) * 120  # fundamental only
        z = analytic(bandpass(y, lo, hi))
        inst = np.diff(np.unwrap(np.angle(z))) * FS / (2 * np.pi)
        n = int(0.01 * FS)  # 10 ms median against residual ripple
        idx = np.arange(int(0.5 * FS), int(2.8 * FS), n // 2)
        err = np.array([1200 * np.log2(np.median(inst[i:i + n]) / np.median(want[i:i + n])) for i in idx])
        tt = idx / FS
        windows = {"hold_0.5_1.0": (0.5, 1.0), "bend_up_1.0_1.5": (1.0, 1.5),
                   "hold_1.6_2.0": (1.6, 2.0), "bend_down_2.0_2.5": (2.0, 2.5)}
        res[f"{shift:+d}"] = {k: {"max_abs_cents": r(np.abs(err[(tt >= a) & (tt < b)]).max(), 1),
                                  "mean_cents": r(err[(tt >= a) & (tt < b)].mean(), 1)}
                              for k, (a, b) in windows.items()}
    out["bend"] = {"pass": "informational: compare builds", **res}


FIXTURES = {"unity": unity, "sidebands": sidebands, "churn": churn, "warble": warble,
            "dc": dc_lowbin, "hf": hf_junk, "bend": bend}


def main():
    global RENDER, SCRATCH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--render", default=RENDER)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "docs/results/2026-10-10-fixtures.json"))
    ap.add_argument("--scratch", default=SCRATCH)
    ap.add_argument("--only", default=",".join(FIXTURES))
    a = ap.parse_args()
    RENDER, SCRATCH = a.render, a.scratch
    os.makedirs(SCRATCH, exist_ok=True)
    out = {"rate": FS, "H": H, "L": L, "latency_D": D, "block": 32}
    for name in a.only.split(","):
        FIXTURES[name](out)
        print(name, json.dumps(out[list(out)[-1]])[:300], file=sys.stderr)
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
