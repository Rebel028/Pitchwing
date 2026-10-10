# Synthetic transport diagnostics

`evaluate.py` runs a bounded NumPy-only evaluation in memory. It prints JSON by
default and writes only when `--output NEW_PATH` is explicit. Existing result
paths are refused. It produces no audio files and does not write to `research/`.
The parent directory of an output path must already exist. The full run contains
50 tone, 12 dyad, 12 temporal, 6 DC, and 2 unity impulse cases. `--quick` contains
24 tone, 6 dyad, 12 temporal, 6 DC, and 2 unity impulse cases. Quick is a smaller
diagnostic matrix, not a quality gate with looser acceptance criteria.

The comparison uses the same transport method, sample rate (48 kHz), hop (96),
synthesis length (384), and scheduled delay (383 samples). The asymmetric branch
has a 2048-sample analysis window; the symmetric branch has a 384-sample window.
This is a matched-delay control, not a comparison against an independently tuned
state-of-the-art symmetric pitch shifter.

## Signals and synthetic target

- Pure sine inputs: B0 (30.867706 Hz), E1 (41.203445), F#1 (46.249303), E2
  (82.406889), and A4 (440). Full runs use -7, -1, 0, +1, and +7 semitones;
  quick runs omit A4 and use -7, 0, +7. Full tone duration is 1.5 seconds;
  quick duration is 1 second. The first 350 ms and last 50 ms are excluded from
  steady measurements. These exclusions do not test pitch settling speed.
- Close dyads: B0/C1 and E1/F1; quick retains B0/C1. The two sinusoids have equal
  amplitude and fixed different starting phases. Each lasts four seconds, with
  analysis over 0.45–3.95 seconds. Shifts are -7, 0, +7 semitones. This duration
  gives enough observation time to inspect low beat spacing independently of
  the engine's much shorter transform. No long observation window is fed back
  into the engine.
- Harmonic gate: B0 starts at 150 ms and finishes release at 750 ms, with 5 ms
  raised-cosine attack and 15 ms release.
- Chord transition: a B0/F#1/B1 chord starts at 150 ms and crossfades into
  E1/B1/E2 from 650–670 ms. The second chord ends release at 1250 ms. Attack is
  5 ms, release is 15 ms, and the complementary crossfade is 20 ms. Both temporal
  fixtures last 1.5 seconds and use -7, 0, +7 semitones. Each voice has eight
  harmonics with amplitude `1 / harmonic**1.3` and deterministic phases.

For every synthetic target, frequency is multiplied by `2**(semitones/12)` while
envelope times and harmonic amplitudes stay fixed. Source and target share the
same source-derived normalization. This is an explicit evaluation reference,
not a unique perceptually correct phase trajectory for every pitch shifter.
B0 and E1 are stress cases below F#1, not agreed or validated supported floors.
Bass support is not established by these tests. The investigation range remains
±12 semitones in project scope; this initial bounded matrix does not cover it.

## Delay and line diagnostics

The unity impulse case measures the peak, energy centroid, and first sample
above absolute amplitude `1e-9`, then compares the complete output with an ideal
delayed impulse. It checks measured unity delay against the declared 383
samples. Non-unity behavior still needs the separate transient diagnostics.

For other tests, `process()` output and `flush()` are concatenated. The first
`latency_samples` output samples are removed for comparison with input event
times. A flush shorter than that delay or nonfinite output fails evaluation.
Temporal metrics retain the exposed tail after this alignment; steady metrics
use only their specified interior interval.

The strongest-line estimate uses a Hann window, at least 4× zero padding to the
next power of two, and a local quadratic interpolation of log FFT magnitude.
Cents error is `1200*log2(measured/target)`. DC is removed before the transform.
Zero padding refines peak location; it does not improve physical resolution.
This metric is useful for a single known sine but does not measure perceived
pitch, preservation of a chord, or the absence of modulation.

Expected-target fitting jointly fits sine and cosine coefficients at the known
target frequencies, plus an independent DC coefficient. The JSON reports each
fitted amplitude, residual RMS, residual-to-centered-output RMS in dB, the
fraction of centered output energy explained, and design condition number.
The fit accepts arbitrary constant output phase. It exposes mistuning, gain
loss, and extra components without confusing phase offsets with pitch error.
Frequency drift or vibrato increases the residual. Nearly coincident harmonic
lines in the chord template are merged within 0.001 Hz to avoid an artificial
ill-conditioned fit. The condition number remains visible. The short late-chord
fit interval cannot separately resolve every nearby harmonic; its combined fit
can be good even when individual fitted amplitudes are unreliable. Neither fitted energy
nor least-squares residual is a perceptual score. Zero ratios with nonfinite dB
values are JSON `null`; silence also has undefined explained-energy fraction.

Tone RMS gain compares the steady output with the equal-amplitude analytic
target over the same interval. It includes unwanted output components; read it
together with the target fit. No arbitrary pass/fail quality threshold is imposed.

## Dyad spacing and resolution

Target spacing is the known source frequency difference multiplied by the
pitch ratio. Expected frequencies are fitted jointly. Observed spacing is
reported only when the Hann spectrum has two local maxima that satisfy all of:

1. The expected pair and detected maxima are at least `2 / observation_seconds`
   apart (about 0.571 Hz for the 3.5-second measurement).
2. The weaker maximum is within 24 dB of the strongest peak in the local search
   band. This rejects the ordinary approximately -31 dB first Hann sidelobe of
   one stationary sine, although other spectral shapes can still mislead it.
3. An intervening valley is at most 80% of the weaker peak's magnitude.

The search band extends three expected spacings (or `4 / observation_seconds`,
whichever is larger) beyond either target. The two strongest qualifying local
peaks are refined as above. Missing, weak, or insufficiently separated peaks
produce `unresolved` with a reason and null observed spacing. The implementation
never chooses the two largest adjacent FFT bins and calls them two notes.

`two_resolved_spectral_lines` describes the measured spectrum only. Amplitude
or phase modulation can generate distinct sidebands that pass these checks.
The pair can also omit a quieter third line; this diagnostic is not a full
spectral inventory. Read observed spacing with the expected-target fit and
frequencies, and inspect failed cases. An unresolved result does not establish
that the algorithm merged the notes: the diagnostic may lack resolution or
confidence. These are spectral-spacing diagnostics of known beat-producing
inputs, not a direct perceptual estimate of audible beat rate.

## Constant-signal diagnostic

The DC fixture is one second of constant amplitude 0.2, at -7, 0, and +7
semitones for each window. After scheduled-delay alignment, samples 24000–46999
(0.5–0.97917 seconds) supply the output mean, AC RMS (standard deviation), and
maximum absolute deviation from 0.2. Ideal constant preservation would keep the
mean at 0.2 with zero AC and zero error. Retaining only the DFT's bin zero is
not sufficient: the analysis window distributes a constant waveform across
other bins. This diagnostic exposes a separate failure from low-note tuning;
it does not test mixed guitar-plus-offset inputs or specify a future DC filter.

## Envelope timing and transitions

The time-varying RMS envelope uses a centered 961-sample (20.02 ms) window with
zero padding. The same measurement is applied to output and analytic target.
The reported onset is the first crossing of 10% of the **target** peak RMS;
thus gain loss can delay or remove a crossing. Centering can move a crossing
before the true event; reported onset difference compares identically measured
signals. `onset_total_delay_ms` adds the declared delay to that difference.
It is a threshold diagnostic, not a sample-accurate latency claim.

Envelope cross-correlation uses 1 ms steps and a ±100 ms search. Positive lag
means the output envelope is later after removing scheduled delay. A boundary
flag identifies cases whose optimum may lie outside the search. Envelope RMS
error is computed after fitting one global gain, without shifting either curve.
Energy quantiles report the times containing 10%, 50%, and 90% of total squared
signal amplitude. A separate metric reports the fraction of output energy after
the final release end plus 50 ms. Temporal fits inspect harmonic energy late in
the sustain: 0.4–0.65 s for the gate and 0.95–1.20 s for the second chord.

These metrics capture gross timing changes, tails, and late tuning failures.
The 20 ms smoothing spans a substantial part of the latency budget; differing
carrier phase and low-frequency beating can shift the measured envelope even
if analytic gates are identical. The reported decimal precision is not timing
accuracy. Cross-correlation over the full chord fixture is not an isolated
chord-change latency or a frequency-settling measurement. A future estimator
must follow individual low components through transitions before making a
settling-time claim. Full-band RMS is not a low-band envelope measurement.

## Interpretation and reproducibility

JSON saves the fixture definitions, frequencies, algorithm parameters, sample
rate, Python/NumPy/platform versions, SHA-256 of the two small engine/evaluator
source files, and total diagnostic wall time. Wall time
includes Python orchestration, FFTs, least-squares fits, and signal generation;
it is not an engine callback benchmark. Run identifiers and engine revisions
belong in the development record accompanying a saved result.

These measurements are **not perceptual or production quality scores**. They
cannot establish Neural DSP parity, acceptable playing feel, bass support, real
guitar attack preservation, or target-native real-time performance in WSL.
Real DI recordings and the user's listening judgments remain necessary. Stereo,
parameter automation, broader sample rates and ratios, native deadline tests,
and low-band pitch-settling analysis remain outside this initial evaluator.

## Estimator self-check evidence

`test_metrics.py` preserves analytic checks of the metric estimators without
rendering the DSP engine. The initial NumPy 1.24.4 probe measured a known B0
sine within +0.000804314 cents and known B0/C1 spacing within +0.0000378967 Hz.
It rejected a single sine's spectral leakage as an unresolved dyad, handled
silence with finite values or JSON null, and fitted the ideal chord targets
with greater than 0.999999 explained energy.

An initial probe's proposed condition-number bound of 10 failed on the known
ideal chord: the observed values were 48.6482, 31.9700, and 21.3811 for -7, 0,
and +7 semitones. Nearby harmonics account for this conditioning; the probe
did not reveal an engine failure. The retained tests use a loose numerical
bound of 1000 while requiring an accurate combined fit. This is a check against
near-singular numerical behavior, not a claim that individual close harmonics
are resolved or a pitch-shifter quality threshold. The measured condition is
also included in every evaluation result.

Run the small checks with an available approved environment:

```sh
OPENBLAS_NUM_THREADS=1 /tmp/pitchwing-env/bin/python -B -m unittest discover -s experiments/transport -p test_metrics.py -v
```
