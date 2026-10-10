# Native engine validation — 2026-10-08

The first C++ engine is implemented and builds as `libpitchwing.a`, with a
standalone offline runner and tests. It is mono and static ratio, supports
float/double buffers and arbitrary block sizes, and prepares its storage before
processing. The final implementation passes its contract checks and agrees with
the explicit deterministic Python variant. It is not yet a production-quality
or target-native deadline-validated engine.

## What was checked

- GCC 9.4/C++17 release and ASan/UBSan builds complete without compiler warnings.
- All nine test groups pass, covering both windows and every hop phase,
  reconstruction, blocks, in-place buffers, rejection without state mutation,
  reset/drain, pitch lifecycle, moves, and configuration validation.
- No global-new allocations were observed during processing, reset, static
  pitch setting, or draining, including the first callback. The allocation probe
  includes aligned new but does not intercept direct malloc/realloc.
- All 30 final numerical comparisons pass at maximum absolute tolerance 1e-10.
  Worst observed error is 1.667e-13; the preferred real excerpt is 1.481e-13.
- ASan/UBSan direct tests pass with fatal findings enabled. Leak validation
  remains unavailable: the initial leak scan rejected ptrace, an unsandboxed
  retry was terminated, and another CTest retry exited 137 without a diagnostic.
  Final direct tests use leak detection off and a bounded 16 MB ASan quarantine.

See the [build record](results/2026-10-08-native-build.json),
[final comparisons](results/2026-10-08-native-parity-final.json), and
[core contract](native-core.md). Default scheduled delay is 383 samples:
8.6848 ms at 44.1 kHz, 7.9792 ms at 48 kHz. This excludes audio-device/host delay
and does not measure frequency-dependent settling or live playing feel.

## Why the numerical reference changed

The first literal port failed every shifted comparison while reconstructing
unity correctly. Flat spectra at startup produced different local maxima from
FFT rounding, which changed persistent inherited phases. Moving onset by one
sample removed the mismatch; moving it by one full hop retained it. These
failed results and the thirty small diagnostic probes are retained:
[initial port](results/2026-10-08-native-parity-initial.json),
[startup probes](results/2026-10-08-startup-probes.json).

Native code and `experiments/transport/stable_reference.py` now choose canonical
bin 1 when positive-interior magnitude spread is at most 1e-12 of the maximum,
and define ordering at the 64-peak cutoff. The original `engine.py` and the
user-accepted listening renders remain unchanged. The corrected variant passed
all 30 checks [before optimization](results/2026-10-08-native-parity-stable.json).
Final parity measures that variant, not the old prototype. For the preferred
excerpt, difference from the old waveform is substantial (max 1.126, RMS 0.202);
these phase-sensitive errors are not a perceptual quality score.

## Diagnostic performance

Measured on an i9-10900KF under WSL, GCC `-O3`, using the same 6.5-second
44.1 kHz mono source slice at -7 semitones. Preparation, file I/O, flush, and
the first 2432 input frames are excluded. No parent build or sanitizer run
overlapped the final measurements. Timer overhead, the final partial block,
and operating-system scheduling remain in the measurement.

| Block samples | Audio duration µs | Final mean / p95 / max µs | Calls over duration | Throughput gain versus unoptimized deterministic port |
| ---: | ---: | ---: | ---: | ---: |
| 32 | 725.6 | 256.1 / 894.6 / 1593.4 | 1895 / 8882 | 1.353× |
| 64 | 1451.2 | 508.8 / 893.4 / 9941.7 | 6 / 4441 | 1.382× |
| 128 | 2902.5 | 994.5 / 1748.6 / 1984.2 | 0 / 2221 | 1.408× |

The optimization replaces repeated modulation trigonometry with a complex
recurrence re-anchored every 64 samples and avoids taper cosine outside its
transition. It leaves persistent phase/region state unchanged. The runs show
35–41% higher throughput, with numerical agreement retained. They are short
observations, not a statistically characterized speedup or worst-case bound.

The 96-sample hop still concentrates work in individual callbacks. A good
average processing rate does not establish that 32-sample callbacks can finish
in time. The long 64-sample maximum is retained without attributing its cause.
Even the observed zero misses at 128 samples cannot guarantee target deadlines.
Reducing per-region inverse-FFT work or distributing it without adding delay is
the next performance question; measure dense inputs and target-native behavior
before making a real-time claim.

## Native listening artifact

[Native 06 at -7 semitones](/tmp/pitchwing-native-listening-20261008/06-minus7.wav)
is mono float32, 44.1 kHz, 289177 frames, 1156766 bytes. ffprobe confirms the
format and frame count. It uses the same source interval, channel, 0.5-second
preroll, and 383-sample scheduled delay as the original example. Audition frames
are `[22433, 287033)`; there is no normalization, limiting, resampling, or crop.
The final report contains its hash and recipe. The file is temporary and can be
recreated with the command below. User listening acceptance is still pending.

Compare with the preserved
[Python 06/-7](/tmp/pitchwing-listening-20261008/06/minus7.wav) and
[delayed dry](/tmp/pitchwing-listening-20261008/06/dry-delay383.wav).
Measured low-dyad spacing and DC defects remain unresolved. Stereo, smooth live
pitch changes, broader sample-rate coverage, below-F#1 real recordings, and
target-native callback validation remain future work. No VST work is included.

## Reproduce

Use already-installed tools; obtain approval for any missing installation.

```sh
export PATH="/tmp/pitchwing-env/bin:$PATH"
cmake -S . -B /tmp/pitchwing-native-release -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build /tmp/pitchwing-native-release --parallel 2
ctest --test-dir /tmp/pitchwing-native-release --output-on-failure
cmake -S . -B /tmp/pitchwing-native-sanitize -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS_DEBUG='-O1 -g' -DBUILD_TESTING=ON -DPITCHWING_ENABLE_ASAN=ON -DPITCHWING_ENABLE_UBSAN=ON
cmake --build /tmp/pitchwing-native-sanitize --parallel 2
ASAN_OPTIONS=detect_leaks=0:halt_on_error=1:quarantine_size_mb=16:thread_local_quarantine_size_kb=64 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 /tmp/pitchwing-native-sanitize/pitchwing_tests
OPENBLAS_NUM_THREADS=1 /tmp/pitchwing-env/bin/python -B scripts/compare_native.py --runner /tmp/pitchwing-native-release/pitchwing_render --benchmark --output /tmp/new-native-parity.json --listening-output /tmp/new-native-06-minus7.wav
```

Choose new output names: reports/audio refuse existing paths. In the recorded
final run, the 27 synthetic comparisons were executed first without timing, then
the three preferred-excerpt cases used `compare_case` with the already archived
mono samples. Their hash was verified against the earlier report before reuse.
This avoided another stem read; the standard command above reproduces the same
fixtures by seeking directly to the bounded source interval. The initial and
stable runs each read only that interval, not the full stem or corpus. Build
products and audio scratch remain under `/tmp`; compact evidence stays here.
