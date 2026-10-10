# LiveEngine artifact mechanisms (code audit, 2026-10-10)

Read-only audit of `src/LiveEngine.cpp` (line numbers from that file),
`experiments/transport/ENGINE_NOTES.md`, `FINDINGS.md`, `docs/live-engine.md`.
No build or audio run was made; severities are reasoning-based estimates to be
falsified by the fixtures below. Geometry at 48 kHz: H=96, L=384, N=2048,
bin = 23.44 Hz, hop rate fs/H = 500 Hz (501.1 Hz at 44.1 kHz, H=88).
Fixtures: mono, duplicated to both channels, <=10 s, trim D=L-1+H samples.

Known: `stems/chord.wav` clicks are in the source and are not amplified
(HF ratio 0.4-1.25x); a clean synthetic 5-note low chord at -12..+12 shows no
discontinuities. Nothing below is proven on real guitar yet.

## Ranked summary (impact on live low-register chords)

| # | Mechanism | Lines | Trigger | Symptom | Est. severity |
|---|---|---|---|---|---|
| 1 | Unresolved region: rigid translation + wobbling merged-peak omega | 283-308, 387 | any two partials < ~2 bins (47 Hz) apart: every low-chord fundamental set | beat-rate warble/FM, detune, preserved beat spacing | high, steady |
| 2 | Region-boundary churn gives boundary bins a different rotation each frame | 262-280, 385-386, 310-322 | peak births/deaths: noise above 1e-4 floor in decay tail, 64-cap re-ranking, beating merge/split, decaying harmonics | crackle/grit at skirt level (-15..-35 dB re partial) | med-high, decay tails |
| 3 | Brick-wall region partition ringing, amplified at the window tail (1/A up to 122x) | 108-123, 385, 419-421 | neighbours closer than ~10 bins with differing rotations (any ratio != 0) | hop-rate (500 Hz) buzz/roughness, tremolo at |dw||r-1| | medium, unverified |
| 4 | 64-region cap drops real partials, they ride a neighbour's delta | 272-280 | 6-string chords with >64 resolved partials, or noise/clicks pushing partials out | detuned/beating harmonics that churn with decay | medium |
| 5 | Nonunity -> exact-unity: rotations reset to 0 while overlapping frames carry theta | 310, 334-342, 363, 377-380 | pitch target lands on exactly 0 and holds >= L samples (wheel to centre, snap) | 6 ms phasey dip/notch per partial, depth by theta | medium, automation |
| 6 | DC bin: non-POU synthesis window, wrong gain, DC lobe translated as a tone | 361-368, 118-123 | DC offset in DI; fundamentals below ~bin 3 (bass, drop tunings) | hop-rate ripple, rumble, unshifted ghost fundamental | low (guitar) / med (bass, offset DI) |
| 7 | Sub-zero destination bins hard-dropped and toggling | 390-396 | downshift >= -7 on lowest region, omega wobble across integer multiple | -25 dB clicks on low E, gain loss | low-med |
| 8 | Onset lag / smear from past-heavy window and region-dependent phase | 108-117, 419-432 | every attack | soft/late attacks (3.27 ms measured), post-smear up to N | medium, known |
| 9 | IF-gate toggle jumps omega by up to 2 bins | 303-306 | beating or noisy partials, onsets | one-hop FM blip; overlap phase mismatch 0.5*dw*(r-1)*H | low-med |
| 10 | Alias taper uses frame-end ratio only | 348, 387-396 | downward target step with content above fs/(2*ratio) | brief alias chirp (< L); upward step: HF dip | low (guitar) |
| 11 | Stereo coherence gate 1e-6, prev-magnitude gate 1e-6 | 291, 300 | anti-phase stereo only / onsets | none for mono guitar | negligible |

## 1. Unresolved region translation and merged-peak wobble

- Code: parabola 283-288, IF estimate 289-308, `delta = omega*u` 387.
- Mechanism: one `omega` per region; all bins move by `omega*(r-1)`. Two tones
  in one region keep their original spacing (FINDINGS table). The merged
  peak's parabola position swings with beat phase (up to +-0.5 bin); the IF
  estimate of a beating pair swings further and is accepted whenever within
  2 bins of the parabola (304), so `omega` can jump up to ~2 bins (47 Hz)
  between frames. Phase stays continuous (trapezoid at 321) but `delta`
  changes, i.e. FM of the whole region at the beat rate.
- Trigger: any pair of partials < 2 bins apart. E2/G#2 fundamentals are
  0.9 bins apart, E2/A2 1.2 bins. Every low chord.
- Symptom: warble/wobble of the fundamental band at the beat rate; at -12
  a 2-bin omega swing is 23 Hz of delta on a ~41 Hz output. Plus steady
  detune of each tone by `(omega_tone-omega_region)*(r-1)`.
- Fixture: E2 (82.41 Hz) + G#2 (103.83 Hz), equal amplitude, 6 s, -7 and
  +7 semitones. Metric: bandpass output 30-200 Hz, Hilbert instantaneous
  frequency, median-filter 20 ms, report peak-to-peak deviation in cents over
  1-5 s; and spectral line spacing (2^18 FFT) vs required `ratio*21.4 Hz`.
  Pass: p-p < 10 cents and spacing within 5 % (expected to fail).
- Fixes: representation change (per-region two-sinusoid model, longer causal
  history for the low band only, or multi-resolution analysis below ~300 Hz).
  Cheap mitigation of the wobble only: slew `omega` per region
  (e.g. max 0.25 bin/frame) and tighten the IF gate for regions whose previous
  magnitude dropped (beat null). Cost: nil CPU/latency; risk: slower settling
  on real pitch changes (bends). Does not fix spacing.

## 2. Region-boundary churn (per-bin rotation discontinuity)

- Code: peak pick 262-268, 1e-4 floor 264, cap 272-280, midpoint bounds
  385-386, ancestor inheritance 310-322 (no distance gate).
- Mechanism: bins are assigned to regions by integer midpoints between
  peaks. When a peak appears or vanishes, bins between its neighbours switch
  region. Rotation is per region and each region's rotation integrates its
  own `omega*u`, so neighbouring rotations diverge over time. A bin that
  changes region gets a phase step of `theta_A - theta_B` (arbitrary after a
  few hundred ms) plus a different translation. Across the 4-frame
  overlap-add this is a partial cancellation / glitch of that bin's content,
  i.e. of the neighbour's lobe skirt, ~-15..-35 dB below the partial for
  harmonics 2-4 bins apart (E2 harmonics are 3.5 bins apart).
  Inheritance on birth uses nearest omega (311-320), so a new noise peak
  between harmonics h1,h2 inherits one of them and then free-runs with its
  own omega; when it dies the bins return with accumulated divergence.
- Triggers: (a) noise bins above `1e-4*largest` (-80 dB re strongest bin,
  relative, so decay tails qualify: with 60 dB time-domain SNR and 30 dB
  decay, noise bins sit ~-60 dB re peak); (b) more than 64 candidates, cap
  re-ranked every frame by magnitude (274-278); (c) beating pairs at ~2 bins
  alternately resolving/merging; (d) source clicks/steps (`stems/chord.wav`)
  adding a broadband floor that interferes with harmonic skirts, creating
  spurious maxima for ~N/H = 21 frames.
- Symptom: crackle/grit riding the decay, worse on dense chords and larger
  |r-1|. Not a click at full level.
- Fixture: synthetic 5-note low chord (E2 A2 D3 G3 B3, 12 harmonics each,
  1/h amplitude, tau 3 s), 8 s, +5 and -7, rendered (i) clean, (ii) with
  white noise at -60 dBFS, (iii) with the noise added only to the output of
  (i) as control. Metric: 1 ms RMS in 1.5-6 kHz band; count samples where it
  exceeds 4x the surrounding 50 ms median, and spectral flux
  (sum |dX| over 10 ms frames) over 3-8 s; compare (ii) vs (iii).
  Pass: (ii) flux/transient count within 20 % of (iii).
- Fixes: (F2) overlapping raised-cosine region weights (1-2 bin crossfade,
  weights sum to 1) instead of brick-wall assignment: boundary bins carry
  both rotations, no hard step; also shrinks mechanism 3. Cost: ~2 extra bin
  multiplies per boundary, 0 latency; risk: none obvious. (F1) peak
  hysteresis: enter at 1e-4, leave at 1e-5, keep a dying peak 2 frames;
  magnitude-rank cap with hysteresis. Cost nil; risk: stale boundaries for a
  few frames. (F3) per-bin accumulated phase (true phase-vocoder state) is
  the full fix but abandons the exact per-region translation; moderate CPU.

## 3. Partition ringing amplified by the asymmetric window tail

- Code: window 108-117 (A falls from 1 at `pivot=N-L/2` to 0.0082 at N-1),
  synthesis `Hann/4/A` 118-123, brick-wall region 419-421, output takes the
  last L samples 425.
- Mechanism: a region is a rectangular band; its IFFT is the windowed partial
  low-passed to the band half-width b. The window's right edge (192-sample
  cosine quarter) needs ~10 bins to be represented, so for b < 10 bins the
  per-region time signal rings/overshoots at n -> N-1. Summed over regions
  with equal rotation the ringing cancels (partition sums to the full
  spectrum); with differing rotations it does not, and S = Hann/(4A)
  amplifies the tail samples by 1/A (2.6x at q'=48, 15x at q'=8, 122x at
  q'=1 relative to a symmetric WOLA). Residual is hop-periodic, modulated at
  |dw||r-1| between neighbours. Consistent with the measured 3-4 % (-14 dB)
  non-line energy for isolated B0/E1 in FINDINGS.
- Trigger: neighbours closer than ~10 bins (every harmonic series below
  ~250 Hz fundamental), any nonzero ratio; grows with |r-1|.
- Symptom: 500 Hz-rate buzz/roughness under sustained chords, tremolo-like
  roughness at the differential frequency (9 Hz at -2 for E2 harmonics).
- Fixture: two tones 1000 Hz + 1082 Hz (3.5 bins) vs 1000 Hz + 1703 Hz (30
  bins), 4 s, +12 and -2. Metric: 2^17 Hann FFT over 1-3 s; energy within
  +-5 Hz of `f_shift +- k*fs/H`, k=1..3, relative to the shifted line; and
  total non-line residual. Pass: sidebands < -50 dB for both spacings.
- Fixes: F2 above (soft region edges remove most Gibbs energy). Window
  variant: end A at ~0.2 instead of 0.008 (max 1/A 5x) at the cost of
  leakage from the edge step (~-26 dB at 2 bins; may hurt peak picking:
  measure with fixture 2). Longer L is excluded by the latency target.

## 4. 64-region cap

- Code: 272-280 (sort by magnitude, keep 64, re-sort by bin).
- Mechanism: dropped peaks' bins join a neighbour's region and are translated
  by `omega_nb*(r-1)`: frequency error `(omega_nb-omega_own)*(r-1)`, e.g.
  3 bins at +12 = 70 Hz on a 2 kHz partial (60 cents). Membership
  re-ranks every frame (also feeds mechanism 2).
- Trigger: 6-note chord with ~20 audible harmonics each (>100 resolved
  partials), or noise/click floor competing.
- Fixture: 80 sinusoids at 300 + 58.6*k Hz (k=0..79, 2.5-bin spacing),
  equal amplitude, 4 s, +7; repeat with 60 sinusoids. Metric: peak-pick the output (2^17 FFT), match to `ratio*f_k`,
  count partials with |error| > 20 cents or missing. Pass: 0 in both.
- Fixes: raise cap (CPU linear: 64 regions = 128 N-point IFFTs per hop
  already); or render weak regions without their own IFFT by assigning
  `delta = omega_bin*(r-1)` per bin via one shared frequency-domain pass
  (loses exact translation for noise only). Risk: none for latency.

## 5. Exact-unity transition resets rotation

- Code: `unitySupport` 334-342; rotation forced 0 when unity (310);
  direct add 363; `regionCount=0` 377-380; unity regions still stored as
  ancestors 374-376.
- Mechanism: after the target becomes 0, frames whose L-support still
  contains nonzero control render post-step samples with constant phase
  `theta_m` (negativeSuffix = 0, 343-347). The first all-zero frame adds the
  raw input (phase 0) and zeroes ancestor rotations. Overlapping frames then
  mix `e^{j theta}`-rotated and unrotated copies of each partial: amplitude
  passes through `|w1 + w2 e^{j theta}|`, a full null for theta = pi, over
  ~3 hops (6 ms). The 0 -> nonzero direction is consistent (theta starts at
  `0.5*(w_prev+w)*hopArea`, matching the suffix convention), verified at
  321 vs 403.
- Trigger: automation lands on exactly 0.0 and stays >= L samples (pitch
  wheel centre, host snap, "off" preset), after any nonunity run.
- Symptom: 6 ms phasey dip/dropout, random depth per partial and per event.
- Fixture: 220 Hz + 1 kHz tones, +3 semitones for T seconds then 0, for
  T in {1.000, 1.013, 1.027, ... 10 values}, each 2 s total. Metric: 1 ms
  RMS envelope around t = T + D/fs; worst dip in dB vs the 50 ms before.
  Pass: all dips < 1 dB (expected to fail with up to -inf dB on a partial).
- Fixes: do not zero rotations in unity frames; keep rendering through
  regions with delta 0 while slewing each rotation toward 0 at a bounded
  rate (e.g. 2*pi*0.5 rad/s), switch to the exact path only when all
  |theta| < 1e-3. Cost: region CPU persists up to ~1 s after return to 0;
  sub-1 Hz transient detune (10 cents at E2 worst). Alternative: never use
  the exact path after a nonunity run (steady CPU, keeps mechanism 3 at 0).

## 6. DC term

- Code: `dc = X[0]/N` added as `dc*synthesis[q]` 361-368; S 118-123.
- Mechanism: (a) S = Hann/(4A) is not a partition of unity (A*S is), so a
  constant `dc` sums to ~1.10-1.15 with +-2.3 % ripple at the hop rate:
  computed sum over hop phases 0/48/95 = 1.104/1.154/1.107. (b) `X[0]/N`
  is `mean(x*A)` = 0.636 c for constant c. (c) The DC lobe's bins 1-2 are
  interior bins of the lowest region and are translated like a tone, and at
  downshifts hard-dropped (mechanism 7). FINDINGS: 0.2 DC -> 0.023 (+7) /
  0.279 (-7) with AC RMS 0.0013-0.0036; the predicted ripple RMS for 0.2 DC
  is ~0.0033, matching. (d) For fundamentals below ~bin 3 (E1 41 Hz = 1.8
  bins; B1 2.6; D2 3.1 partial), lobe leakage into bin 0 is re-emitted
  unshifted, sampled at hop rate through S.
- Trigger: DC offset in DI (common), bass/7-string/drop tunings.
- Symptom: 500 Hz buzz at ~-33 dB re the DC offset, rumble, unshifted ghost
  fundamental.
- Fixture: (i) 0.05 DC + 220 Hz at 0.3, 3 s, +7: line at fs/H and 2fs/H in
  dBFS, mean DC gain. (ii) E1 41.2 Hz at 0.5, -12 and +12: energy at 41.2 Hz
  vs expected 20.6/82.4 Hz. Pass: hop lines < -80 dBFS, ghost < -40 dB.
- Fixes: DC-block input (1st-order HPF ~5 Hz) inside the engine: nil cost,
  no risk for guitar, removes (a)-(c) for offsets. Use `dc*A[N-L+q]*S[q]`
  (= Hann/4) for the DC term: nil cost, exact POU. For (d): fold bin 0 into
  the lowest region's analytic sum when its omega < 3 bins (moves true DC
  with the note; acceptable after HPF).

## 7. Sub-zero destination discard

- Code: 390-396 (`destination > 0.0` else taper 0).
- Mechanism: lowest region with peak p at ratio r drops bins <= p*(1-r).
  At -12 with E2 at bin 3.5: bins 1,2 dropped (lower skirt, ~-20..-30 dB).
  As omega wobbles across the integer threshold a skirt bin toggles on/off
  between frames (hard step, no taper on the low side).
- Symptom: gain loss ~0.5-1.4 dB on low notes (FINDINGS 1.1-1.4 dB at
  B0/E1); clicks at ~-25 dB re fundamental on toggles.
- Fixture: E2 with 0.5 Hz vibrato +-15 cents, 6 s, -12. Metric: bandpass
  25-60 Hz output, 1 ms RMS step count > 3 dB; spectral flux. Pass: no steps.
- Fix: 1-bin raised-cosine low-side taper mirroring 393-394. Nil cost.

## 8. Onset lag and post-smear

- Code: window 108-117 (newest 192 samples weighted 1 -> 0.008); region
  IFFT spreads modified content over all N (419-425).
- Mechanism: a transient entering the window is weighted by A near 0 for its
  first ~2-4 ms, then its energy, once in the spectrum, is re-emitted from
  the last L samples of 21 successive frames with region-dependent rotation
  and translation (each region's rotation is a different phase shift of the
  click). Causal, so post-smear only.
- Symptom: late, soft, slightly "chirped" attacks; measured 3.27 ms lag.
- Fixture: 1-sample impulses every 500 ms over a decaying E2 (0.3), 4 s,
  +7. Metric: output energy in a 60 ms window after each impulse (minus
  the tone via subtraction of the impulse-free render): time to 90 % energy,
  compare to input (1 sample). Pass: < 5 ms.
- Fixes: transient detector with per-frame unity bypass (keeps L-sample
  overlap, no latency change, risk: pitch dropouts on false positives).

## 9. IF-gate toggles

- Code: 300-306.
- Mechanism: the estimate switches between parabola and IF when the +-2 bin
  gate flips; omega may jump up to 2 bins. Phase is continuous at the frame
  end via 321, but the overlap of consecutive frames mismatches by
  `0.5*dw*(r-1)*H` (0.29 rad per bin of dw at +12, 0.88 at +24) and the
  region's delta jumps for one hop.
- Fixture: covered by fixture 1 (IF p-p). Fix: slew omega (see 1).

## 10. Alias taper uses the frame-end ratio

- Code: `frameRatioMinusOne = frameControl[L-1]` 348; taper 387-396.
- Mechanism: destinations are evaluated at the newest control only.
  Downward step (+12 -> 0): the older 3/4 of the support is still
  translated x2 but no bins are removed: content above fs/4 folds for up to
  L samples. Upward step: all bins above the new limit are removed for the
  whole support, including samples that were not shifted: HF dip of L.
- Fixture: 10 kHz + 14 kHz, +12 for 1 s then 0, 2 s. Metric: energy at
  48000-28000 = 20 kHz in the 10 ms after the step + D vs steady state.
- Fix: evaluate the taper at `max_q |omega*frameControl[q]|` (worst-case
  destination over the support). Nil cost; slightly more HF loss during
  downward steps only.

## 11. Negligible / verified consistent

- Coherence gate 300 and previous-magnitude gate 291: mono-duplicated input
  never triggers the first; the second only affects the first onset frame.
- Control integration: `hopArea` (219-223) = sum of the H newest controls;
  `negativeSuffix` (343-347) = minus the sum of later controls; trapezoid
  rotation (321) and in-frame phase (403) agree at the previous frame end up
  to `0.5*(w_prev-w)*hopArea`. Recurrence step (407-412) uses the control of
  the sample being integrated and is re-anchored exactly every 64 samples;
  no phase jump from control changes within a hop.
- Ring: writes `[pos+H, pos+H+L)` mod `L+H` never touch reads `[pos, pos+H)`
  (329-331, 423-431); scheduler finishes all regions by `hopPhase = H-1`
  (224-227). Region bounds: `end_i == begin_{i+1}`, bins 1..N/2-1 covered
  once (385-386). Nyquist omitted at nonunity: inaudible.
- No index/sign/off-by-one bug found. Non-bug but notable: the peak picker
  sorts up to ~500 candidates per frame on the audio thread (274-279).

## Top 5 to test first

1. Fixture 5 (unity transition dip): cheap, deterministic, likely a real
   automation bug; fix is self-contained.
2. Fixture 3 (hop-rate sidebands, 3.5-bin vs 30-bin pair): decides whether
   partition ringing is audible and whether soft region edges (F2) are worth
   implementing before any tracker work.
3. Fixture 2 (noisy decaying chord vs control): quantifies churn crackle on
   the realistic decay-tail case and tests F1/F2.
4. Fixture 1 (E2+G#2 warble): confirms the beat-rate FM of merged regions,
   the dominant steady artifact on every low chord.
5. Fixture 6/7 (DC offset buzz, low-bin toggle at -12): both trivially
   fixable (input HPF, POU DC window, low-side taper); verify before fixing.
