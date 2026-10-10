# Multi-resolution low band: gauntlet and probe outcome (2026-10-10, session 3)

Reviewed: `2026-10-10-multires-plan.md` (long past-heavy low-band analysis whose
regions are transported, soft $\cos^2$ crossover). Reviewers: formalist, historian.

## Converged flaw (both reviewers)

The soft crossover over two separate region partitions is the rejected soft
region mask again: a partial inside the ~190 Hz ramp is rendered by a long and a
short region with different ω and rotation, giving the $|w+(1-w)e^{j\Delta\theta}|$ notch
or a ghost (formalist: E2's 412 Hz harmonic at −7 st keeps 0.15 of its energy in
the 330 Hz long region → −16 dB ghost 27 Hz away). Formalist's only valid
crossover: one partition in Hz, each region rendered from both spectra with one
ω/rotation, boundaries snapped to the short grid, $N_{\mathrm{low}} = k \cdot n$.

## Other formalist findings (would have applied to the transported design)

Rule not total (no long peak → hole, stale `lowestAmplitude`); peak flip-flop
across 350 Hz (same partial in both spectra, ω jumps by ~65 ms of lag); $A_{\mathrm{low}}$
cannot both equal $A$ on the support and be a plain sine rise (0.9868 vs 0.9993);
`lobeRange` must scale with N; partition of unity is only approximate on the
region path (leak through the ramp kernel); `maxRegions` ranks raw magnitudes
(long peaks win); $64 \times \mathrm{IFFT}(8192)$ worst case; history/tail/`fastSizeAbove`
bookkeeping.

## Historian findings

Gabor limit: separation needs ~$1/\Delta f$ of delay; a past-heavy window moves it into
the support edge (one-sided leaky separation, bloom, stale chords; Levine 1998,
Schörkhuber 2013). Recommended instead (Dressler 2006, Keiler & Marchand 2002,
Virtanen & Klapuri 2002, Every & Szymanski 2006): multi-resolution for
**estimation only** — long frame supplies $\omega_1, \omega_2$; the short frame fits only the
complex amplitudes of both lobes (linear, image-aware) and each fitted lobe is
transported with its own ω/rotation, residual with the merged ω. Reassignment
(weighted mean ω, beats) and time-domain low-band shifters (25–40 ms grains,
crossover comb) rejected. If the transported design were kept: $2N$ not $4N$.

## Probes (`experiments/quality/twolobe_probe.py`, `split_probe.py`)

- Short-frame amplitude fit with known ω over bins 0–8: condition number 1.8
  (E2+G#2, 0.9 bin), 1.5 (1.2 bin), 3.5–4 (0.45–0.6 bin); frame-to-frame
  amplitude p-p 0.03 dB exact ω, < 1 dB with 5–10 cent ω bias.
- ω from the short frame alone (2-D fit): 3.7 c p-p clean, 18 c with a 1 s
  decay, **134–143 c with harmonics** (every harmonic pair of a dyad is merged
  too) → ω must come from a resolving frame.
- Long frame, 3-bin single-lobe fit per long peak: $4N$ E2+G#2 14 c p-p (the
  neighbour 3.6 long bins away biases it); $2N$ fails (77–750 c). Full-band
  neighbour subtraction made it worse (26 c, skirt peaks unfiltered).
- Long frame with a **joint cluster fit** (peaks < 6 long bins apart,
  coordinate descent on each ω, amplitudes solved jointly over the cluster's
  bins, 3 sweeps): $4N$ E2+G#2 2.1/2.5 c p-p (means 0.3/0.0 c), E2+F#2 (1.7 long
  bins) 4.7/3.5 c, 1 s decay 3–7 c, −40 dB noise unchanged; short-frame
  amplitude split with those ω: 0.05–0.2 dB p-p.

## Decision

Implement the estimation-only split: $N_{\mathrm{long}} = 4 \cdot n$ analysis (ω only, never
transported), joint cluster fit of long peaks, and inside each short region
holding ≥ 2 long peaks a linear amplitude split into per-component lobes plus a
residual; components and residual are separate transport entries with their own
ω and inherited rotations. Single-note regions keep the short-frame ω, so bends
of resolved notes are untouched; the long-frame lag (~85 ms centroid) only
affects split components. Exact partition of unity is kept (parts + residual =
the region's bins). Risks to measure: model-order flip-flop when a long peak
appears/disappears, stale long ω after chord changes and on bends of dyads,
CPU of FFT(4n) per channel per hop.
