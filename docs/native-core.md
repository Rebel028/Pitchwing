# Native engine core

Date: 2026-10-08. First C++ implementation of the existing mono static-ratio
experiment. The user explicitly requested the native engine now, superseding
the earlier sequencing proposal to resolve all synthetic DSP defects before
porting. This changes implementation order, not the evidence about quality.
The current deliverable is a reusable library, with no VST wrapper or integration.

`include/pitchwing/Engine.hpp` defines the public interface. `src/Engine.cpp`
contains implementation and private preallocated state. The numerical design
follows `experiments/transport/engine.py`; its equations and known weaknesses
remain documented in `experiments/transport/ENGINE_NOTES.md`. Initial direct
parity exposed an unstable flat-spectrum peak decision, described below. The
native engine now follows `experiments/transport/stable_reference.py`, a small
explicit variant that leaves the original Python file and accepted renders
unchanged. Other DSP mechanisms remain the same.

## Public contract

`pitchwing::Engine` is movable, noncopyable, and owns its private implementation
through `std::unique_ptr`. Prepare it outside audio processing. Construction
validates settings, allocates buffers, builds windows, and prepares the FFT;
it may throw `std::invalid_argument`, or standard allocation exceptions.
The processing/lifecycle interface returns `pitchwing::Status` and is `noexcept`.
Instances require exclusive caller access; there is no internal synchronization.

Defaults are 48 kHz, `N=2048`, `L=384`, `H=96`, zero semitones, asymmetric window.
The explicit native preparation limit is `65536 >= N >= L >= 8`, both sizes even;
`H` must divide `L` with at least two overlaps. Sample rate must be finite and
positive, pitch finite within `[-12, 12]`, and the window enum valid. Symmetric
mode requires `N == L`; its matched baseline uses `384/384/96`. These checks
precede FFT allocation, preventing overflow and accidental astronomical sizes.
The limit bounds storage, not callback time: large or poorly factorized FFT sizes
can be expensive. Equal millisecond settings at another sample rate require
caller-selected corresponding sizes; the engine does not resample or auto-scale.

`config()` returns a copy, so callers cannot mutate prepared sizes/windows.
The returned pitch reflects a successful `setPitchSemitones` call.

| Operation | Behavior |
|---|---|
| `process(input, output, count)` | Supports float or double, returns exactly `count` samples in the caller's buffer. |
| Zero-count `process` | Accepts null pointers, does not start or advance an open stream. A closed stream still returns `StreamClosed`. |
| Nonempty buffers | Must reference valid live arrays of sufficient length. Exact in-place use is accepted. Null, overflowing address ranges, and partial input/output overlap return `InvalidBuffer`. |
| Sample validation | Checks the whole block for finite samples with absolute value at most `1e100`; otherwise returns `InvalidSample`. |
| Validation failure | Leaves processing state and sample output untouched. No prefix is processed. |
| `latencySamples()` | Returns `L-1`, 383 samples or approximately 7.979 ms at the default rate. |
| `tailSamples()` | Returns `N+L-1+H`, 2527 samples by default. |
| First `flush(output, capacity, written)` | Requires capacity at least `tailSamples()`, writes that entire zero-fed tail, sets `written`, and closes the stream, including for an initially empty stream. |
| Failed `flush` | Sets `written=0`, leaves sample output/state untouched; insufficient capacity returns `BufferTooSmall`, otherwise an invalid buffer returns `InvalidBuffer`. |
| Subsequent `flush` | Returns `Ok` with `written=0`; permits a null output and zero capacity. |
| `process` after flush | Returns `StreamClosed` until reset, including zero-count calls. |
| `reset()` | Returns `Ok`, clears stream/phase/scheduler state, reopens the stream, and retains configuration/pitch without allocating. |
| `setPitchSemitones(value)` | Rejects nonfinite/out-of-range values with `InvalidPitch`; changed values after nonempty processing or closure return `PitchLocked`. Identical values are always `Ok` for a prepared instance. Reset re-enables changes. |
| Moved-from instance | Status-returning operations return `NotPrepared`; flush writes `written=0`; delay/tail return zero and `config()` returns default settings. Destruction and move assignment remain valid. |

There is no hidden gain adjustment or clipping. Float samples are converted to
double internally and narrowed on output. Extremely large finite float inputs
can overflow float output after coherent gain changes; keeping the output in
float range is the caller's responsibility. This preserves the requested common
input bound and baseline gain behavior. Normal audio is far below this limit.
Likewise, buffer validation cannot establish that an arbitrary nonnull address
really names accessible storage: callers must supply valid arrays.

## Numerical parity and preparation

The implementation uses the bundled MIT Signalsmith Linear
`signalsmith::linear::SplitFFT<double>` through the private include
`<signalsmith-linear/fft.h>`. Its license is preserved by the parent task in
`third_party/signalsmith-linear/LICENSE.txt`. This is an FFT dependency, not borrowed
pitch-shifting logic. C++17 supports the installed GCC 9.4 toolchain without new
packages; the requested cpp-pro skill's RAII/memory guidance is applied, while
its C++20 concepts guidance is inapplicable to this explicitly C++17 API.

Forward/inverse transforms operate on preallocated complex-double buffers.
Signalsmith inverse transforms are unnormalized: the port divides every inverse
result by `N`, matching NumPy. A tiny independent impulse check measured raw
round-trip gains of exactly 384 and 2048 for the two baseline sizes; dividing by
`N` produced zero reported impulse reconstruction residual in that check.
This checks normalization, not arbitrary-spectrum numerical parity.

The scheduler stores only ring positions and a bounded hop phase. It computes
frames at input indices `0,H,2H,...` before emitting the corresponding sample.
It adds each recent synthesis contribution to the output ring with `D=L-1`.
Independent bounded positions avoid an ever-growing sample index and preserve
arbitrary caller block boundaries without an extra FIFO.

All history, output, magnitude, peak, region, FFT, and modulation scratch storage
is allocated during construction. Region inverse transforms run sequentially
through shared scratch instead of allocating Python's region-by-FFT matrix.
`reset`, `process`, `flush`, and pitch setting contain no allocation, locks,
filesystem access, FFT preparation, or container growth. Move/destruction manage
ownership and should also occur outside the audio callback. The parent task owns
allocation-guard tests and sanitizer runs; this description is not a deadline
measurement.

Algorithm details preserved from the original reference include the 64-region cap and
`1e-4` relative peak floor, phase-difference frequency estimate with the same
sanity gate, ungated nearest-ancestor phase inheritance, frame-end modulation,
rigid translation of each region, explicit DC-bin retention, Nyquist omission,
and the upper two-bin taper. Lower nonpositive destinations are discarded
without a low-frequency taper. No onsets, stereo, automation, extra tracking
confidence, normalization, or new DC treatment are added.

The explicit native/stable-reference change is this: when positive interior
magnitudes have relative spread `(maximum-minimum)/maximum <= 1e-12`, choose
one canonical peak at bin 1. A zero spectrum still produces no regions. The
code uses the equivalent subtraction/product comparison without dividing by
zero. Frequency bootstrap, phase-difference gates, and ancestor integration
remain unchanged. At the 64-peak cap the stable reference sorts by magnitude,
then bin index, matching the native deterministic tie rule. This is not a new
pitch estimator; a flat spectrum contains no localized frequency peak.

The native FFT and summation order differ from NumPy, so numerical equality is
approximate. NumPy's original argsort tie behavior was not a stable cross-runtime
contract; the new stable reference and native selector both favor higher bin
indices for equal magnitudes at the cutoff. Record remaining parity failures
rather than loosening tolerances to conceal material differences.

## Diagnosed startup parity failure

The initial direct port passed all six unity comparisons at maximum errors
around `3e-16`, but all shifted cases failed materially: the full comparison
reported asymmetric E1 error `0.414368`, B0/C1 error `0.780470`, A4 error
`0.0657946`, and the preferred recording error `0.812590`. Block size did not
change these differences. This was a real behavioral difference, not a reason
to relax the `1e-10` parity limit.

At a frame boundary, the first nonzero sample alone creates a windowed impulse.
Its spectral magnitudes are mathematically equal. FFT rounding made the original
local-maximum detector choose unrelated sets of peaks; those seeded different
nearest-ancestor phase histories that persisted after startup. Removing the
ambiguous frame eliminated the error to ordinary floating-point scale in 30
short in-memory/scratch probes. Delaying the onset by exactly one hop recreated
the failure, distinguishing the cause from a general modulation sign or FFT
normalization bug.

Each probe used `x[n]=0.3*sin(2*pi*f*n/48000+0.23)` for `0 <= n < 4096`, hop 96,
L384, the existing release runner, and the original Python reference. Compare
the complete process-plus-flush output at the shifts/windows below:

| f / shift / window | Original max error | Set only x[0]=0 | Prepend one zero |
|---|---:|---:|---:|
| 440 Hz / -1 / asymmetric | 0.0657946 | 2.01e-15 | 4.26e-15 |
| 440 Hz / -1 / symmetric | 0.0293861 | 3.43e-15 | 3.30e-15 |
| 41.203445 Hz / -7 / asymmetric | 0.0920660 | 6.45e-16 | 7.41e-16 |
| 41.203445 Hz / -7 / symmetric | 0.0550446 | 4.40e-15 | 1.78e-15 |
| 750 Hz / +12 / asymmetric | 0.690337 | 7.05e-15 | 4.95e-15 |
| 750 Hz / +12 / symmetric | 0.568743 | 2.40e-15 | 7.95e-15 |

For every row, prepending 96 zeros reproduced the original maximum error;
prepending 97 zeros matched the one-zero result. These five variants across six
rows are the 30-probe recipe. Raw scratch stayed under `/tmp`; the parent task
persists the compact full probe/initial-parity reports with its development
record. These smaller E1 probes use phase 0.23, unlike the full harness E1 phase
0.31, which explains their different failing error magnitudes.

The fix handles the spectral decision inside the engine. It does not zero the
first real sample, prepend audio, add latency, or alter the input. The original
Python and listening files remain available as the accepted baseline; the
native/stable variant can have a different attack/phase history and requires
an explicit new listening comparison. Parent-owned tests compare the stable
variant without silently treating the original-reference change as parity.

## Bounded transport-loop optimization

After the deterministic variant passed all 30 parent-owned parity cases at the
unchanged `1e-10` maximum-absolute threshold, two local arithmetic optimizations
were applied. Region selection and every persistent phase/state update remain
unchanged; the original and stable Python references remain unchanged.

For each region, compute `step=exp(j*delta)` once. Evaluate the exact modulation
phase at synthesis offsets `q=0,64,128,...`, then multiply by `step` between
anchors. At L384 this uses seven sine/cosine pairs per region instead of 384:
one step plus six anchors. No recurrence crosses a region or frame, and at most
63 recurrence steps contribute between direct evaluations. This bounds local
roundoff accumulation while preserving the same intended phase equation.

The upper alias taper returns zero directly for destinations outside `(0,pi)`
and one directly for destinations at or below `pi-guard`. It evaluates a cosine
only within the two-bin transition below Nyquist. These are the constant portions
of the existing raised-cosine rule, not new gain or band-limit policies.

The optimization targets repeated transcendental evaluations; only parent-owned
post-change parity, sanitizer, and timing results establish its actual effect.
No build or experiment was duplicated by the implementation agent. In particular,
fewer arithmetic calls alone do not establish a native callback deadline or
correct the documented DSP quality failures.

## Validation ownership and known limits

The implementation agent compiled `src/Engine.cpp` with GCC, C++17,
`-Wall -Wextra -Wpedantic`, and the FFT dependency as a system include, with no
reported warnings. Its only independent numerical run was the tiny normalization
check above. The parent integrates the separate workers' CMake/tests/runner and
owns complete native tests, allocation checks, ASan/UBSan, and Python parity
results. See the current entry in `../DEVELOPMENT.md` and linked run artifacts for
the resulting evidence; pending checks must not be interpreted as passed.

A subsequent read-only contract review of `CMakeLists.txt`,
`tests/engine_tests.cpp`, and `tools/pitchwing_render.cpp` found no blocking API or
state mismatch. Tests exercise both partial-overlap directions, atomic invalid
blocks, exact in-place processing, active-stream reset, moves, complete tails,
and allocation counting from the first callback. The allocation probe catches
global new/new[] including aligned forms, not arbitrary direct malloc calls;
it is a regression check rather than universal runtime instrumentation. The
offline runner checks process/flush statuses and finite output and separates
preparation/warmup/I/O/flush from its explicitly limited WSL process timing.
Review of `scripts/compare_native.py` also confirmed complete-output/tail and
declared-delay comparisons, reference reuse across native block sizes, and a
single bounded preferred-recording read. The harness does not silently relax
its parity threshold when numerical or tracker differences appear.

The port retains the measured/identified DSP defects. Keeping DFT bin zero does
not preserve a constant waveform when other window-spectrum bins move. One rigid
region cannot scale an unresolved dyad's spacing. Historical evidence, region
reassignment, boundary truncation, and coherent collisions can affect attacks,
gain, and low-note behavior. Scheduled delay is distinct from settling time.
Successful parity proves preservation of the baseline, not correction of these
problems or guaranteed support below F#1.

The engine is mono and static ratio. Native target callback deadlines, sample-rate
coverage, stereo, smooth parameter automation, and objective/listening quality
gates remain work. WSL test or timing results are not target-native real-time
performance evidence. Preserve the accepted listening baseline and change DSP
mechanisms separately, with explicit before/after measurements and listening.
