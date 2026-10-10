# First transport candidate: measured findings

Date: 2026-10-08. Initial result: the algorithm does not meet the measured
low-register polyphonic requirement. Later decision: the user accepted the
real-guitar listening comparisons and explicitly requested a native C++ engine
now. Port this baseline faithfully and retain the failures below for subsequent
DSP work. This supersedes the original decision to defer the native port;
it does not change any measurement or establish production quality.

The full in-memory run is saved in
[results/2026-10-08-initial.json](results/2026-10-08-initial.json), including
source hashes and environment/configuration metadata. It contains 50 tone,
12 dyad, 12 temporal, 6 DC, and 2 unity-delay cases. Both configurations use
48 kHz, a 96-sample hop, and 383 samples of scheduled delay. The asymmetric
analysis has 2048 samples; the symmetric baseline has 384. Wall time was
25.67 seconds under WSL; this is not an audio callback benchmark.

## What works

The processing interface passes nine tests, including all 96 impulse positions
within a hop for both windows, variable input blocks, reset, draining, invalid
inputs during an active stream, read-only configuration, and resolved-tone
octave direction/gain. Five separate metric tests validate measurements against
known signals, including rejecting a single tone's leakage as a resolved dyad.

Both configurations reconstruct unity at exactly 383 samples. The asymmetric
configuration's isolated B0/E1 strongest-line errors remain below one cent at
the four tested nonzero shifts (-7, -1, +1, +7). The short symmetric baseline
often retains the original strongest line at those low frequencies. However,
accurate strongest-line placement is only one property: asymmetric B0/E1 fits
contain about 96–97% of AC energy at the expected frequency and lose roughly
1.1–1.4 dB. Modulation and other residual energy remain.

The asymmetric E2 case is also worse than those lower isolated tones: -7 gives
about +7.03 cents and +7 gives about -4.71 cents. A4 is comparatively clean.
Neither a few favorable tones nor a larger analysis window establishes quality
across the input range.

## The central low-dyad failure is reproduced

| Asymmetric case | Required spacing | Measured spacing |
| --- | ---: | ---: |
| B0/C1, -7 semitones | 1.225 Hz | 1.836 Hz |
| B0/C1, +7 semitones | 2.750 Hz | 1.835 Hz |
| E1/F1, -7 semitones | 1.635 Hz | 2.450 Hz |
| E1/F1, +7 semitones | 3.671 Hz | 2.450 Hz |

The original spacings are 1.835 and 2.450 Hz. Moving an unresolved region as
one carrier preserves its internal spacing. The experiment reproduces that
failure for both windows. Asymmetric nonzero-shift fits to the expected dyad
frequencies contain only about 0.2–3.8% of output AC energy in these fixtures.
The spectral spacing diagnostic does not itself prove each observed line is a
preserved input note; modulation sidebands may also appear as distinct lines.

Decision: reject rigid one-carrier-per-region translation as sufficient for the
required low polyphony. Better isolated-tone frequency estimates alone cannot
fix this behavior. A subsequent experiment must change how unresolved mixtures
are represented or evolved, and must explicitly demonstrate scaled spacing.

## Other failures and limits

- DC is not preserved under nonzero shifts. For constant input 0.2, the
  asymmetric +7 case settles to mean 0.02337 with AC RMS 0.001296; asymmetric
  -7 settles to 0.27948 with AC RMS 0.003643. Preserving DFT bin zero does not
  preserve the full windowed constant waveform. A future design needs an
  explicit DC policy that does not accidentally remove low guitar fundamentals.
- The asymmetric +7 low-chord onset crosses the measured envelope threshold
  about 3.27 ms later than the synthetic target after scheduled-delay alignment.
  The envelope uses centered 20 ms RMS smoothing; this is a diagnostic, not a
  precise perceptual attack-delay claim.
- Late expected-harmonic fits in the asymmetric changing-chord fixture contain
  approximately 16.55% (-7) and 4.16% (+7) of output AC energy. Close harmonics
  and short fit intervals complicate interpretation; this still supplies no
  evidence of acceptable chord reconstruction.
- The region tracker inherits the nearest previous region without a distance
  gate. Newly appearing notes may inherit unrelated phase. Region changes and
  the nominal-bin Nyquist guard have no demonstrated artifact bounds.
- The implementation allocates per frame and uses a batched inverse FFT for
  every region. It is mono, static-ratio Python research code. Stereo, automation,
  sample-rate coverage, shifted impulse phase sweeps, real DI, listening, and
  native callback deadlines are unvalidated.

## Next experiment

Keep the verified scheduler, interface checks, metric tests, and failed fixtures.
Investigate within-region mixture estimation/evolution or a different analysis
representation, with B0/C1 and E1/F1 beat scaling as explicit early criteria.
Consider longer causal history only alongside onset and chord-change checks;
additional history alone does not resolve the tradeoff. Compare any new design
with this saved run rather than overwriting it. Native implementation now
proceeds alongside these unresolved quality requirements, per the later user
decision recorded in [DEVELOPMENT.md](../../DEVELOPMENT.md).

Real dry DI clips will complement these tests. Useful clips contain below-F#1
notes, close intervals, palm mutes, bends, and ringing chord changes. Record
tuning and sample rate, preserve original levels and leading/trailing silence,
and compare identical DI through the candidate and exact reference transposer.
Human listening and playing decide naturalness and feel; synthetic numerical
metrics do not substitute for that evaluation.
