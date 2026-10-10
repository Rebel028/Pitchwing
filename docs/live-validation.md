# Live engine validation

`LiveEngine` passes its contract tests in release and sanitizer builds on
Linux, keeps its 32 to 128 sample callbacks inside budget at 44.1 and 48 kHz
in a WSL probe, and starts an octave step within one hop of the commanded
sample. Windows, DAW, and listening validation are still open. This document
records the measurements, links the result files, and lists the commands that
produced them. The contract and the design behind the numbers are in
[the live engine design](live-engine.md); the consumer's view is in
[ShiftKey integration](shiftkey-integration.md).

Everything here was built and run under `/tmp` in WSL2 with the environment in
[the environment record](results/2026-10-09-live-environment.json): GCC 9.4,
CMake 3.31.10, Intel i9-10900KF, Linux 6.6.87.2. No VST, JUCE dependency,
or external tool installation was part of any run. A WSL timing is a
diagnostic, never a target-native real-time result.

## Contract tests and consumer packaging

Release CTest passes both test executables, 9 static-engine groups and 11 live
groups, in 3.62 s ([test output](results/2026-10-09-live-release-tests.txt)).
The live groups (`tests/live_engine_tests.cpp:245-661`) cover:

- 44.1, 48, and 96 kHz exact delayed unity, sample and hop phases, tail
  boundaries;
- fractional $\pm 49$ targets and command/block partition equivalence;
- one-sample sub-hop commands and sustained unity reacquisition;
- stereo swap, dual mono, anti-phase, silent channels, duplicated input;
- float/double parity, exact in-place processing, transactional rejection of
  invalid input;
- the shared $10^{30}$ sample bound: large delayed samples through float
  `process` and `flush` at unity, -7, and $\pm 49$ against a double reference
  (`testPrecisionChangesAtCommonBound`);
- reset, moves, terminal drain, and first-call plus runtime allocation checks.

The allocation probe replaces the ordinary and aligned C++ `new` and `delete`
operators. It is not malloc instrumentation and proves nothing about another
platform's runtime; a source review also checked that processing performs no
container growth or FFT planning.

The standalone [`tests/consumer`](../tests/consumer/CMakeLists.txt) project
builds and passes in both `MODE=source` and `MODE=installed`, linking the
static engine into a shared library and then an executable. This checks
position-independent code, dependency propagation, headers, API use, embedded
defaults, and the exported CMake package on Linux. The install was a staging
step under `/tmp/pitchwing-stage`. No Windows MSVC build and no REAPER or
pluginval run exists. The bundled FFT's MIT notice is installed; Pitchwing has
no separate licence file, so the FFT notice must not be presented as the
project's licence.

## Sanitizer runs

Warning-enabled release and sanitizer builds produce no compiler warnings. The
live suite passes all 11 groups with ASan and UBSan at `-O1 -g`, fatal
diagnostics, leak detection disabled, and bounded quarantine
([output](results/2026-10-09-live-sanitizer-tests.txt)). An unoptimized Debug
run reached nine groups without a diagnostic and then hit its 60 s cap; that
incomplete run is not a pass.

The static suite passes 9 of 9 groups under the same instrumentation only with
`ASAN_OPTIONS=...:handle_segv=0`
([command and output](results/2026-10-09-static-sanitizer-final.txt)). With
the default ASan SIGSEGV handler the run repeatedly printed `DEADLYSIGNAL`,
both with redirected output (60 s timeout) and in a terminal (interrupted);
[the failed-run excerpt](results/2026-10-09-static-sanitizer-failure.json)
preserves the symptom and metadata, and no cause or engine defect is
established. The redirected loop wrote a 1056285420-byte log to `/tmp` before
it was removed, so a diagnostic capture needs an output cap as well as a time
cap. The first static group contains 384 render and drain loops, so missing
early `PASS` output does not prove a startup failure. Disabling the SIGSEGV
handler keeps the compiler's address and UB checks and fatal diagnostics but
removes ASan's handler for raw segmentation faults. Leak checking remains
unvalidated in this environment.

```sh
/tmp/pitchwing-env/bin/cmake -S . -B /tmp/pitchwing-live-sanitize -DCMAKE_BUILD_TYPE=RelWithDebInfo '-DCMAKE_CXX_FLAGS_RELWITHDEBINFO=-O1 -g -DNDEBUG' -DPITCHWING_BUILD_TOOLS=OFF -DPITCHWING_ENABLE_ASAN=ON -DPITCHWING_ENABLE_UBSAN=ON
/tmp/pitchwing-env/bin/cmake --build /tmp/pitchwing-live-sanitize -j 2
timeout 60s env ASAN_OPTIONS=detect_leaks=0:halt_on_error=1:quarantine_size_mb=16:thread_local_quarantine_size_kb=64 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 /tmp/pitchwing-live-sanitize/pitchwing_live_tests
```

## Arithmetic regression of the synthesis weighting

Preweighting each region's cached modulation by the synthesis-window and
inverse-FFT normalization once, and reusing it for both channels through an
explicit real dot product, changes floating-point association only. The
[comparison source](results/2026-10-09-live-optimization-probe.cpp) renders
24000 frames of differing-channel tones with 32-sample pitch updates at each
of 44.1, 48, and 96 kHz. Across 144000 double output samples the maximum error
between the two builds is $1.1102 \times 10^{-16}$ and the RMS error
$1.7925 \times 10^{-17}$; all samples are finite. This is a local arithmetic
check, not parity with the mono engine and not a quality judgement.

[The initial timing report](results/2026-10-09-live-timing-initial.json)
includes each case's final partial block in its nominal-block aggregate; at
44.1 kHz the nominal 32-sample case ended with a two-sample block. The final
report below excludes partial blocks, so a comparison between the two reports
is a diagnostic, not a controlled speedup claim.

## Callback timing

[The final timing report](results/2026-10-09-live-timing-final.json) uses two
distinct synthetic low-register chords: the left fundamentals are 38.89,
58.27, 77.78, and 92.50 Hz, the right multiplies them by 1.003 with different
harmonic phases, and each note has twelve harmonics. Each case prepares, warms
up for 0.25 s, then measures 0.5 s. The table shows the automated 32-sample
cases, whose control follows $-7 + 9 \sin(2\pi \cdot 7t)$ semitones updated
at each internal chunk. Time includes setters, validation, and stereo
processing; no build, test, or probe ran concurrently.

| Sample rate | Audio delay | Block budget, µs | Mean / p95 / max, µs | Exceedances / full blocks |
| --- | ---: | ---: | ---: | ---: |
| 44.1 kHz | 439 (9.955 ms) | 725.62 | 176.5 / 233.6 / 323.6 | 0 / 689 |
| 48 kHz | 479 (9.979 ms) | 666.67 | 152.9 / 200.2 / 290.7 | 0 / 750 |
| 96 kHz | 959 (9.990 ms) | 333.33 | 158.3 / 217.0 / 348.6 | 1 / 1500 |

All 32, 64, and 128 sample cases at 44.1 and 48 kHz have zero exceedances. At
96 kHz the static -7, 64-sample case exceeds its budget in 3 of 750 calls
(max 772.6 µs against 666.7 µs); the cause is not isolated and the outliers
are preserved. One-sample calls exceed a hypothetical single-sample budget
repeatedly because analysis and inverse transforms arrive in bursts; those
are diagnostics, not DAW underruns, since ShiftKey's internal chunks share the
surrounding host callback budget. Final partial blocks are excluded from the
aggregates.

That report measures the engine before the quality changes recorded in the
design document. [The current probe output](results/2026-10-10-timing-step12.txt)
on the same synthetic signal with automation off reports, per sample rate and
block size, mean / p95 / max in µs and misses: 44.1 kHz 32: 188 / 476 / 681,
0 of 689; 48 kHz 32: 165 / 362 / 406, 0 of 750; 96 kHz 32: 115 / 389 / 422,
223 of 1500; all 64 and 128 sample cases at every rate: 0 misses. The same
file records the real-material wall time of the 6.5 s guitar excerpt at block
64: 1.80 s. The 96 kHz small-block misses are a known open defect. WSL
scheduling, short observation windows, and synthetic input rule out any hard
deadline or Windows-native guarantee; denser spectra cost more.

## Pitch-control clock measurement

`pitchwing_live_probe steps` follows ShiftKey's old/new-frequency
amplitude-share metric: 220 Hz dual mono at 48 kHz, two seconds of settling,
exact sample event splits in calls of at most 32 samples, a centred
1024-point periodic Hann DFT, an eight-sample scan with interpolated
crossings. Twelve event phases, 0 to 88 by 8, cover a subset of the 96-sample
hop. All 48 cases start below 10 % new-frequency share, end above 90 %, and
have ordered $t_{10}$, $t_{50}$, $t_{90}$ crossings. The offset is

$$
\text{offset} = t_{50} - t_{\text{event}} - D ,
$$

with $D = 479$ the audio latency.

| Step (semitones) | Mean offset, samples | Min / max, samples | Mean measured $t_{10}$ to $t_{90}$, samples |
| --- | ---: | ---: | ---: |
| 0 to +12 | -0.878 | -2.235 / 0.648 | 489.19 |
| 0 to -12 | 1.232 | -0.861 / 3.692 | 493.98 |
| +12 to 0 | 46.082 | -1.312 / 131.625 | 493.37 |
| -12 to 0 | 8.155 | -2.738 / 25.424 | 558.53 |

The near-zero outgoing offsets support a provisional `clockDelay48k = 0` for
ShiftKey, which is the value the consumer currently carries (see
[ShiftKey integration](shiftkey-integration.md)). Averaging all directions
into one constant would hide the return-to-unity variation, which reaches
131.625 samples (2.742 ms) in this set. Audio latency and curve-clock
compensation are separate quantities.

These are first crossings of amplitude share, not energy fraction and not
proof of settling; deep level dips can move the ratio. The 1024-sample window
spans 21.33 ms and smears the measured transition width, so the width is not
an isolated engine delay, and interpolation does not establish
fractional-sample accuracy. Real low guitar, other intervals and rates, the
remaining hop phases, and listening are still unmeasured. Results:
[final](results/2026-10-09-live-steps-final.json) and
[initial](results/2026-10-09-live-steps-initial.json); both report the same
crossing values, and the final file adds explicit validity fields.

## Quality fixtures and real-material gate

Two scripts check the DSP beyond the contract tests. Their per-mechanism
numbers are owned by [the live engine design](live-engine.md) and
[the fixture results](quality/2026-10-10-fixture-results.md).

- [`scripts/quality_fixtures.py`](../scripts/quality_fixtures.py) renders
  synthetic fixtures through `pitchwing_live_render` at 48 kHz, block 32, and
  writes one JSON per run; the latest is
  [`2026-10-10-fixtures-step12-shared.json`](results/2026-10-10-fixtures-step12-shared.json).
  Its usage and `--only` selector are in the script docstring.
- [`scripts/real_material_gate.py`](../scripts/real_material_gate.py)
  renders the user's guitar excerpts (`stems/06.wav` 9.2 to 15.7 s at -7 and
  -2, `stems/chord.wav` at $\pm 12$, 44.1 kHz) and fails when the wet peak
  exceeds 1.25 times the dry peak, the attack-envelope ratio exceeds 2 (max)
  or 1.5 (p99), or the render needs more than 0.5 CPU seconds per audio
  second. The latest run is
  [`2026-10-10-real-gate-step12.json`](results/2026-10-10-real-gate-step12.json);
  the script refuses to overwrite an existing output file.

## Reproduction

The commands below were run with the approved temporary CMake under
`/tmp/pitchwing-env`; none fetches a dependency. Use a fresh build directory
if an earlier tools-only cache has tests disabled, and do not run a benchmark
concurrently with a build, test, or other DSP probe. The waveform comparison
links the saved probe source against the two library builds; its binary
sample streams stay in `/tmp`.

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

## Readiness limits

The API covers ShiftKey's control envelope, channel contract, and CMake use.
Acceptance of $\pm 49$ semitones is not established extreme-shift sound
quality. Linked stereo and sample-integrated controls change the DSP relative
to the static engine's listening renders. Unity reacquisition can still dip,
and frame-end Nyquist guarding does not prove alias suppression during a
short upward excursion. Shifted DC and low-dyad defects persist within the
limits stated in the design document. No formant preservation or quality
selector exists. Real input below F#1 and bass support remain open. Windows
and DAW deadline validation and listening are required before production use.
