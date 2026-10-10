# First streaming spectral transport experiment

Date: 2026-10-08. Status: falsifiable research prototype, mono and static ratio.
The deliverable remains an engine. This experiment is not a VST, a native C++
implementation, a real-time callback implementation, or evidence of competitive
guitar quality. The required tunings below F#1 are evaluation cases, not a
supported-range claim. Read `../../PROJECT.md` for current scope.

## Purpose and implementation choices

`engine.py` implements the long-history/short-synthesis scheduling described in
`../../research/architecture.md`, plus a minimal coherent region transport.
The preserved checkpoint is unchanged. This implementation is written from the
public mathematical description; no competitor code or binary implementation
is used or inferred.

The first question is whether even this uncomplicated transport retains useful
low-tone and close-dyad behavior at the verified scheduling delay. A negative
answer remains useful evidence. Do not add onset heuristics or port the DSP to
C++ on the strength of reconstruction or isolated midrange-tone tests alone.

Fractional movement uses one analytic inverse transform per region followed by
complex modulation. This is an exact fractional frequency translation of each
selected finite Fourier sum, avoiding an uncalibrated bin interpolator. It is
deliberately more expensive than an eventual remapper. It does **not** remove
window truncation, positive/negative frequency overlap, alias-cancellation, or
region-tracking problems. Limiting the peak count to 64 bounds transform memory
and frame work; this cap is an explicit research simplification.

## Public interface and terminal behavior

```python
engine = TransportEngine(sample_rate=48000, analysis_size=2048,
                         synthesis_size=384, hop=96, semitones=0.0,
                         window="asymmetric")
output = engine.process(input_mono)   # same sample count, float64
tail = engine.flush()                # terminal, includes delayed output
```

- `latency_samples` is `synthesis_size - 1`: 383 samples, or approximately
  7.979 ms, with the default 48 kHz configuration. It is scheduled delay and
  says nothing about low-frequency pitch/envelope settling.
- `process` accepts one-dimensional real integer/float arrays, rejects complex,
  boolean, nonfinite, and greater-than-`1e100` absolute samples, and leaves the
  argument unchanged. The entire block is checked before stream mutation.
  Empty real arrays are accepted before closure and do not start the stream.
- The first `flush` feeds exactly `N + (L - 1) + H` zeros and returns all resulting
  samples. This includes history expiry and the remaining synthesis ring, even
  for an empty stream. Tail length is therefore 2527 samples by default and can
  exceed the delay; trim only with an explicit evaluation/rendering policy.
- A second `flush` returns an empty float64 array. Every `process` after flush,
  including an empty one, raises `RuntimeError` until `reset`.
- `reset` clears history, output, previous spectrum, region phase state, frame
  clock, and closure, retaining configuration and pitch.
- `set_pitch_semitones` accepts finite values in `[-12, 12]`. A changed value is
  accepted only before the first nonempty `process` or after reset. The identical
  value is a no-op at any time. Invalid values are rejected before mutation.
  This slice has no parameter automation or ratio-crossing claim.
- `render(samples, **config)` concatenates `process(samples)` and the full tail.
  No gain normalization, clipping, trimming, audio file I/O, or resampling occurs.
- The matched symmetric configuration is `analysis_size=384`,
  `synthesis_size=384`, `hop=96`, `window="symmetric"`. Its scheduled delay is
  also 383 samples. Symmetric mode requires `N == L`; both sizes must be even,
  `N >= L >= 8`, and `H` must divide `L` with at least two overlaps.

Configuration attributes are read-only properties backed by private fields;
attempting assignment raises `AttributeError`. This prevents public settings
from diverging from prepared windows and tables, an issue found in the initial
read-only review and corrected without changing DSP behavior. Instances are not
thread safe. Non-default sample rates use the requested sample counts as given; the
caller must scale sizes to compare equal time support at other rates.

## Reconstruction and exact schedule

For frame end `t = 0, H, 2H, ...`, the ordered frame contains input
`x[t-N+1 : t+1]`, with zeros before the first input. Its DFT uses the frame-start
convention `X[k] = sum_n x[t-N+1+n] A[n] exp(-j*2*pi*k*n/N)`.

For asymmetric analysis, `P = N-L/2` and:

```text
A[n] = sin(pi*n/(2*P))                  n < P
A[n] = cos(pi*(n-P)/(2*(N-P)))          n >= P
g[q] = (1-cos(2*pi*q/L)) / (L/H)        0 <= q < L
S[q] = g[q] / A[N-L+q]                 zero where numerator/denominator are zero
```

Symmetric analysis uses `A[n] = sin(pi*n/N)` and the same product-window rule.
The overlap sum of `A*S` is one. A frame's newest `L` inverse-transform samples
correspond to original indices `t-L+1+q`. They are accumulated at output index
`t+q`, exactly `L-1` samples later. Compute the frame before emitting output
sample `t`. History and overlap-add buffers have lengths `N` and `L`; arbitrary
caller block boundaries never reset the hop clock or add a block FIFO.
This implementation's hop origin is `t=0`, whereas the imported scaffold uses
`t=H-1`. Both conventions can support the same exact scheduled delay when each
computes its frame before emission; startup waveforms at nonunity need not match.

At ratio one the spectrum is inverse-transformed without transport edits. Peak
estimation and region state still advance, so reset/flush lifecycle is shared.
This exact path deliberately establishes only reconstruction and scheduling.
There is no active-stream ratio change that would justify claiming a smooth
transition between this path and modified spectra.

## Regions, phase reference, and fractional movement

Detect local maxima in positive-frequency interior bins. Keep peaks above
`1e-4` times the largest interior-bin magnitude, with at most the 64 strongest.
If there is no interior maximum, retain the largest interior bin. This fallback
is relevant for DC-dominated or unresolved low-frequency spectra. Partition all
interior bins at midpoint boundaries between retained peaks, including residual
bins; no stochastic residual or independent fundamental tracker is used.

The bootstrap frequency estimate is a clamped log-magnitude parabola. It is
not an asymmetrical-window calibration. Where previous same-bin energy exists,
prefer the phase-difference estimate:

```text
omega_hat = omega_k + principal(angle(X_m[k])-angle(X_(m-1)[k])-omega_k*H)/H
delta = (ratio-1) * omega_hat
```

Accept this estimate only in `(0, pi)` and within two bin widths of the bootstrap
estimate. This is a rudimentary sanity gate, not an onset/confidence model.

Each current peak inherits the previous region with closest estimated frequency.
There is no distance gate: even a remote new peak inherits an existing region.
The early implementation discussion suggested gated association, but the actual
first slice uses this simpler explicit rule; only the IF estimate has a gate.
Splits can share an ancestor; a merge takes its nearest ancestor. Its frame-end
rotation is:

```text
theta_m = principal(theta_previous + H*(delta_previous+delta_m)/2)
```

The first active frame following zero spectral history starts with `theta=0`.
New regions otherwise inherit existing phase instead of arbitrarily resetting.
There is no reliable track identity or phase-safe crossfade at peak crossings;
nearest-ancestor inheritance can still fail at births, merges, or new chords.

For region `R`, construct its finite analytic sum `z_R[n]` by putting
`2*X[k]` in that region's positive interior bins and zero elsewhere, followed by
an `N`-point inverse FFT. Synthesize only `N-L <= n < N`:

```text
y_R[n] = real(z_R[n] * exp(j*(theta_m + delta_m*(n-(N-1)))))
```

The factor `n-(N-1)` anchors fractional translation at the frame **end**;
`theta_m` advances between frame ends. For a stable isolated sinusoid this
applies the expected additional phase advance and local frequency translation.
It does not stretch a region's lobe width. Within one unresolved region, two
tones retain their original spacing under a common translation; a true shift
would multiply their spacing by the ratio. Close low dyads are therefore a
necessary falsifier, even when individual-tone tuning looks good.

## Boundary bins, aliasing, and gain

During nonunity transport, the DC coefficient contributes `real(X[0])/N`
without movement. The Nyquist coefficient is omitted because it has no unique
positive-frequency analytic phase direction. Unity retains both endpoints.
An STFT DC coefficient also contains low-tone window leakage; holding that
coefficient fixed is a known possible low-register error, not a guarantee of
correct constant/DC or sub-bin-tone behavior at nonunity.

For each interior source bin, consider its nominal destination `omega_k+delta`.
Discard nonpositive destinations. Use a raised-cosine taper over the final two
DFT bins below positive Nyquist; destinations at/above Nyquist get zero weight.
Do **not** apply a symmetric two-bin low-frequency taper: at the default FFT
size it would suppress much of the required sub-F#1 range by construction.
These per-coefficient rules do not establish a measured anti-alias rejection
specification for finite windows or changing regions. Measure aliases and gain.

Colliding regions add coherently. There is no hidden normalizer or limiter.
Omitting endpoint energy, boundary guards, region collision, and modified WOLA
alias cancellation can change gain; those changes must remain visible in data.

## Focused implementation checks and limitations

Focused in-memory checks used Python 3.8 / approved NumPy 1.24.4 in
`/tmp/pitchwing-env`, with `OPENBLAS_NUM_THREADS=1` and no bytecode writes:

- Seed-5 Gaussian input, 2400 samples, default unity: maximum delayed error
  `1.33e-15`.
- A 0.5-amplitude 750 Hz sinusoid, 0.5 seconds at 48 kHz, evaluated after 0.1
  seconds: shifting down 12 semitones placed `0.999815` of measured steady energy
  at 375 Hz, with gain `0.999454`; shifting up 12 placed `0.999924` at 1500 Hz,
  with gain `0.999893`. These are sinusoid projection checks of sign and phase,
  not a musical-quality result or broad sideband/alias specification.
- Those checks preceded removal of the lower two-bin taper. That correction
  addresses a low-frequency design flaw; parent integration checks cover the
  final code. Do not treat the numbers above as final comprehensive metrics.
- The parent subsequently reported all eight interface/scheduling/phase tests
  passing for the final lower-taper correction, including 192 impulse cases
  across both windows' hop phases and octave-shift tone concentration.

The parent task owns broader API tests and evaluation, including the final
code's reproducible metrics and failed cases. This file records the implementation
agent's decisions and preliminary observations so they do not remain in context.

Outstanding issues include low-note gain/tuning, unresolved mixtures, endpoint
leakage, transient historical smearing, region reassignment, onset and pitch
settling, stereo, automation, and usable shift range. Frame processing allocates
NumPy arrays and performs up to 64 complex inverse FFTs. It is unsuitable for a
real-time callback. WSL timings must not be reported as native engine performance.
Streaming state is bounded independently of stream duration; returned caller
buffers and temporary per-call results naturally scale with that call's size.

Next: inspect matched-delay asymmetric/symmetric measurements and preserve
negative cases. Evaluate representative real DI recordings with the user for
musical quality; objective signal measurements cannot replace listening or
playing-response judgments.
