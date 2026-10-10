# Live engine validation for ShiftKey

2026-10-09. Scope: reusable engine changes after inspecting the separate
ShiftKey consumer. No VST, JUCE dependency, source-audio copy, or external tool
installation is part of this task. Builds and disposable outputs use `/tmp`.

## Contracts and consumer packaging

Release CTest passes both executables: 9 original static-engine groups and 11
new live groups, 3.62 seconds total in the recorded run. The
[full test output](results/2026-10-09-live-release-tests.txt) is retained.
Live checks cover:

- 44.1/48/96 kHz exact delayed unity, sample/hop phases and tail boundaries;
- fractional ±49 targets and command/block partition equivalence;
- one-sample sub-hop commands, sustained unity reacquisition;
- stereo swap, dual mono, anti-phase, silent channels and duplicated input;
- float/double parity, exact in-place and transactional invalid-input rejection;
- reset, moves, terminal drain and first/runtime C++ allocation checks.

The allocation probe replaces ordinary and aligned C++ new/delete. It is not
malloc instrumentation or a proof about another platform's runtime. A source
review also checked that processing performs no container growth or FFT planning.

The standalone `tests/consumer` builds and passes in both source and installed
modes, linking the static engine into a shared library and then an executable.
This verifies PIC, dependency propagation, headers, API use, embedded defaults,
and exported package consumption on Linux. The install was a staging operation
under `/tmp/pitchwing-stage`, not an external package installation. No Windows
MSVC build or REAPER/pluginval run was performed. The bundled FFT's MIT notice
is installed; no separate Pitchwing-owned license was found, so the FFT notice
must not be presented as licensing the entire project.

Review found one numeric contract defect before completion: a double input up
to 1e100 could later overflow float output through retained history. Both input
overloads now share the conservative 1e30 bound, validated before state changes.
The new mixed-precision regression exercises actual large delayed samples in
float process and flush at unity, -7 and ±49, comparing with a double reference.

Two initial release test attempts used a stale 10-group object compiled while
the test agent was updating it. Its old 1e100 acceptance assertion failed after
the core bound changed. The object timestamp was later than the edited source,
so ordinary rebuilding did not recompile it. Removing only that task-owned
object and rebuilding produced the current passing 11-group suite. Finish file
edits before compiling their targets; do not reinterpret this stale assertion
as a current engine failure.

## Sanitizers and environment

GCC 9.4, CMake 3.31.10, Intel i9-10900KF, WSL2 Linux 6.6.87.2. Build flags and
source hashes are in [the environment record](results/2026-10-09-live-environment.json).
Warning-enabled release and sanitizer builds produced no compiler warnings.

The new live suite passes all 11 groups with ASan+UBSan at `-O1 -g`, fatal
diagnostics, leak detection disabled and bounded quarantine:
[output](results/2026-10-09-live-sanitizer-tests.txt). A previous unoptimized
Debug live run reached nine groups without a diagnostic, then hit its 60-second
cap; that incomplete run was not a pass.

The original static suite also passes 9/9 under address/UB instrumentation, but
required `ASAN_OPTIONS=...:handle_segv=0`:
[exact command/output](results/2026-10-09-static-sanitizer-final.txt). Prior runs
with the default ASan SIGSEGV handler repeatedly printed `DEADLYSIGNAL`, both
with redirected output (60-second timeout) and in a terminal (interrupted).
The [failed-run excerpt](results/2026-10-09-static-sanitizer-failure.json)
preserves the symptom and metadata; no cause or engine defect is established.
The redirected loop produced a 1056285420-byte `/tmp` log, removed after saving
bounded excerpts. Future diagnostic captures should cap output as well as time.
No such log was written to the mounted project drive. Allocation replacement
code is identical in the static/live suites; lack of early PASS output did not
prove a startup failure because the first static group contains 384 render/drain
loops. Disabling the SIGSEGV handler retains compiler address/UB checks and fatal
diagnostics, but removes ASan's handler for raw segmentation faults. Leak
checking remains unvalidated in this tracing environment.

```sh
/tmp/pitchwing-env/bin/cmake -S . -B /tmp/pitchwing-live-sanitize -DCMAKE_BUILD_TYPE=RelWithDebInfo '-DCMAKE_CXX_FLAGS_RELWITHDEBINFO=-O1 -g -DNDEBUG' -DPITCHWING_BUILD_TOOLS=OFF -DPITCHWING_ENABLE_ASAN=ON -DPITCHWING_ENABLE_UBSAN=ON
/tmp/pitchwing-env/bin/cmake --build /tmp/pitchwing-live-sanitize -j 2
timeout 60s env ASAN_OPTIONS=detect_leaks=0:halt_on_error=1:quarantine_size_mb=16:thread_local_quarantine_size_kb=64 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 /tmp/pitchwing-live-sanitize/pitchwing_live_tests
```

## Bounded synthesis optimization

Preweight each region's cached modulation by synthesis-window/inverse-FFT
normalization once, then reuse it for both channels with an explicit real dot
product. This reduces repeated arithmetic without changing the spectral
algorithm, scheduler, or control integration. The
[comparison source](results/2026-10-09-live-optimization-probe.cpp) renders 24000
frames of differing-channel tones and 32-sample pitch updates at each of
44.1/48/96 kHz. Across 144000 double output samples, before/after maximum error
is 1.1102230246251565e-16 and RMS error is 1.7924876222892854e-17; all are finite.
This is a local arithmetic-regression comparison, not parity with the original
mono engine or a quality judgment.

The original timing report is retained as
[initial timing](results/2026-10-09-live-timing-initial.json). Its final partial
block is included in each nominal-block aggregate; later review corrected the
probe to exclude that partial block. In particular a 44.1 kHz nominal 32-sample
case ended with two samples. Treat comparisons with the corrected final report
as diagnostics, not a controlled speedup claim.

## Final callback timing

[Final raw timing](results/2026-10-09-live-timing-final.json) uses two distinct
synthetic low-register chords: the left fundamentals are
38.89/58.27/77.78/92.50 Hz, while the right multiplies those frequencies by 1.003
and uses different harmonic phases. Both have twelve harmonics per note.
For each case, prepare, warm up for 0.25 seconds,
then measure 0.5 seconds. The table selects the automated 32-sample cases;
control follows -7 + 9 sin(2π·7t) semitones, updated at each internal chunk.
Time includes setters, validation and stereo processing. Builds/tests/probes
were not run concurrently with this measurement.

| Sample rate | Audio delay | Block budget, µs | Mean / p95 / max, µs | Exceedances / full blocks |
| --- | ---: | ---: | ---: | ---: |
| 44.1 kHz | 439 (9.955 ms) | 725.62 | 176.5 / 233.6 / 323.6 | 0 / 689 |
| 48 kHz | 479 (9.979 ms) | 666.67 | 152.9 / 200.2 / 290.7 | 0 / 750 |
| 96 kHz | 959 (9.990 ms) | 333.33 | 158.3 / 217.0 / 348.6 | 1 / 1500 |

All measured 32/64/128 cases at 44.1 and 48 kHz have zero exceedances. At 96 kHz,
the static -7, 64-sample case also exceeds budget in 3/750 calls (max 772.6 µs
against 666.7 µs). Preserve these outliers; their cause is not isolated. The
optimization's timing benefit is not established by these short sequential
runs, despite its small verified numerical effect.

One-sample calls exceed hypothetical single-sample budgets repeatedly due to
analysis/IFFT bursts. Those are diagnostics, not observed DAW underruns:
ShiftKey's small internal chunks share the surrounding host callback budget.
The 32/64/128 cases time each entire block with its internal subdivisions.
Final partial blocks are excluded from nominal-block aggregates. WSL scheduling,
short observation periods and synthetic inputs prevent any hard deadline or
Windows-native performance guarantee; denser spectra may cost more.

## Pitch-control clock measurement

`pitchwing_live_probe steps` follows ShiftKey's old/new-frequency amplitude-share
metric: 220 Hz dual mono at 48 kHz, two seconds of settling, exact sample event
splits in calls of at most 32 samples, centered 1024-point periodic Hann DFT,
eight-sample scan with interpolated crossings. Twelve event phases, 0..88 by 8,
cover a subset of the 96-sample hop. All 48 cases start below 10% new-frequency
share, end above 90%, and have ordered t10/t50/t90 crossings. The offset is
`t50 - actualEventSample - latencySamples()`, with audio latency 479.

| Step (semitones) | Mean offset, samples | Min / max, samples | Mean measured t10–t90, samples |
| --- | ---: | ---: | ---: |
| 0 → +12 | -0.878 | -2.235 / 0.648 | 489.19 |
| 0 → -12 | 1.232 | -0.861 / 3.692 | 493.98 |
| +12 → 0 | 46.082 | -1.312 / 131.625 | 493.37 |
| -12 → 0 | 8.155 | -2.738 / 25.424 | 558.53 |

The near-zero outgoing offsets support **provisional `clockDelay48k = 0`** for
an initial ShiftKey trial. Do not derive one universal constant by averaging all
directions. Return-to-unity variation reaches 131.625 samples (2.742 ms) in this
set. Audio latency and curve-clock compensation are separate quantities.

These are first crossings of amplitude share, not energy fraction or proof of
settling. Deep level dips can affect the ratio. The 1024-sample window spans
21.33 ms and smears the measured transition width; the width is not an isolated
engine delay. Interpolation does not establish fractional-sample accuracy.
Real low guitar, other intervals/rates, all hop phases and listening still need
evaluation. Saved initial results precede the arithmetic optimization; final
results have the same reported crossing values and explicit validity fields.
See [final step results](results/2026-10-09-live-steps-final.json) and the
[initial report](results/2026-10-09-live-steps-initial.json).

## Reproduction

Use the already approved temporary CMake tools. No command fetches dependencies.

```sh
/tmp/pitchwing-env/bin/cmake -S . -B /tmp/pitchwing-live-release -DCMAKE_BUILD_TYPE=Release -DPITCHWING_BUILD_TESTS=ON
/tmp/pitchwing-env/bin/cmake --build /tmp/pitchwing-live-release -j 2
/tmp/pitchwing-env/bin/ctest --test-dir /tmp/pitchwing-live-release --output-on-failure
/tmp/pitchwing-live-release/pitchwing_live_probe timing > /tmp/pitchwing-live-timing-final.json
/tmp/pitchwing-live-release/pitchwing_live_probe steps > /tmp/pitchwing-live-steps-final.json

/tmp/pitchwing-env/bin/cmake -S tests/consumer -B /tmp/pitchwing-consumer-source -DMODE=source -DCMAKE_BUILD_TYPE=Release
/tmp/pitchwing-env/bin/cmake --build /tmp/pitchwing-consumer-source -j 2
/tmp/pitchwing-env/bin/ctest --test-dir /tmp/pitchwing-consumer-source --output-on-failure
/tmp/pitchwing-env/bin/cmake --install /tmp/pitchwing-live-release --prefix /tmp/pitchwing-stage
/tmp/pitchwing-env/bin/cmake -S tests/consumer -B /tmp/pitchwing-consumer-installed -DMODE=installed -DCMAKE_PREFIX_PATH=/tmp/pitchwing-stage -DCMAKE_BUILD_TYPE=Release
/tmp/pitchwing-env/bin/cmake --build /tmp/pitchwing-consumer-installed -j 2
/tmp/pitchwing-env/bin/ctest --test-dir /tmp/pitchwing-consumer-installed --output-on-failure
```

Use a fresh build directory if the earlier tools-only cache has tests disabled.
Do not run benchmarks concurrently with builds, tests, or other DSP probes.
Waveform comparison uses the saved standalone source linked against the two
library builds; generated binary sample streams remain in `/tmp` only.

## Readiness limits

The API covers ShiftKey's control envelope, channel contract and CMake use.
Acceptance of ±49 is not established extreme-shift sound quality. Linked stereo
and sample-integrated controls change DSP behavior relative to prior listening
renders. Unity reacquisition can produce phase/gain dips, and frame-end Nyquist
guarding does not prove suppression of aliases during short upward excursions.
Known shifted DC and low-dyad defects persist. No formant preservation or quality
selector is supplied. Below-F#1 real-input coverage and bass support remain open.
Windows/DAW deadline validation and listening are required before production use.
