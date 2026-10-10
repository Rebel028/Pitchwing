# Native validation tools

Two tools check the static native engine against its Python reference:
the offline runner `pitchwing_render` (`tools/pitchwing_render.cpp`) and the
parity harness `scripts/compare_native.py`. A passing harness run means the
native output matches `StableTransportEngine` in
`experiments/transport/stable_reference.py` to $10^{-10}$ maximum absolute
error, with equal frame counts, finite output, and equal declared latency. It
does not mean parity with the preserved original `TransportEngine`
(`experiments/transport/engine.py`), does not repair the documented
unresolved-dyad and shifted-DC defects, and is not listening approval. The
reference variant and its reason are described in
[native core](native-core.md); recorded runs are in
[native validation results](native-validation-results.md).

## Build and test

Use the already installed tools; ask before installing anything. The CMake
options are in `CMakeLists.txt`: `PITCHWING_BUILD_TOOLS` and
`PITCHWING_BUILD_TESTS` default to on at the top level, and
`PITCHWING_ENABLE_ASAN` and `PITCHWING_ENABLE_UBSAN` default to off and
require GCC or Clang. Configuration downloads nothing; the FFT header is
bundled under `third_party/` (see `third_party/README.md`).

```sh
cmake -S . -B /tmp/pitchwing-native-release -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build /tmp/pitchwing-native-release --parallel 2
ctest --test-dir /tmp/pitchwing-native-release --output-on-failure
```

`ctest` runs `pitchwing_engine` (`tests/engine_tests.cpp`, nine groups) and
`pitchwing_live_engine` (`tests/live_engine_tests.cpp`). For a sanitizer build:

```sh
cmake -S . -B /tmp/pitchwing-native-sanitize -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS_DEBUG='-O1 -g' -DBUILD_TESTING=ON -DPITCHWING_ENABLE_ASAN=ON -DPITCHWING_ENABLE_UBSAN=ON
cmake --build /tmp/pitchwing-native-sanitize --parallel 2
ASAN_OPTIONS=detect_leaks=0:halt_on_error=1:quarantine_size_mb=16:thread_local_quarantine_size_kb=64 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 /tmp/pitchwing-native-sanitize/pitchwing_tests
```

Leak detection stays off: in the recorded WSL run the leak scan rejected
`ptrace` (see the results document).
[Live validation](live-validation.md) records the later sanitizer runs,
including the `handle_segv=0` option they needed.

## Offline runner

`pitchwing_render` reads one mono raw little-endian IEEE float64 file, runs
every `process()` block through one `Engine`, appends the `flush()` tail, and
writes the complete stream as the same raw format. The output keeps the
scheduled delay and is not cropped, normalized, resampled, limited, or
converted to integer PCM. The runner refuses an existing output path and
assumes one writer per new path. It requires a little-endian machine with
64-bit IEEE doubles. It prints a compact JSON report on stdout; argument,
file, and engine failures go to stderr with exit status 1.

```sh
/tmp/pitchwing-native-release/pitchwing_render --input /tmp/input.f64 --output /tmp/new-output.f64 --sample-rate 48000 --semitones -7 --analysis-size 2048 --synthesis-size 384 --hop 96 --window asymmetric --block 128 --benchmark
```

| Option | Default | Usage |
|---|---|---|
| `--input PATH` | required | Raw float64 input file. |
| `--output PATH` | required | New raw float64 output file; an existing path is an error. |
| `--sample-rate HZ` | 48000 | Finite positive number; only used for the benchmark deadline and the report. |
| `--semitones X` | 0 | Finite pitch shift within $[-12, 12]$. |
| `--analysis-size N` | 2048 | Analysis FFT size; symmetric mode needs `--analysis-size 384`. |
| `--synthesis-size L` | 384 | Synthesis window size. |
| `--hop H` | 96 | Hop size. |
| `--window MODE` | asymmetric | `asymmetric` or `symmetric`. |
| `--block B` | 128 | Samples per `process()` call. |
| `--benchmark` | off | Times individual `process()` calls after warmup. |
| `--warmup-frames N` | $N + L$ source frames | Calls whose input starts before this frame are not timed; `0` times every call. |
| `--help` | | Prints usage and exits 0 (only as the sole argument). |

The runner itself allocates and performs file I/O; it preloads the input and
allocates the output before processing. The engine's no-allocation contract is
tested separately in `tests/engine_tests.cpp`. The runner checks every
`process` and `flush` status and rejects a nonfinite output sample.

With `--benchmark`, the report's `benchmark` object records the timed call
count, warmup frames, excluded calls, timed input frames, mean, nearest-rank
p95 (index $\lceil 0.95\,n \rceil - 1$ of the sorted durations), maximum,
total call time, worst ratio of call duration to that block's audio duration,
the number of calls longer than their block, and input frames per second.
Warmup calls advance the same stream and do not change the rendered output.
Timing includes clock overhead and the possibly shorter final block and
excludes construction, warmup, file I/O, and flush. With no timed call the
field is `null`. WSL scheduling makes these numbers a diagnostic, not a
target-native deadline result; the report says so in its `limitations` string.

## Parity harness

Run the harness with the approved NumPy environment and a built runner:

```sh
OPENBLAS_NUM_THREADS=1 /tmp/pitchwing-env/bin/python -B scripts/compare_native.py --runner /tmp/pitchwing-native-release/pitchwing_render --benchmark --output /tmp/pitchwing-native-parity.json --listening-output /tmp/pitchwing-native-06-down7.wav --archive-stem-input /tmp/pitchwing-native-06-input.f64
```

| Option | Default | Usage |
|---|---|---|
| `--runner PATH` | required | Built `pitchwing_render` executable. |
| `--output PATH` | stdout | New JSON report path; an existing path is an error. |
| `--tolerance X` | $10^{-10}$ | Maximum absolute float64 sample error per case; finite and positive. |
| `--benchmark` | off | Passes `--benchmark` to every runner call. |
| `--skip-stem` | off | Runs only the 27 synthetic cases. |
| `--stem PATH` | `stems/06.wav` | Preferred recording; must stay integer PCM24 at 44.1 kHz. |
| `--listening-output PATH` | none | New float32 WAV under `/tmp` of the native preferred excerpt at block 128. |
| `--archive-stem-input PATH` | none | New raw float64 file under `/tmp` holding the selected excerpt input. |

The harness exits 0 when every case passes and 1 otherwise. A case passes when
frame counts match, all native samples are finite, the maximum absolute error
is at most the tolerance, and the runner's `latency_samples` equals the
reference's. The report also stores the RMS error and the error-to-reference
RMS ratio. A larger error is a diagnostic failure that needs an explanation;
the harness never widens its tolerance for FFT or peak-choice differences.

### Cases

The default run performs 30 comparisons, all with $L = 384$ and $H = 96$:

- unity: noise plus 0.12 DC plus a B0 sine (6143 samples at 48 kHz) at blocks
  1, 127, and 512, with both windows (6 cases);
- E1 at $-7$ semitones, B0 plus C1 at $+7$, and A4 at $-1$, each at blocks 64
  and 257 with both windows (12 cases). These short signals test
  implementation parity, not steady pitch quality;
- A4 at $-1$ semitone with the first nonzero sample at input frame 0, 96, or
  97, asymmetric window, blocks 32, 64, and 128 (9 cases). They exercise the
  startup peak-selection failure on and just after a hop boundary;
- the preferred recording `stems/06.wav`, audition interval 9.7 to 15.7 s with
  0.5 s preroll, 44.1 kHz, channel zero, $-7$ semitones, asymmetric window,
  blocks 32, 64, and 128 (3 cases). The reader seeks to 9.2 s and reads 6.5 s
  once; both engines process the same samples including preroll. The report
  hashes only the selected interleaved PCM bytes.

The preserved original `TransportEngine` also processes the preferred excerpt
once, and each preferred case records its difference from that output under
`original_prototype_comparison` with `used_for_acceptance: false`. These
numbers make the variant's change from the accepted listening prototype
visible; they are not acceptance criteria.

`--skip-stem` selects the 27 synthetic cases. `--stem` points at the same
recording at another path; changing the source changes the fixture and must be
recorded. The recording's tuning and provenance are documented in
`experiments/corpus/README.md`.

### Scratch and outputs

Raw intermediates live in a temporary directory under `/tmp` that the harness
removes at exit. The input is rewritten there once per fixture and window; the
preferred recording is read once. Each Python reference is computed once per
fixture and window and reused across native block sizes. Nothing is written
into the repository.

`--listening-output` writes one mono IEEE float32 WAV (format tag 3, with a
`fact` chunk) from the native preferred-excerpt output at block 128, only when
that case passes. The file keeps the whole stream: preroll, 383-sample delay,
and flush tail, with no crop, normalization, limiting, or resampling. At
44.1 kHz the audition interval is frames $[22433, 287033)$, from
$\mathrm{round}(0.5 \cdot 44100) + 383$ for six seconds. The report records
these bounds, the encoded hash, and the encoding. Compare this file with the
preserved original render before judging its audible changes.

`--archive-stem-input` keeps the selected mono float64 input with its hash,
frame count, rate, and source interval in the report, so a later timing run
can reuse it without rereading the recording: pass it to `pitchwing_render`
with `--sample-rate 44100 --semitones -7 --block 32 --benchmark` and new
paths. Both audio outputs require the stem case and must be new paths in
existing `/tmp` directories.

### Report contents

The JSON report (`schema_version` 2) records the reference-variant policy,
Python, NumPy, and platform versions, SHA-256 of the harness, runner source,
engine header and source, both Python references, and
`experiments/corpus/audit_stems.py`, the runner binary hash, the tolerance,
whether the stem was included, the limitations list, every case with its
configuration and optional runner timing, `case_count`, `passed`, and
`failed_cases` as `fixture/window/blockB` identifiers. Persist the compact
report with the development record. The harness installs nothing and runs no
build. Native contract tests, allocation checks, sanitizer runs, sample-rate
coverage, automation, stereo, and listening are separate tasks.
