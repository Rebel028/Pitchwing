# Native engine validation results (2026-10-08)

This is the dated record of the first native engine validation. On
2026-10-08 the static C++ engine built as `libpitchwing.a` with the offline
runner and tests, passed all nine contract test groups in release and
sanitizer builds, allocated nothing after preparation, and matched the
deterministic Python variant in all 30 parity cases with a worst error of
$1.667 \times 10^{-13}$ against a $10^{-10}$ bound. It was not, and is not,
a target-native deadline-validated or listening-approved engine. The
procedure is in [native validation](native-validation.md); the contract is in
[native core](native-core.md).

## Checks and outcomes

Evidence: [build record](results/2026-10-08-native-build.json) and
[final comparisons](results/2026-10-08-native-parity-final.json).

- GCC 9.4, C++17, release (`-O3`) and ASan/UBSan (`-O1 -g`) builds completed
  without compiler warnings at `-Wall -Wextra -Wpedantic`.
- All nine test groups passed: unity at every hop phase with both windows,
  block independence and reset, in-place and rejected buffers for double and
  float, static pitch and flush lifecycle, float/double parity at 44.1 kHz,
  moves and moved-from state, no allocations after preparation, and invalid
  configurations.
- No global `new` was observed during processing, reset, static pitch setting,
  or draining, including the first callback. The probe covers aligned `new`
  and does not intercept direct `malloc` or `realloc`.
- All 30 parity comparisons passed at maximum absolute tolerance $10^{-10}$.
  The worst error was $1.667 \times 10^{-13}$; the preferred real excerpt
  measured $1.481 \times 10^{-13}$.
- ASan/UBSan tests passed with fatal findings enabled. Leak validation stayed
  unavailable: the first leak scan rejected `ptrace`, an unsandboxed retry was
  terminated, and a CTest retry exited 137 without a diagnostic. The recorded
  sanitizer run used `detect_leaks=0` and a 16 MB ASan quarantine.

The default scheduled delay is 383 samples: 8.6848 ms at 44.1 kHz and
7.9792 ms at 48 kHz. This excludes audio-device and host delay and does not
measure frequency-dependent settling or live playing feel.

## Reference change: flat-spectrum peak selection

The literal port failed every shifted comparison while reconstructing unity
correctly: [initial parity](results/2026-10-08-native-parity-initial.json)
reports maximum errors of 0.414368 (E1, $-7$ semitones, asymmetric), 0.780470
(B0 plus C1, $+7$, asymmetric), 0.0657946 (A4, $-1$, asymmetric), and
0.812590 (preferred excerpt). Block size did not change them. The cause was
the flat spectrum of a frame whose only nonzero sample is its first: FFT
rounding chose different local maxima, which seeded different persistent
inherited phases. Moving the onset by one sample removed the mismatch; moving
it by one full hop kept it.

The 30 probes in [startup probes](results/2026-10-08-startup-probes.json)
each used

$$
x[n] = 0.3 \sin\!\left(2\pi f\,\frac{n}{48000} + 0.23\right), \quad 0 \le n < 4096,
$$

hop 96, $L = 384$, the release runner, and the original Python reference,
comparing the complete process-plus-flush output. Maximum absolute errors:

| $f$ / shift / window | Original | Only $x[0] = 0$ | One leading zero |
|---|---:|---:|---:|
| 440 Hz / $-1$ / asymmetric | 0.0657946 | 2.01e-15 | 4.26e-15 |
| 440 Hz / $-1$ / symmetric | 0.0293861 | 3.43e-15 | 3.30e-15 |
| 41.203445 Hz / $-7$ / asymmetric | 0.0920660 | 6.45e-16 | 7.41e-16 |
| 41.203445 Hz / $-7$ / symmetric | 0.0550446 | 4.40e-15 | 1.78e-15 |
| 750 Hz / $+12$ / asymmetric | 0.690337 | 7.05e-15 | 4.95e-15 |
| 750 Hz / $+12$ / symmetric | 0.568743 | 2.40e-15 | 7.95e-15 |

For every row, 96 leading zeros reproduced the original error and 97 leading
zeros matched the one-zero result; those two variants complete the five
variants per row. The probes use phase 0.23 where the harness E1 fixture uses
0.31, which is why their failing magnitudes differ from the harness report.

The fix in the engine and in `experiments/transport/stable_reference.py`
selects canonical bin 1 when the interior magnitude spread is at most
$10^{-12}$ of the maximum, and defines the ordering at the 64-peak cutoff
([native core](native-core.md) has the rule). The original `engine.py` and the
user-accepted listening renders are unchanged. The corrected variant passed all
30 checks before the modulation arithmetic change:
[stable parity](results/2026-10-08-native-parity-stable.json). Final parity
measures that variant, not the old prototype. For the preferred excerpt the
difference from the old waveform is large (maximum 1.126, RMS 0.202); these
phase-sensitive errors are not a perceptual quality score.

## Diagnostic performance

Measured on an i9-10900KF under WSL with GCC `-O3`, on the same 6.5-second
44.1 kHz mono excerpt at $-7$ semitones. Preparation, file I/O, flush, and
the first 2432 input frames are excluded; timer overhead, the final partial
block, and operating-system scheduling are included. No other build or
sanitizer run overlapped the final measurements. Source:
[final comparisons](results/2026-10-08-native-parity-final.json) against
[stable parity](results/2026-10-08-native-parity-stable.json).

| Block samples | Audio duration µs | Final mean / p95 / max µs | Calls over duration | Throughput gain versus unoptimized deterministic port |
| ---: | ---: | ---: | ---: | ---: |
| 32 | 725.6 | 256.1 / 894.6 / 1593.4 | 1895 / 8882 | 1.353 |
| 64 | 1451.2 | 508.8 / 893.4 / 9941.7 | 6 / 4441 | 1.382 |
| 128 | 2902.5 | 994.5 / 1748.6 / 1984.2 | 0 / 2221 | 1.408 |

The gain column compares the final build with the stable-parity build, which
lacks the anchored complex recurrence and the taper shortcut described in
[native core](native-core.md). Persistent phase and region state are the same
in both, and parity held. The 35 to 41 percent higher throughput is a short
observation, not a characterized speedup or a worst-case bound.

The 96-sample hop concentrates work in single callbacks, so a good average
rate does not show that 32-sample callbacks finish in time. The 9941.7 µs
maximum at block 64 is recorded without an attributed cause. Zero misses at
block 128 do not guarantee a target deadline. The next performance question
is reducing or distributing per-region inverse-FFT work without adding delay,
measured on dense inputs and target hardware before any real-time claim.

## Native listening file

The native render of excerpt 06 at $-7$ semitones was written to
`/tmp/pitchwing-native-listening-20261008/06-minus7.wav`: mono float32,
44.1 kHz, 289177 frames, 1156766 bytes, format and frame count confirmed with
`ffprobe`. It uses the same source interval, channel, 0.5-second preroll, and
383-sample scheduled delay as the original example; audition frames are
$[22433, 287033)$ with no normalization, limiting, resampling, or crop. The
final report holds its hash and recipe. The file is temporary and the
harness command in [native validation](native-validation.md) recreates it.
User listening acceptance is still pending.

The comparison files are the preserved Python render
`/tmp/pitchwing-listening-20261008/06/minus7.wav` and the delayed dry signal
`/tmp/pitchwing-listening-20261008/06/dry-delay383.wav`, also temporary. The
measured low-dyad spacing and DC defects remain unresolved. Stereo, smooth
live pitch changes, broader sample-rate coverage, real recordings below F#1,
and target-native callback validation remain open. No VST work is included.

## Provenance of the recorded run

The build, test, and harness commands are in
[native validation](native-validation.md). In the recorded final run, the 27
synthetic comparisons ran first without timing; the three preferred-excerpt
cases then used `compare_case` with the archived mono samples, whose hash was
checked against the earlier report before reuse. This avoided another read of
the recording; the standard harness command reproduces the same fixtures by
seeking to the bounded source interval. The initial and stable runs each read
only that interval. Build products and audio scratch stayed under `/tmp`; the
compact evidence is in `docs/results/`.
