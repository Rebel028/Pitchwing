# Multi-resolution low band: design note before prototyping (2026-10-10)

Status: design only, no code. Written after the gauntlet re-scoped the
unresolved-dyad work (`2026-10-10-gauntlet.md`, synthesis item 5) and after the
estimator/DC/fold step landed (`DEVELOPMENT.md`). To be gauntleted briefly
(formalist + historian) before implementation.

## Why

Measured: an unresolved low pair (E2+G#2, 21.4 Hz = 0.9 bin at N=2048) is
translated by one merged ω, so at −7 st both notes land ~100 cents off
(51.6/73.1 Hz instead of 55.0/69.3) and the interval widens from 400 to ~600
cents (`docs/results/2026-10-10-fixtures-step3.json`, `warble`). Every low
third, second and the E2–B2 fifth (41 Hz) is affected. This is the dominant
musical defect of the engine; the estimator fix did not and cannot touch it.
The parametric low band proposed in the research options was rejected by all
four gauntlet reviewers (envelope re-imposes the old beat, undefined phase
splice, stale model across chord changes, stereo collapse).

## Proposal

Run a second, longer past-heavy analysis for the low band only and feed its
regions through the *same* transport (regions, ω fit, rotation, per-sample
modulator, synthesis window). No parametric synthesis, no new phase convention.

- Long analysis: N_low = 4·N (8192 at 48 kHz, 171 ms, 5.9 Hz bins; E2+G#2 is
  3.6 bins apart, E2+A2 4.7, E2–B2 7). Window A_low: same cosine fall over the
  final 192 samples and the same values over the whole 384-sample support as
  A (so `A_low[N_low−L+q] = A[N−L+q]`), sine rise over the longer past. Then
  the existing `synthesis = (1−cos)/4 / A[N−L+q]` is valid for both analyses
  and the OLA of untranslated content stays an exact partition of unity.
- Band split: regions whose peak lies below a crossover (≈ 350 Hz) come from
  the long spectrum, the rest from the short one. The crossover is a soft
  cos² ramp of several short-analysis bins (≈ 8 bins = 190 Hz wide) applied as
  complementary masks: long spectrum × (1−c), short spectrum × c. A soft
  ramp keeps the band-split kernel short (~5 ms), so the inconsistency between
  `A_low·x` and `A·x` (they differ only before the support) leaks negligible
  old content. Brick-wall split would ring for ~N/transition.
- Region IFFTs for low regions are N_low-point (4× cost each, but low regions
  are few: ≤ ~12 below 350 Hz). One extra forward FFT(8192) per channel per hop.
- ω fit: the lobe table is per window; build a second table for A_low (same
  code, different N). Bin 0 / DC handling moves to the long analysis (its bin
  0 is the DC).
- Rotation inheritance: unchanged (nearest previous ω); long and short regions
  share one ancestor list since ω is in rad/sample for both.

## Expected effects and risks (to measure, not assume)

- E2+G#2 at ±7: spacing scales (14.3 / 32.1 Hz) with the two notes within
  ~5 cents; residual skirt sidebands at −19 dB-class levels as for resolved
  pairs today (fixture `hop_sidebands`), unless the window-tail study lowers
  the skirts.
- Low-band attack smear: a low region of width b bins is a bandpass with a
  ~N_low/b-sample kernel; narrow low regions (≈ 2 bins = 12 Hz) smear a
  fundamental's attack over up to ~100 ms inside the 171 ms frame. Attacks
  are dominated by the > 350 Hz band from the short analysis, so the audible
  risk is a slower bass "bloom". Fixture: chord-onset fixture from the window
  study (Q3) and the `low_chord_crossfade` late-fit / onset metrics.
- ω lag on bends: the long window's centroid is ~85 ms old; a 1-semitone bend
  over 200 ms gives a transient error of ~7–14 cents × (r−1)/r. Fixture: E2
  linear bend of 2 semitones over 300 ms at ±7.
- Chord changes: the long spectrum holds the previous chord for ~170 ms; the
  merged/old regions translate the new notes with stale ω for that time. The
  short analysis has the same problem at 43 ms today (late fit 0.14–0.24).
- CPU: + FFT(8192) × 2 channels + ≤12 IFFT(8192) × 2 per hop ≈ 2× today's
  typical cost; still below the 64-region worst case. Measure with
  `tools/pitchwing_live_probe`.
- Exact unity: unaffected (direct add path). Unity-settling frames render
  both bands with δ = 0.

## Alternatives kept in view

- N_low = 2·N (4096, 85 ms, 11.7 Hz bins): resolves ≥ ~25 Hz pairs only
  (E2+A2 marginal at 2.3 bins, E2+G#2 at 1.8 bins unresolved), half the smear
  and lag. Make N_low a constructor constant and measure both.
- Two-scale estimator only (historian): long FFT feeds ω estimates for low
  regions but the short spectrum is still transported — does not fix the
  spacing (the bins are shared), rejected for the output path.

## Acceptance

Before/after on `evaluate.py` full matrix (dyads E1/F1 and B0/C1 are
informational — out of reach at 171 ms), `quality_fixtures.py` (warble must
pass spacing within 5 %, hop_sidebands and churn must not regress), the new
bend and chord-onset fixtures, tests green, and the `06/minus7` and chord DI
listening renders re-made for the user.
