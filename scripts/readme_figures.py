"""Generate the README figures from a real engine render.

Inputs
  stems/chord.wav      local gitignored clean guitar DI (mono PCM24, 44.1 kHz)
  excerpt              14.0-17.0 s of that file (a sustained low chord)
  shift                +7 semitones, block 32, 44.1 kHz (the stem's rate)
  binary               /tmp/pitchwing-build/pitchwing_live_render
                       (override with argv[1]); build it with
                       cmake -S . -B /tmp/pitchwing-build -DCMAKE_BUILD_TYPE=Release
Outputs (150 dpi PNG, light theme): docs/figures/waveform.png, spectrum.png,
spectrogram.png. Intermediates go to /tmp/pitchwing-figures.
Run from the repo root:
  OPENBLAS_NUM_THREADS=1 /tmp/pitchwing-env/bin/python -B scripts/readme_figures.py
"""
import subprocess
import sys
import wave
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STEM, START, DUR, SEMIS = ROOT / "stems" / "chord.wav", 14.0, 3.0, 7
RENDER = sys.argv[1] if len(sys.argv) > 1 else "/tmp/pitchwing-build/pitchwing_live_render"
SCRATCH, OUT = Path("/tmp/pitchwing-figures"), ROOT / "docs" / "figures"
LATENCY = 439  # LiveEngine latencySamples() at 44.1 kHz
ZOOM_AT, ZOOM_MS = 2.2, 20.0  # zoom/spectrum frame start (s into the excerpt; steady sustain) and zoom length
DPI, COLORS = 150, ("#4a6fa5", "#d1762b")


def read_excerpt():
    with wave.open(str(STEM), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth()) == (1, 3), w.getparams()
        fs = w.getframerate()
        w.setpos(round(START * fs))
        raw = np.frombuffer(w.readframes(round(DUR * fs)), dtype=np.uint8).reshape(-1, 3)
    pcm = (raw[:, 0].astype(np.int32) | raw[:, 1].astype(np.int32) << 8
           | raw[:, 2].astype(np.int8).astype(np.int32) << 16)
    return fs, pcm / 2 ** 23


def render(x, fs):
    SCRATCH.mkdir(exist_ok=True)
    src, dst = SCRATCH / "in.f64", SCRATCH / "out.f64"
    x.astype("<f8").tofile(src)
    subprocess.run([RENDER, str(src), str(dst), str(fs), str(SEMIS), "32"], check=True,
                   capture_output=True)
    y = np.fromfile(dst)[LATENCY:LATENCY + len(x)]
    assert len(y) == len(x) and np.all(np.isfinite(y)) and np.abs(y).max() < 1.25
    return y


def waveform(x, y, fs):
    t = np.arange(len(x)) / fs
    fig, (a, b) = plt.subplots(2, 1, figsize=(8, 4.2), constrained_layout=True)
    m = fs // 100  # whole-excerpt view as 10 ms min/max envelopes (keeps the PNG small)
    for v, c, lab in ((x, COLORS[0], "input"), (y, COLORS[1], f"shifted +{SEMIS} st")):
        e = v[: len(v) // m * m].reshape(-1, m)
        a.fill_between(t[::m][: len(e)], e.min(1), e.max(1), color=c, alpha=0.6, lw=0, label=lab)
    a.set(xlim=(0, DUR), xlabel="time (s)", title="Whole excerpt, latency removed"); a.legend(loc="upper right")
    s = slice(int(ZOOM_AT * fs), int((ZOOM_AT + ZOOM_MS / 1000) * fs))
    b.plot(t[s] * 1000, x[s], COLORS[0], lw=1); b.plot(t[s] * 1000, y[s], COLORS[1], lw=1, alpha=0.8)
    b.set(xlabel="time (ms)", title=f"{ZOOM_MS:.0f} ms zoom at {ZOOM_AT:.1f} s")
    fig.savefig(OUT / "waveform.png", dpi=DPI); plt.close(fig)


def spectrum(x, y, fs, n=8192):
    s = slice(int(ZOOM_AT * fs), int(ZOOM_AT * fs) + n)
    win, f = np.hanning(n), np.fft.rfftfreq(n, 1 / fs)
    db = lambda v: 20 * np.log10(np.abs(np.fft.rfft(v[s] * win)) / win.sum() * 2 + 1e-12)
    fig, a = plt.subplots(figsize=(8, 3.6), constrained_layout=True)
    a.semilogx(f, db(x), COLORS[0], lw=0.8, label="input"); a.semilogx(f, db(y), COLORS[1], lw=0.8, alpha=0.8, label=f"shifted +{SEMIS} st")
    a.set(xlim=(40, 8000), ylim=(-100, -20), xlabel="frequency (Hz, log)", ylabel="dBFS",
          title=f"One {n / fs * 1000:.0f} ms frame at {ZOOM_AT:.1f} s: harmonics move by the ratio {2 ** (SEMIS / 12):.3f}")
    a.grid(alpha=0.3, which="both"); a.legend(loc="upper right")
    fig.savefig(OUT / "spectrum.png", dpi=DPI); plt.close(fig)


def spectrogram(x, y, fs):
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.4), sharey=True, constrained_layout=True)
    for a, v, name in zip(axes, (x, y), ("input", f"shifted +{SEMIS} st")):
        a.specgram(v, NFFT=4096, Fs=fs, noverlap=3072, cmap="magma", vmin=-110, vmax=-10)
        a.set(yscale="log", ylim=(40, 8000), xlabel="time (s)", title=name)
    axes[0].set_ylabel("frequency (Hz, log)")
    fig.savefig(OUT / "spectrogram.png", dpi=DPI); plt.close(fig)


if __name__ == "__main__":
    fs, x = read_excerpt()
    y = render(x, fs)
    OUT.mkdir(exist_ok=True)
    plt.rcParams.update({"font.size": 8, "axes.titlesize": 9})
    waveform(x, y, fs); spectrum(x, y, fs); spectrogram(x, y, fs)
    for p in sorted(OUT.glob("*.png")):
        size = p.stat().st_size
        assert size <= 200_000, (p, size)
        print(p.relative_to(ROOT), size)
