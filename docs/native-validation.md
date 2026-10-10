# Native/reference validation tools

The native engine ports the transport experiment with an explicit deterministic
stability fix. Passing these checks means its output follows the new
`StableTransportEngine` variant, not necessarily the preserved original
`TransportEngine`. The change does not repair the documented unresolved-dyad
spacing or shifted-DC failures, establish a supported low tuning, or demonstrate
competitive perceptual quality. Listening to the native variant is still needed.

The original `experiments/transport/engine.py` remains untouched. The new
`stable_reference.py` subclass selects candidate bin 1 when nonzero interior
spectral magnitudes have relative spread at most `1e-12`. Its peak-cap ties use
magnitude followed by bin index, retaining the greatest 64. Other frequency,
phase ancestry, transport, and scheduling equations are retained. This removes
an ill-conditioned peak choice at spectrally flat startup frames: roundoff from
different FFT implementations could select different peaks and produce lasting
phase differences. It is an algorithm behavior change, recorded in report
metadata and source hashes; it must not be described as exact parity with the
old listening prototype.

## Offline runner

The CMake target `pitchwing_render` reads and writes mono raw little-endian IEEE
float64 files. It preloads input and allocates output before processing. The
runner itself is an offline utility and performs allocations and file I/O; the
engine's processing contract is tested separately. Existing output paths are
refused. Use one writer per new output path.

```sh
/tmp/pitchwing-native-release/pitchwing_render --input /tmp/input.f64 --output /tmp/new-output.f64 --sample-rate 48000 --semitones -7 --analysis-size 2048 --synthesis-size 384 --hop 96 --window asymmetric --block 128 --benchmark
```

Output contains every `process()` sample followed by the terminal `flush()`
tail. It retains scheduled delay and is not cropped, normalized, resampled,
limited, or converted to integer PCM. Configuration defaults match the example
except that the default pitch shift is zero and benchmarking is off. Symmetric
comparison requires `--window symmetric --analysis-size 384`. The runner
supports little-endian machines with 64-bit IEEE doubles and emits compact JSON
on stdout; argument, file, and engine failures go to stderr with nonzero status.

`--benchmark` times only individual process calls after preparation and input/
output allocation. It records mean, nearest-rank p95, maximum, total call time,
input-frame throughput, the worst observed ratio of call duration to that
block's audio duration, and the count of calls exceeding their block duration.
Calls whose input start is before `analysis-size + synthesis-size` frames are
excluded as startup warmup; `--warmup-frames N` can override this count, including
zero. Warmup advances the same stream and does not change rendered output.
Timing includes clock overhead and the possibly shorter final block. It excludes
construction, warmup calls, file I/O, and flush. If no call remains after warmup,
the benchmark field is null. It is a bounded diagnostic without a stress loop. WSL
scheduler behavior and these workloads cannot establish target-native callback
deadlines or worst-case real-time safety.

## Bounded parity harness

Use the already approved NumPy environment and an already built runner:

```sh
OPENBLAS_NUM_THREADS=1 /tmp/pitchwing-env/bin/python -B scripts/compare_native.py --runner /tmp/pitchwing-native-release/pitchwing_render --benchmark --output /tmp/pitchwing-native-parity.json --listening-output /tmp/pitchwing-native-06-down7.wav --archive-stem-input /tmp/pitchwing-native-06-input.f64
```

The harness performs 30 comparisons by default:

- Unity noise, DC, and B0 mixture at blocks 1, 127, and 512, with both windows.
- E1 at -7 semitones, B0/C1 at +7, and A4 at -1, each at blocks 64 and 257 with
  both windows. These short signals test implementation parity, not steady
  pitch-quality resolution.
- Three phased A4 signals at -1 semitone, with the first nonzero sample at input
  frame 0, 96, or 97, each with asymmetric analysis and blocks 32, 64, and 128.
  These nine cases specifically exercise the startup peak-selection failure
  both on and immediately after a hop boundary.
- The preferred `stems/06.wav` interval 9.7–15.7 s with 0.5 s source preroll,
  original 44.1 kHz, channel zero, -7 semitones, asymmetric window, blocks 32,
  64, and 128, giving the requested bounded timing observations for each size.
  The reader seeks to 9.2 s and reads only the selected 6.5 seconds once. Both
  engines process the same samples, including preroll, and their complete
  delayed outputs and tails are compared. No full source hash or corpus scan
  is repeated; the report hashes the selected interleaved PCM bytes.

The preserved original Python engine also processes the preferred excerpt once,
reusing the same decoded samples. Every preferred native result records its
waveform difference from that original separately under
`original_prototype_comparison`; these numbers are **not** acceptance criteria.
They make the stability variant's change from the prior listening prototype
visible rather than hiding it behind a different reference.

`--skip-stem` explicitly selects the 27 synthetic-only comparisons. `--stem`
may specify the same preferred recording at a different path. The expected
format remains integer PCM24 at 44.1 kHz; changing the source also changes the
fixture and must be recorded. The source's tuning and processing provenance
remain as documented in the corpus guide, without new inference from the data.

The default acceptance bound is maximum absolute float64 sample error `1e-10`
over complete, equally sized streams, with finite output and equal declared
latency. Reports also contain RMS error and error/reference RMS ratio. A larger
error is a diagnostic failure requiring explanation; the harness does not
silently adjust its tolerance for FFT differences or phase/peak choices.

Raw input/output intermediates live under a temporary `/tmp` directory and are
removed after the run. Input is rewritten there for each fixture/window, while
the preferred source file is read only once. Each Python reference is computed
once per fixture/window and reused across native block sizes. The original
preferred-excerpt reference is likewise computed only once. No audio files
or results are implicitly written into the repository. JSON defaults to stdout;
an explicit `--output` path is created exclusively and must not already exist.

Optional `--listening-output NEW_PATH` writes one mono IEEE float32 WAV under
`/tmp`, using the already loaded native preferred-excerpt output at block 128.
It is written only if that case passes stable-reference parity. The small RIFF
writer includes float format and sample-count chunks. It retains the entire
stream, including preroll, 383-sample delay, and flush tail; there is no crop,
normalization, limiting, or resampling. At 44.1 kHz, audition frames are
22433 through 287032 inclusive (`[22433, 287033)`). The report records these
bounds, encoded hash, and encoding details. Compare this variant with the
preserved original render before deciding whether its audible changes are
acceptable. Numerical parity with the stability variant is not listening approval.

Optional `--archive-stem-input NEW_PATH` retains the selected mono float64 input
under `/tmp`, with its hash, frame count, rate, and source interval in the report.
This permits subsequent isolated timing runs without rereading the recording.
For example, reuse that archive with `pitchwing_render --sample-rate 44100
--semitones -7 --block 32 --benchmark` and explicit new input/output paths as in
the runner command above. Listening/archive outputs require the stem case, must
be distinct new paths in existing `/tmp` directories, and are never implicit.

The report records Python/NumPy/platform versions, both Python-reference source
hashes, native/tool source hashes, runner binary
hash, fixture configurations, optional timings, and failed case identifiers.
Persist the compact report and build configuration with the development record.
The tool does not install dependencies or run a build. Native tests, allocation
checks, sanitizer runs, supported sample-rate coverage, parameter automation,
stereo behavior, and listening remain separate validation tasks.
