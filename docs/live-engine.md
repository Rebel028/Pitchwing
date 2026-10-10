# Linked stereo engine with live pitch control

Date: 2026-10-09. `LiveEngine` is a separate implementation for the ShiftKey
consumer. It does not alter `Engine`, the original Python experiment, or any
accepted listening/render evidence. Its public interface is
[`LiveEngine.hpp`](../include/pitchwing/LiveEngine.hpp), and its implementation is
[`LiveEngine.cpp`](../src/LiveEngine.cpp). Construction uses C++17 RAII and the
existing MIT Signalsmith FFT dependency; no new package is required.

## Consumer contract

`LiveConfig` accepts finite sample rates from 8000 through 192000 Hz and finite
pitch targets from -49 through +49 semitones, including fractional values.
This defines accepted controls, not proven musical quality throughout that
range. Construction validates the configuration before allocating and may throw
`std::invalid_argument` or an allocation exception. Move/destruction/preparation
belong outside the callback. Instances are movable and noncopyable.

The caller must serialize access to each instance, including the pitch setter;
there are no internal locks or atomics. Pass parameter events on the processing
thread, splitting a block at their sample offsets when necessary. The setter
changes the raw target for the next accepted input sample, including during an
active stream. It neither resets audio history nor starts a second engine.
There is no hidden target ramp. Multiple setter calls without intervening input
have no sample duration; only the last such target applies.

| Operation | Contract |
|---|---|
| `process(left,right,outLeft,outRight,frames)` | Planar float or double stereo, exactly `frames` returned. Arbitrary block lengths, exact in-place processing, crossed exact in-place buffers, and identical mono input pointers are supported. |
| Buffer overlap | Output channels must be disjoint. Every other pair must be disjoint or exactly equal; partial overlap is rejected. Input/output arrays must contain enough accessible live elements. |
| Zero frames | Accepts null pointers without advancing state while open. A closed stream returns `StreamClosed`. |
| Sample validation | The whole block must be finite, with absolute values at most `1e30` for both float and double. Validation failure returns `InvalidSample` before output or DSP state changes. |
| Invalid buffers | Return `InvalidBuffer` before reading samples or mutating processing state. Address-range checks cannot prove a nonnull pointer actually owns accessible storage. |
| `setPitchSemitones` | Finite values in `[-49,49]` return `Ok` while open; invalid values return `InvalidPitch`. After closure a changed valid value returns `StreamClosed`, while an identical value is still `Ok`. |
| `reset()` | Clears histories, pending work, and output without allocating; preserves sample rate and the current target; reopens a closed stream. This explicitly discards sound and is not a live bypass switch. |
| First `flush` | Offline terminal drain requiring two disjoint output arrays with capacity at least `tailSamples()`. Feeds that many zero-input samples at the last target, writes the full tail, and closes even an initially empty stream. |
| Failed `flush` | Writes `written=0`, leaves audio output and stream state untouched. Capacity is checked before buffer addresses. |
| Repeated `flush` | Returns `Ok` with `written=0`, permitting null buffers/zero capacity. |
| Moved-from instance | Status operations return `NotPrepared`, flush sets `written=0`, size queries return zero, and `config()` returns default settings. |

All allocations, container sizing, FFT plans, and windows are prepared during
construction. Processing, the setter, reset, and flush contain no allocation,
locking, I/O, planning, or container growth. Allocation checks pass in the
[live validation](live-validation.md); target-native timing remains open. Input validation has
linear cost in the caller's block size. The shared input limit leaves ample
float-representable headroom for coherent sums even when a caller switches from
double input to float processing or flushing. An earlier draft allowed `1e100`
for double, which could queue values overflowing a subsequent valid float call;
review caught this and the bound was unified before validation. There is no limiter, gain compensation,
normalization, or promise that normal audio stays below full scale.

## Rate-dependent geometry and scheduling

For sample rate `fs`, choose:

```
H = floor(fs * 0.002)
L = 4 * H
N = Signalsmith SplitFFT::fastSizeAbove(ceil(fs * 2048 / 48000))
D = L - 1 + H
tail = N + D + H
```

The public geometry queries return these prepared sizes. They remain fixed for
an instance; prepare a new instance for a sample-rate change. `D` is 439 samples
at 44.1 kHz, 479 at 48 kHz, and 959 at 96 kHz, below 10 ms at all accepted rates.
The additional hop is deliberate scheduling delay and included in the reported
latency. No adapter, FIFO, or resampler sits outside that count in this class.
Scheduled delay does not characterize pitch settling or host/device buffering.

Frames are analyzed after ingesting samples `t=0,H,2H,...`. Each frame writes a
length-L output contribution beginning at `t+H` into a ring of length `L+H`.
Spectra, regions, control support, and destination origin are immutable until
that frame finishes. During hop phase `p`, the scheduler completes
`floor((p+1)*R/H)` of the frame's `R` regions. Thus all region work finishes at
`t+H-1`, before any sample of that frame can be emitted. Input history continues
to advance independently. There are at most 64 regions, and `H>=16`; the
scheduler handles more than one region per input sample at low rates.

FFT analysis and peak selection still occur at frame boundaries; the two
per-region inverse transforms are distributed over the hop. This reduces one
source of bursts, not all bursts. It also does not prove deadline compliance
on either WSL or the consuming Windows machine.

## Linked stereo analysis

Use a shared peak magnitude `hypot(abs(X_left),abs(X_right))`, then the existing
local maxima, 64-region cap, relative floor `1e-4`, and stable
flat-spectrum/tie policy. Both channels retain their own complex spectra. The
region frequency is a least-squares fit of the three peak bins of both channels
to `X[k] = a*A(w_k - w) + conj(a)*A(w_k + w)`, where `A` is the tabulated
spectrum of the analysis window (1/64 bin over ±24 bins) and `a` is solved per
channel; `w` is found by a nested 13-point grid search over ±0.6 bin (from 0
for peaks at bin 1). The image term matters: without it the previous
log-parabola and cross-frame phase-difference estimates wobbled 150–680 cents
frame to frame below bin 4 and carried a −15 cent bias at E2
(`docs/results/2026-10-10-estimator-probe.txt`). The fit is a single-sinusoid
model; it does nothing for unresolved dyads. Near `w = 0` only `Re(a)` is
determined (a DC lobe) and the fit falls back to that real-only solution, also
when the two-parameter amplitude exceeds four times the data (ill-conditioning).

The lowest region owns DFT bin 0: its fitted tone share `2*a*A(-w)` is translated
with the region, and the remaining `X[0] - a*A(-w) - conj(a)*A(w)`, divided by
the window sum, is the true DC and is rendered untranslated with the exact
partition-of-unity window `analysis*synthesis = (1-cos)/4`. Measured: 0.05 DC +
220 Hz at +7 hop lines −61 → −148 dBFS, DC gain 0.725 → 1.00; the unshifted
41 Hz ghost of E1 fell from −18 dB to −75 dB. Destinations below zero are no
longer dropped: `Re(z*e^{j*delta*n})` folds them to `|destination|`, which is
the conjugate reflection of a real signal's lobe; low-tone gain loss at −7 fell
from −1.1…−1.5 dB to −0.7…−0.9 dB (E2: −0.23 dB).

Unresolved low partials are split, not re-analysed
(`docs/quality/2026-10-10-multires-gauntlet.md`). A second past-heavy analysis
spanning `4n` samples runs whenever the frame is not exact unity and supplies
frequencies only. It is computed on a decimated copy of the input (largest
divisor of `4n` keeping ≥ 6 kHz, 8 at 48 kHz; Kaiser anti-alias FIR, ~90 dB,
transition 750 Hz to rate/M − 750 Hz since only aliases below the 700 Hz search
limit matter), so its FFT is `4n/M` points with the same bin spacing as a full
`4n` frame; the window has the same construction with a fall of `L/(2M)`
samples and its own closed-form lobe table; it is
never transported, so latency, bloom and the short frame's time resolution are
unchanged. Its peaks below 700 Hz (floor `1e-4` re the short maximum scaled by
the window sums, skirt peaks dropped with its own lobe table) are counted per
short region. Neighbouring short regions whose long peaks are < 3 short bins
apart are merged first (an unresolved pair shows one or two short peaks
depending on the beat phase). A group is split when it holds 2–4 long peaks
within 2.5 short bins of its short peaks and ≥ −40 dB re the strongest of them
(weaker ones are long-window skirt ripple), spaced ≥ 0.35 short bin: the long
peaks' frequencies are refined jointly (coordinate descent, amplitudes solved
jointly over the cluster's long bins; single-lobe fits are biased ~14 cents
p-p by the neighbour), then the short frame fits only the complex amplitudes of
all component lobes over the group's bins (`jointFit`, Cholesky with a 1e-12
ridge). The group is rendered as one residual entry (bins minus all fitted
lobes, merged short `w`) plus one entry per component (its fitted lobe, own `w`
and inherited rotation). Each component's image term `conj(a)*A(k+w)` is
placed conjugated on the mirrored bins `n-k`, so the modulator moves it by
`-delta` with its partial (as positive content it left `f - delta` lines at
−31 dB). Bin 0 of a split lowest group: components carry `2*a*A(-w)`, the
residual nothing, and the DC term is `X[0]` minus all component shares. The
parts plus the residual equal the group's bins, so the untranslated sum is
unchanged. E2+G#2 at ±7: lines within 0.1 % of the required spacing (was
50 %/−33 %), outer beat sidebands −26/−17 → −86/−90 dB, output residual
re an ideal two-tone −51 dB.

Lobe ownership (all regions, step 6). A partial whose 3-bin lobe fit leaves
≤ 2 % residual and whose centre is ≥ 1 bin owns its fitted lobe over ±24 bins
(window skirts included), transported with its own `w`; its image term goes
conjugated to the mirrored bins as for components. Every bin-owning entry
(plain region, split residual) renders `X − model` in its bins, where `model`
is the sum of all transported lobes; bin 0's remainder `X[0] − model[0]` is
the DC term. The sum over entries is still exactly `X`. Before, a partial's
skirt outside its own region was translated with the neighbour's `delta`
(−19 dB lines at f ± (f2−f1)(r−1) for a 3.5-bin pair) and its image term by
`+delta` (low-tone gain −0.7…−0.9 dB, fit 0.984–0.99). Sub-bin regions (a DC
lobe) keep bins only, and when lowest their fitted bin-0 share as before
(rendering a lobe there made pure DC +7 lose 25 %).

Peak fits run in two passes (step 8). Pass 1: 13-point grid over the peak bin
±0.6 (from 0 at bin 1), then four parabolic steps (spacing 0.1 bin, shrinking
4×; 25 cost evaluations instead of 65). Pass 2, for peaks with a credible
neighbour (3-bin fit residual ≤ 30 %, centre ≥ 1 bin) within ±24 bins: the
neighbours' pass-1 lobes are subtracted from the peak's three bins and the fit
is repeated by four parabolic steps from the pass-1 centre (spacing 0.15 bin —
0.05 could not reach the bias and cost 3 dB). Lobe ownership uses the pass-2
quality (≤ 2 %). Subtracting non-credible fits (DC-lobe sidelobes) broke pure
DC at +7.

Split groups (step 9) hold up to 32 components (a low chord's harmonic series
chains into one group below 700 Hz; the former cap of 4 left real chords
unsplit). The long-frame frequencies use a single fit plus two local refits on
bins cleaned of the other components' lobes (the joint coordinate descent was
O(m³) per sweep). Components are rendered as oscillators,
`Re(2a·n·w[n−L+q]·e^{jω(n−L+q)}·modulation[q])` — the exact IFFT of their lobe
plus mirrored image, untruncated — instead of an n-point IFFT each.

Region ancestry, transport rotation, and modulation are shared. The analytic
inverse transforms remain separate per channel, preserving signed proportional
channel relations without mixing samples between channels. A silent channel
therefore remains silent; arbitrary independent material in both channels can
still compete for shared peaks. Linked analysis is not a claim of perceptually
perfect imaging on all stereo recordings.

## Pitch-event integration

For every accepted input sample store `u[t] = 2^(semitones[t]/12)-1` in a
length-L control history. The pre-stream history is zero. At frame time `t`,
snapshot that history and the sum of controls since the previous frame. The
rotation of a tracked region is

```
theta[t] = principal(theta_previous
                   + 0.5*(omega_previous+omega_current)
                     * sum(u[t-H+1 .. t]))
```

The first frame has no ancestor and starts at zero rotation. Its input controls
before stream start have zero duration/area. For synthesis support sample `s`,
use

```
phase(s) = theta[t] - omega_current * sum(u[s+1 .. t])
```

This endpoint convention advances the phase of source sample `s` using the
command attached to `s`; the suffix excludes `s` when reconstructing backward
from the frame end. Commands lasting fewer than one hop contribute both phase
area and support modulation, even if neither surrounding frame-end target shows
them. Already scheduled frame work uses its saved control snapshot, so a new
setter call cannot modify a pending contribution.

For constant controls this is the same intended linear phase function as the
static design. Initial control history, coherent stereo tracking, scheduler,
unity reacquisition, and changing targets make this a new behavior; no literal
parity with the earlier mono engine is asserted.

Modulation is calculated once per region and reused by both channels. Complex
recurrence reuses a step within each constant-control run and is re-anchored
from the exact suffix sum every 64 samples. There is no accumulated recurrence
error across a frame. Commands that change every sample still require many
transcendental evaluations; normal block-rate automation costs less.

A bounded synthesis optimization prepares `synthesis[q]/N` during construction
and includes that scalar in the cached region modulator. Both channels reuse
the weighted complex value. Each output accumulation evaluates only the required
real dot product (`time.real*weight.real - time.imag*weight.imag`), avoiding an
unused imaginary product and repeated per-channel normalization/window scaling.
The FFT, region selection, persistent phase, control integration, and scheduler
are unchanged. Floating-point association differs, so the parent compares a
captured pre-optimization waveform within numerical tolerance before measuring
timing again. This change does not itself establish a speedup or callback bound.

When all L saved controls are exactly zero and every inherited region rotation
is exactly zero, add the original windowed recent time-domain samples directly;
no inverse transforms are needed for that frame. After a nonunity run the
rotations are not reset (a reset mixed rotated and unrotated copies of each
partial in the overlap ring and measured dips to −15 dB per partial); unity
frames keep rendering regions with zero translation while each rotation is
slewed towards zero by at most `max(omega, 2*pi*100 Hz) * H * 0.006` per hop,
i.e. a glide of at most 10 cents (33 cents below 100 Hz), so the worst case
settles within about 420 hops. Sustained unity then becomes exact delayed
reconstruction without clearing audio history (measured per-partial dips
≤ 0.7 dB, `scripts/quality_fixtures.py --only unity`).

## Preserved limitations and validation ownership

The implementation keeps rigid region translation, ungated nearest-frequency
ancestry (rotations with a per-hop translation advance below 1e-3 rad are slewed
to zero), Nyquist omission outside exact unity, and the two-bin high-frequency
taper. It does not solve unresolved low-dyad spacing, low-note settling, or
spectral collisions; a DC offset at a nonzero shift keeps a small ripple
(0.2 DC: 0.005 RMS at −7, 0.019 at +7). The alias guard
uses the frame-end ratio only. A short high-ratio excursion inside the saved
support can therefore exceed the guard's assumed destination range; there is
no proof of dynamic alias suppression. Extreme target values are accepted
without guaranteeing useful bandwidth or timbre.

The parent owns compilation, warnings, contract tests, ASan/UBSan, event/block
equivalence, stereo tests, low-register measures, listening renders, and timing.
The implementation worker ran no independent build or audio experiment. The
main agent coordinated the completed [validation](live-validation.md), including
release/sanitizer checks, packaging, numerical optimization comparison and
diagnostic timing. Existing historical evidence remains unchanged.
