# Native engine core

`pitchwing::Engine` is a mono, static-ratio pitch shifter with a 383-sample
scheduled delay at the default configuration. It is a C++17 static library
with no plug-in wrapper. The public interface is `include/pitchwing/Engine.hpp`;
the implementation and all preallocated state are in `src/Engine.cpp`. The
numerical design follows the Python experiment `experiments/transport/engine.py`
with a deterministic peak-selection policy (two rules), implemented in both the
engine and `experiments/transport/stable_reference.py`. The equations and known
weaknesses of the method are documented in
`experiments/transport/ENGINE_NOTES.md`; the measured defects are in
`experiments/transport/FINDINGS.md`.

The contract below is normative. The design and limits sections describe the
code at `src/Engine.cpp` and are kept in step with it.

## Public contract

`pitchwing::Engine` is movable, noncopyable, and owns its state through a
`std::unique_ptr` to a private implementation. Prepare it outside the audio
callback: construction validates settings, allocates buffers, builds windows,
and prepares the FFT, and may throw `std::invalid_argument` or an allocation
exception. Every processing and lifecycle operation returns `pitchwing::Status`
and is `noexcept`. An instance has no internal synchronization; the caller
owns exclusive access.

### Configuration

The defaults in `EngineConfig` are 48 kHz, $N = 2048$ (analysis size),
$L = 384$ (synthesis size), $H = 96$ (hop), zero semitones, asymmetric window.
Construction rejects a configuration unless:

- $65536 \ge N \ge L \ge 8$, with $N$ and $L$ even;
- $H$ divides $L$ and $H \le L/2$ (at least two overlaps);
- the sample rate is finite and positive;
- the pitch is finite and within $[-12, 12]$ semitones;
- the window enum is valid, and symmetric mode has $N = L$ (its matched
  baseline is $384/384/96$).

These checks run before any FFT allocation (`src/Engine.cpp`,
`validateConfig`). The size limit bounds storage, not callback time: a large or
poorly factorized FFT size can be expensive. The engine does not resample or
scale sizes with sample rate; equal millisecond settings at another rate need
caller-selected sizes.

`config()` returns a copy, so a caller cannot mutate prepared sizes or
windows. The returned pitch reflects the last successful `setPitchSemitones`.

### Operations

| Operation | Behavior |
|---|---|
| `process(input, output, count)` | Accepts float or double and writes exactly `count` samples to the caller's buffer. |
| Zero-count `process` | Returns `Ok`, accepts null pointers, and neither starts nor advances an open stream. A closed stream still returns `StreamClosed`. |
| Nonempty buffers | Must be valid live arrays of at least `count` samples. Exact in-place use (`input == output`) is accepted. A null pointer, an address range that overflows, or partial input/output overlap returns `InvalidBuffer`. |
| Sample validation | Every input sample must be finite with absolute value at most $10^{100}$; otherwise `process` returns `InvalidSample`. |
| Validation failure | Leaves processing state and the output buffer untouched. No prefix of the block is processed. |
| `latencySamples()` | Returns $L - 1$: 383 samples, about 7.979 ms at 48 kHz. |
| `tailSamples()` | Returns $N + L - 1 + H$: 2527 samples at the defaults. |
| First `flush(output, capacity, written)` | Requires `capacity >= tailSamples()`, writes the whole zero-fed tail, sets `written`, and closes the stream. This holds for a stream that never received input. |
| Failed `flush` | Sets `written = 0` and leaves output and state untouched. Insufficient capacity returns `BufferTooSmall`; otherwise an invalid buffer returns `InvalidBuffer`. |
| Later `flush` | Returns `Ok` with `written = 0`; a null output and zero capacity are accepted. |
| `process` after `flush` | Returns `StreamClosed` until `reset`, including zero-count calls. |
| `reset()` | Returns `Ok`, clears stream, phase, and scheduler state, reopens the stream, and keeps configuration and pitch. It allocates nothing. |
| `setPitchSemitones(value)` | Returns `InvalidPitch` for a nonfinite or out-of-range value. A changed value after nonempty processing, or after `flush`, returns `PitchLocked`. The current value always returns `Ok` on a prepared instance. `reset` re-enables changes. |
| Moved-from instance | Status-returning operations return `NotPrepared`; `flush` sets `written = 0`; `latencySamples` and `tailSamples` return 0; `config()` returns default settings. Destruction and move assignment stay valid. |

The engine applies no gain adjustment or clipping. Float input is widened to
double internally and narrowed on output, so a very large finite float input
can overflow float output after coherent gain changes; keeping the output in
float range is the caller's responsibility. Buffer validation cannot prove that
a nonnull address names accessible storage: callers supply valid arrays.

## Design

### FFT and normalization

The engine uses `signalsmith::linear::SplitFFT<double>` from the bundled MIT
header `third_party/signalsmith-linear/fft.h` through the private include
`<signalsmith-linear/fft.h>`. The header and its license are copied unchanged
from the research checkpoint; see `third_party/README.md` for the pinned
commit. The dependency supplies only the FFT, not pitch-shifting logic.

Forward and inverse transforms run on preallocated complex-double buffers. The
inverse transform is unnormalized, so the engine multiplies every inverse
result by $1/N$ (`inverseN` in `src/Engine.cpp`), matching NumPy's `irfft`.
At a pitch ratio of exactly 1 the frame is reconstructed from its positive
half-spectrum without transport, which is what the unity tests measure.

The native FFT and summation order differ from NumPy, so numerical equality
with the Python reference is approximate. The parity harness in
[native validation](native-validation.md) records any failure above its
$10^{-10}$ bound rather than loosening the bound.

### Scheduler

The scheduler stores only ring positions and a bounded hop phase. It computes
a frame at input indices $0, H, 2H, \dots$ before emitting the corresponding
sample, and adds each synthesis contribution to a length-$L$ output ring with
delay $D = L - 1$. Independent bounded positions avoid an ever-growing sample
index and accept arbitrary caller block boundaries without an extra FIFO.

### Allocation

All history, output, magnitude, peak, region, FFT, and modulation scratch
storage is allocated in the `Impl` constructor. Region inverse transforms run
one at a time through shared scratch instead of a region-by-FFT matrix.
`reset`, `process`, `flush`, and `setPitchSemitones` contain no allocation,
locks, filesystem access, FFT preparation, or container growth. Move and
destruction manage ownership and belong outside the audio callback.
`tests/engine_tests.cpp` (`testNoAllocationsAfterPreparation`) counts global
`new` and `new[]`, including aligned forms, from the first callback onward; it
does not intercept direct `malloc`.

### Transport rules retained from the reference

The engine keeps the reference method's rules (`src/Engine.cpp`,
`findRegions` and `transport`):

- at most 64 regions, and a relative peak floor of $10^{-4}$ of the largest
  interior magnitude;
- a parabolic log-magnitude bin estimate, replaced by the phase-difference
  estimate when the previous magnitude at that bin exceeds $10^{-6}$ of the
  largest, the instantaneous frequency lies in $(0, \pi)$, and it is within two
  bin widths of the parabolic estimate;
- ungated nearest-ancestor phase inheritance from the previous frame's
  regions, with rotation $\rho = \rho_a + \tfrac{H}{2}(\delta_a + \delta)$
  wrapped to $[-\pi, \pi)$;
- modulation referenced to the frame end, with angle
  $\theta_q = \rho + \delta\,(q - (L - 1))$ at synthesis offset $q$;
- rigid translation of each region by $\delta = (r - 1)\,\omega$, where $r$ is
  the pitch ratio and $\omega$ the estimated region frequency;
- DC bin retained, Nyquist bin omitted, a raised-cosine taper over the two bins
  below Nyquist, and destinations outside $(0, \pi)$ dropped without a
  low-frequency taper.

If no interior local maximum passes the peak floor, the largest interior bin
becomes the single region. No onset handling, stereo, automation, tracking
confidence, normalization, or new DC treatment is added.

### Deterministic flat-spectrum peak selection

When the interior magnitudes (bins $1$ to $N/2 - 1$) satisfy

$$
\max - \min \le 10^{-12} \cdot \max ,
$$

the engine selects one canonical peak at bin 1. A zero spectrum still yields no
regions. The code uses the subtraction-and-product form above rather than a
division, so a zero maximum never divides. Frequency bootstrap, the
phase-difference gate, and ancestor integration are unchanged. At the 64-peak
cap, candidates are ordered by magnitude and then bin index, keeping the 64
largest; equal magnitudes at the cutoff favor the higher bin.
`experiments/transport/stable_reference.py` applies the same two rules on top
of the untouched `engine.py`. This is a peak-selection policy, not a new pitch
estimator: a flat spectrum contains no localized frequency peak.

The rule exists because the literal port failed every shifted parity case
while passing unity. At a frame boundary the first nonzero sample alone forms a
windowed impulse whose interior magnitudes are mathematically equal, and FFT
rounding then made the local-maximum detector pick unrelated peaks that seeded
persistent ancestor phases. Removing the ambiguous frame removed the error;
delaying the onset by exactly one hop recreated it. The failing report is
[initial parity](results/2026-10-08-native-parity-initial.json) and the 30
diagnostic probes are [startup probes](results/2026-10-08-startup-probes.json);
[native validation results](native-validation-results.md) tabulates them.

The fix changes the spectral decision inside the engine. It does not zero the
first sample, prepend audio, add latency, or alter input. The original Python
engine and the accepted listening renders are unchanged, so the native output
can differ audibly from the accepted baseline at attacks and needs its own
listening comparison.

### Modulation arithmetic

The transport loop evaluates the modulation phase exactly at synthesis offsets
$q = 0, 64, 128, \dots$ and multiplies by $s = e^{\,j\delta}$ between anchors.
At $L = 384$ this costs seven sine/cosine pairs per region instead of 384: one
for $s$ and six anchors. No recurrence crosses a region or frame, and at most
63 recurrence steps separate direct evaluations, which bounds local roundoff.

The upper alias taper is $0$ for destinations outside $(0, \pi)$, $1$ for
destinations at or below $\pi - g$ with guard $g = 2 \cdot 2\pi/N$, and the
raised cosine

$$
t = \tfrac{1}{2} - \tfrac{1}{2}\cos\!\left(\pi\,\frac{\pi - d}{g}\right)
$$

only for a destination $d$ inside the two-bin transition. These are the
constant parts of the existing rule, not a new band limit. Region selection
and every persistent phase update are unchanged by either shortcut; the
measured throughput effect is in [native validation
results](native-validation-results.md).

## Known limits

The port keeps the measured DSP defects of the reference. Retaining DFT bin
zero does not preserve a constant waveform when the other window-spectrum bins
move. One rigid region cannot scale an unresolved dyad's spacing. Ancestor
history, region reassignment, boundary truncation, and coherent collisions can
affect attacks, gain, and low-note behavior. Scheduled delay is distinct from
settling time. Parity with the reference proves preservation of the baseline,
not correction of these problems or support below F#1.

The engine is mono and static ratio. Target-native callback deadlines,
sample-rate coverage, stereo, smooth parameter automation, and objective or
listening quality gates remain open. WSL test and timing results are not
target-native real-time evidence.
