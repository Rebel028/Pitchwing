# LiveEngine fixture results (2026-10-10)

Synthetic fixtures from [2026-10-10-code-caveats.md](2026-10-10-code-caveats.md)
rendered through `pitchwing_live_render` (48 kHz, block 32, $H=96$, $L=384$,
$D=479$) by `scripts/quality_fixtures.py`; numbers in
[docs/results/2026-10-10-fixtures.json](../results/2026-10-10-fixtures.json).
Whole run: 32 renders, ~40 s in WSL. Synthetic tones only, not real guitar.
dB are power ratios unless marked dBFS (full-scale sine = 0 dBFS).

## Verdicts

| Caveat | Mechanism | Verdict | Key number (pass threshold) |
|---|---|---|---|
| 5 | exact-unity transition resets rotation | confirmed | dips to -15 dB on 1 kHz, -5 dB on 220 Hz (< 1 dB) |
| 3 | partition ringing at hop rate | partly refuted | hop lines -41..-47 dB, independent of spacing (< -50); beat-rate sidebands -19 dB for 3.5-bin pair |
| 2 | region churn crackle from noise | refuted at tested levels | flux ratio (ii)/(iii) 0.96 / 0.96 / 0.87 (within 20 %), 0 extra transients |
| 1 | merged-region rigid translation + beat-rate FM | confirmed | spacing error +50 % / -33 % (< 5 %); IF p-p 205 / 160 cents (< 10) |
| 6 | DC term: hop ripple, wrong gain, ghost fundamental | confirmed | hop line -60.8 dBFS (< -80); DC gain 0.725; E1 ghost -17.9 dB (< -40) |
| 7 | sub-zero bin toggling clicks | refuted (gain loss confirmed) | 0 steps > 3 dB, rel. step 0.011 wet vs 0.021 dry; gain -0.91 dB |
| - | +12 HF junk baseline | reference | synthetic clean chord 4.5x median vs real DI 21.8x |

## 1. Unity transition (caveat 5)

Predicted: 6 ms phasey dip per partial of random depth when the control lands on
exactly 0 after a nonunity run. Measured (220 Hz + 1 kHz, +3 -> 0 at ten T values
1.000..1.117 s; envelope per partial over one period, min in $[T,\ T+40\ \mathrm{ms}]$ vs min
of the 50 ms before): worst dips -5.0 dB (220 Hz, $T=1.091$) and -15.0 dB
(1 kHz, $T=1.104$); 1 ms total-RMS dip up to -3.1 dB. Depth varies 0..-15 dB with
T as predicted (phase-dependent). Controls: steady +3 gives 0.0 dB; the reverse
0 -> +3 step gives no dip (-0.4 / -0.5 dB per partial, +1.9 dB overshoot).
Confirmed; fails the 1 dB threshold in 9 of 10 cases. No full null seen (10 T only).

## 2. Hop-rate sidebands (caveat 3)

Predicted: lines at $f_{\text{shift}} \pm k \cdot 500$ Hz, worse for neighbours < 10 bins apart.
Measured ($2^{17}$ Hann over 1-3 s, $\pm 5$ Hz bands, re the shifted line):

| pair | semis | worst hop sideband | non-line residual | strongest residual peaks (Hz, dB) |
|---|---|---|---|---|
| 1000+1082 (3.5 bins) | +12 | -46.6 dB | -17.2 dB | 2082 -18.6, 1918 -25.1, 2246 -27.2 |
| 1000+1082 | -2 | -44.7 dB | -17.1 dB | 973 -19.5, 882 -20.9 |
| 1000+1703 (30 bins) | +12 | -43.2 dB | -38.4 dB | 3203 -43.5 |
| 1000+1703 | -2 | -40.9 dB | -38.2 dB | 1391 -43.9 |

Hop-rate lines exist (-41..-47 dB, all four fail -50) but do not depend on
spacing, so they are not the predicted partition-ringing product; both tones
land within 0.1 Hz of $\text{ratio} \cdot f$ (two regions, no rigid translation at 3.5 bins).
The spacing-dependent artefact is at $f_{\text{line}} \pm \text{beat}$, $\text{beat} = (f_2-f_1)(r-1)$
(82 Hz at +12, 8.9 Hz at -2): -19 dB for the close pair, < -43 dB for the wide
pair. That is ~10 % amplitude modulation at the differential rate, the caveat's
secondary "tremolo at $|dw||r-1|$" prediction (9 Hz roughness at -2), 20 dB above
the hop lines. Verdict: hop-rate part refuted; beat-rate modulation confirmed.

## 3. Churn crackle (caveat 2)

Predicted: crackle in the decay tail when noise bins cross the 1e-4 peak floor;
(ii) noisy input flux > (iii) noise added after the clean render. Measured
(5-note chord, 1.5-6 kHz 1 ms RMS, exceedances > 4x the 50 ms block median,
spectral flux 10 ms frames over 3-8 s):

| case | noise | flux (ii)/(iii) | transient events ii / iii / clean |
|---|---|---|---|
| +5 | -60 dBFS | 0.961 | 1 / 1 / 1 |
| -7 | -60 dBFS | 0.955 | 0 / 0 / 1 |
| +5 | -40 dBFS | 0.872 | 0 / 0 / 1 |

No excess flux or transients from shifting the noise; the engine slightly
reduces noise flux (ratio < 1, likely the alias taper). Refuted at these
levels. Limitations: block (not sliding) median; the single event occurs in
clean and dry too (metric edge); the engine's flux attenuation could mask a
few-percent churn contribution. A per-frame region-count trace is the direct test.

## 4. Warble (caveat 1)

Predicted: E2+G#2 (0.9 bins apart) share a region; the pair is translated
rigidly (spacing kept at 21.4 Hz) and FM'd at the beat rate. Measured
($2^{18}$ Hann over 1-5 s; IF from the analytic signal of 30-200 Hz, 20 ms median):

| semis | lines found | expected | spacing (required) | IF p-p wet | static two-tone control | outer beat sidebands |
|---|---|---|---|---|---|---|
| -7 | 51.45, 72.88 Hz | 55.0, 69.3 | 21.42 (14.3) +50 % | 204.5 cents | 65.1 | -29.9 dB |
| +7 | 128.72, 150.15 Hz | 123.48, 155.57 | 21.42 (32.1) -33 % | 159.6 cents | 12.1 | -24.0 dB |

Spacing is exactly the input 21.42 Hz both ways (each tone 3.5-5 Hz off) and
the output has lines at $2f_1-f_2$ and $2f_2-f_1$ (-24..-30 dB) that the dry input
lacks. IF p-p of a beating pair is inflated by amplitude imbalance alone (static
two-tone with the measured amplitudes: 65 / 12 cents; dry 4 cents), but the wet
value is 3-13x larger. Confirmed on both criteria; spacing and outer sidebands
are the robust evidence, the IF number is indicative only.

## 5. DC and low bins (caveats 6, 7)

- (i) 0.05 DC + 220 Hz at 0.3, +7: hop line at 500 Hz -60.8 dBFS (predicted
  ~-33 dB re the -26 dBFS offset = -59 dBFS), 1000 Hz -73.5 dBFS; mean DC
  gain 0.725 (predicted $0.636 \times 1.10..1.15 = 0.70..0.73$). Confirmed, fails
  -80 dBFS.
- (ii) E1 41.2 Hz at 0.5, -12 / +12: unshifted ghost at 41.2 Hz is -17.9 /
  -17.8 dB re the shifted line (threshold -40). Confirmed. Shifted line at
  -4.3 dBFS, i.e. +1.7 dB gain (FINDINGS reported a loss at B0/E1; different
  geometry, not investigated).
- (iii) E2 with 0.5 Hz $\pm 15$ cent vibrato at -12: 0 envelope steps > 3 dB over
  1-5 s (25-60 Hz analytic envelope, max 0.01 dB per ms, same as dry); full-band
  relative sample step 0.011 wet vs 0.021 dry, so no -25 dB clicks either.
  Gain -0.91 dB, inside the predicted 0.5-1.4 dB loss. Clicks refuted for this
  case, gain loss confirmed. Limitation: $\pm 15$ cents may not sweep omega across
  an integer multiple; a wider sweep was not tried.

## 6. +12 HF junk reference

Clean synthetic 5-note chord at +12, 1-6 s, > 2 kHz wet/dry energy aligned by
D: per-second 4.39-4.68x, median 4.51x, versus the real-DI 21.8x median in
DEVELOPMENT.md. Energy above 2x the highest expected harmonic (5927 Hz):
-30.1 dB re total, -55.5 dBFS. Transposing 1-2 kHz harmonics above 2 kHz
explains the 4.5x; the real DI's extra ~5x is not explained by a clean
harmonic chord and remains a candidate artefact (noise/click translation).

## Not covered

Caveats 4, 8, 9, 10 were not rendered. Fixture 4 cannot separate merged-peak
omega wobble from partition AM; fixture 2 shows the latter exists even with
resolved regions, so both likely contribute on real chords.
