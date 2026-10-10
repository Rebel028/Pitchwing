# Window study: hop-rate lines, window-tail trade, onset lag (2026-10-10)

Script `experiments/quality/window_study.py`, data `docs/results/2026-10-10-window-study.json`.
Renders use `/tmp/pitchwing-build-wt/pitchwing_live_render` built 10:41 from the engine
BEFORE c1cf59b (image-aware region fit, bin-0 split), 48 kHz, block 32, H=96, L=384,
N=2048, D=479; Q1/Q3 should be rerun on the new build. Spectra: 2^17 Hann over 1-3.7 s,
+-5 Hz bands, levels re the shifted line. The NumPy model replays the frame pipeline with
exact omega: window A, FFT, engine peak picking (local maxima >= 1e-4 of the largest,
midpoint partition, parabola omega, IF accepted within 2 bins), per-region x2 IFFT, last
L samples times S*exp(j*omega_r*u*n), OLA at hop H, plus the unrotated DC term dc*S.

## Q1. Origin of the spacing-independent hop-rate lines

Single 1 kHz tone (0.3). The engine forms TWO regions on it: the windowed tone's
magnitude has a local maximum at bin 6 (-62 dB, tone skirt interfering with the
negative-frequency image), so bins 1-24 become a region with omega ~ 137-144 Hz (its IF
estimate, 1000 Hz, fails the 2-bin gate) and bins 25-1023 the real one. The partition
slices the tone's own skirt and each slice is re-emitted with its own translation.

| case | render hop -1 / -2 dB | render residual | render top peaks (Hz, dB) | model, engine regions: hop -1 / residual | model, 1 region: residual | ideal exp err |
|---|---|---|---|---|---|---|
| 1 kHz +7 | -51.7 / -70.1 | -51.5 | 571.7 -54.7, 71.4 -71.0 | -51.6 / -51.4 (568.0 -53.4, 68.1 -71.2) | -72.9 | 2.5e-12 |
| 1 kHz +12 | -51.7 / -69.8 | -51.5 | 643.4 -53.4, 143.6 -71.3 | -51.6 / -51.4 (636.5 -53.7, 136.6 -71.1) | -73.3 | 3e-12 |
| 1 kHz -2 | -51.7 / - | -51.5 | 484.5 -54.3, 15.7 -71.2, 109.1 -72.0 | -51.6 / -51.3 (485.2, 15.0, 109.1) | -72.9 | 1.4e-12 |
| 1 kHz -7 | -51.7 / - | -51.4 | 452.3 -53.4, 47.6 -70.0, 332.5 -72.1 | -51.6 / -51.3 (454.5, 45.4, 332.5) | -71.5 | 7.7e-13 |
| 1 kHz 0.0001 | -74.4 / -110.7 | -73.7 | 995.0 -81.3 (analysis skirt) | -74.1 / -73.7 | -73.7 | 1.4e-12 |
| 1 kHz 0 exact | -186 / - | -73.4 | none | identical | identical | 1.4e-12 |
| 3 kHz +7 | -115.8 / -113.4 | -78.9 | 1494.9 -87.9, 4500 -88.1 | -114.0 / -79.9 (1 region) | -79.9 | 5.1e-12 |
| 300 Hz +7 | +1 -72.8, +2 -68.3 | -48.6 | 50.5 -53.3, 349.4 -55.3 | +1 -82.7 / -48.2 (50.5 -53.3, 349.4 -53.7) | -48.2 | 7.7e-13 |

- The lines exist with a single tone (not a two-tone product); -51.7 dB at f_shift - 500
  Hz and -70 dB at f_shift - 1000 Hz for +12, +7, -2 and -7 alike, absent at exact unity,
  23 dB lower at u = 6e-6 (slices rotate by ~0 and still recombine). Only lower sidebands
  appear because each slice is a one-sided (positive-bin) signal: the comb at
  (f + omega_r*u) - k*500 Hz is weighted by the slice's spectrum, bins 1-24 (0-560 Hz).
  The second family (571.7/71.4 Hz at +7, 643.4/143.6 at +12, 452.3/47.6 at -7) is the
  same comb for the spurious region, (f + 143.6*u) - k*500 Hz. At 1 kHz, 2f is a multiple
  of 500 Hz, so fixture 2's lines sat on f_shift +- k*500 by coincidence. Both families
  are caveat-3 partition ringing (brick-wall slice re-emitted hop-periodically, tail
  amplified by S/A), triggered by the tone's own skirt rather than by a neighbour.
- The engine-region model reproduces every 1 kHz render to 0.1-0.5 dB; peak positions
  differ by the 7 Hz between the engine's spurious-region omega (143.6 Hz) and the
  model's parabola (136.6 Hz). The single-region model gives -73 dB at 1 kHz: the lines
  come from the partition, not the DC term (no-DC variant identical) or the Nyquist
  taper (3 kHz: -114 dB, one region).
- (a) POU error of the translated frame: refuted; a pure complex exponential through A,
  last L samples, exp(j*delta*n)*S, 4-frame OLA reproduces the shifted tone to 1e-12 for
  every delta. (d) omega jitter: refuted, the exact-omega model matches. (c): refuted.
  (b) DC/image skirt is a second, frequency-dependent instance of the same slice
  mechanism: at 300 Hz the single-region model already gives -48 dB (bin-0/1 brick wall
  slicing the image skirt, 2f = 25.6 bins at -59 dB); -73 dB at 1 kHz, -80 at 3 kHz.
  Scaling: with the skirt level at the slice boundary (300 Hz -48.6, 1 kHz -51.7, 3 kHz
  -116 since no spurious region forms above the 1e-4 floor), not with |r-1|.
  Unexplained: 300 Hz render lines at +2/+3 (-68 dB) that the model puts at -90 dB.

## Q2. Window-tail trade (NumPy, L=384, H=96, sin rise to the pivot kept)

Sidelobes |A| dB at 1.75/2/3.5/7/10 bins; ML = -3 dB full width (bins); S_end = S[L-1] re
max S; tail = sum S^2 over the last 48 samples re Hann/4 (dB); age = A^2-weighted mean age
of the last L samples (ms); regions = engine regions on a 1 kHz / 300 Hz tone; ripple =
largest non-tone model peak at delta = 1 bin, 1 kHz / 300 Hz. A*S is an exact POU for all
rows (max error 4e-16). Rows omitted here (cos 256, floor 384, Blackman 192, all 256/320 variants) are in the JSON.

| fall | F | 1.75 | 2 | 3.5 | 7 | 10 | ML | A_end | 1/A | S_end dB | tail dB | age | regions | ripple 1k / 300 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cos (current) | 192 | -15.8 | -17.7 | -24.5 | -32.9 | -41.1 | 1.13 | 0.0082 | 122 | -41.7 | 10.4 | 4.91 | 2 / 1 | -51.6 / -53.1 |
| cos | 320 | -16.3 | -18.0 | -27.1 | -40.7 | -45.8 | 1.25 | 0.0049 | 204 | -39.7 | 14.8 | 5.43 | 2 / 1 | -55.1 / -58.1 |
| cos (A=1 at support start) | 384 | -16.7 | -18.3 | -28.9 | -42.5 | -47.0 | 1.25 | 0.0041 | 245 | -39.5 | 16.4 | 5.61 | 2 / 1 | -54.6 / -58.2 |
| cos, floor 0.2 | 192 | -15.9 | -17.9 | -24.7 | -33.8 | -42.1 | 1.13 | 0.207 | 4.8 | -69.8 | 6.9 | 4.77 | 1 / 1 | -48.6 / -55.4 |
| Hann half | 192 | -15.6 | -17.3 | -24.3 | -32.0 | -39.9 | 1.25 | 6.7e-5 | 1.5e4 | 0.0 | 23.3 | 5.18 | 6 / 4 | -47.2 / -45.1 |
| Hann half | 384 | -16.4 | -17.4 | -27.4 | -52.7 | -53.0 | 1.25 | 1.7e-5 | 6.0e4 | 0.0 | 35.3 | 6.15 | 9 / 7 | -39.5 / -32.5 |
| Blackman half | 384 | -16.2 | -17.0 | -26.2 | -43.9 | -51.7 | 1.25 | 6.0e-6 | 1.7e5 | 0.0 | 43.9 | 6.46 | 10 / 5 | -25.8 / -37.2 |

- Near sidelobes (-16 dB at 1.75 bins, -18 at 2) are set by the whole asymmetric shape
  (long sin rise), not the fall; no candidate moves them by more than 1 dB. Only the
  3.5-10 bin skirt improves with F (cos: -24.5 -> -28.9 at 3.5, -33 -> -42.5 at 7).
- Hann and Blackman falls are unusable with the Hann/4 target: their second-order end
  zero makes S end at its maximum (S_end 0 dB, S_max up to 5.6, a rectangular synthesis
  termination) and their skirt ripple spawns 3-10 spurious regions. The fall needs a
  simple zero at the end (cos quarter-wave) or a floor.
- Ending A at 0.2 removes the spurious 1 kHz region, cuts 1/A to 4.8 and the tail gain by
  3.5-7 dB, but the edge step raises the far skirt so the bin-0 image slice grows: 1 kHz
  ripple worsens to -46..-49 dB. Not a win on its own.
- With longer F, 1/A at the last sample grows (122 -> 245) and so does the tail energy gain
  (10 -> 16 dB); S_end stays -40 dB. The spurious 1 kHz region persists for every cos F;
  ripple improves only 3.5 dB (-51.6 -> -55.1 at F = 320) via the lower boundary skirt.

Pareto: cos F=320 or 384 (F=384: A=1 at the support start, S = 2 sin^2 cos in closed
form, best 3.5-10 bin skirt, -55/-58 dB ripple) versus the current F=192 (shortest age
4.9 ms, lowest tail gain). Nothing on the table reaches -50 dB because the window is not
the lever: the lines are a region-formation problem (skirt maxima becoming regions,
brick-wall slices). Deciding fixtures: (1) fixture 2 and the Q1 tone on a build that
merges a peak whose IF equals an existing region's omega (the bin-6 peak's IF is exactly
1000 Hz) or uses soft region edges; (2) the Q3 chord on an F=320 build at +7.

## Q3. Onset lag: region path at u ~ 0 versus exact unity

1 ms-attack E2 chord (E2 B2 E3 G#3, 10 harmonics 1/h, RT60 0.5 s), every 1 s, 4 onsets.
Causal 5 ms RMS envelope, 50 % crossing re the input delayed by D; 90 %-energy time in
the first 60 ms; first-5 ms energy re input.

| semis | lag50 ms (per onset) | mean | t90 in -> out ms | e5ms dB | peak ratio dB |
|---|---|---|---|---|---|
| 0 (exact unity) | 0, 0, 0, 0 | 0.000 | 48.31 -> 48.31 | 0.0 | 0.0 |
| 0.0001 (region path) | 0, -0.03, -0.06, -0.08 | -0.043 | 48.31 -> 48.61 | -0.05 | +0.01 |
| +7 | 0.81, 0.31, 0.65, 1.14 | 0.726 | 48.31 -> 51.39 | -2.74 | -3.1 |

Verdict: the lag is NOT present on the region path at u ~ 0. Rendered through the window,
brick-wall partition, 1/A tail and OLA with ~zero rotation, the onset crosses 50 % within
0.08 ms of the input, keeps 99 % of its first-5 ms energy and its 90 % time within 0.3 ms.
At +7 the same chord loses 2.7 dB of first-5 ms energy, peaks 3 dB lower, crosses 50 %
0.3-1.1 ms late and reaches 90 % energy 3.1 ms later. The ~3.3 ms reported earlier is an
effect of the shift itself (region-dependent rotation/translation dispersing the transient
over the L-sample outputs of ~21 frames, caveat 8), not of the window or region bandpass;
a longer fall (Q2) is not contraindicated at u ~ 0, but its effect at nonzero shift is
unmeasured. Exact unity equals the input to 1e-16. Limitations: synthetic chord, four
onsets, one shift; 50 % crossing (0.7 ms) and 90 % time (3.1 ms) measure different
things, so the earlier 3.27 ms (20 ms RMS) is not directly comparable.
