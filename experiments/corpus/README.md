# Guitar recordings and diagnostic listening set

Intake: 2026-10-08. User-provided sources remain unchanged. This material is
useful for real-instrument listening; it is not an exact target waveform for
transposed polyphonic audio.

## Exported stems

`stems/` contains eight PCM24 WAVs at 44.1 kHz: 177.333 seconds and 46,927,962
encoded bytes in total. Every left-channel sample equals its right-channel
sample in all eight files. Selecting one channel therefore retains the complete
signal in these files; this does not establish stereo processing support.

The user reports the first four or five files are G#1 standard on a seven-string
guitar, and the last three are Drop F#1. Assignments below use filename and export
time order. `05` remains uncertain, and original take names containing
"drop f#" do not override the user's description of mixed tunings.

| File | Seconds | Tuning label | Peak dBFS | PCM endpoint samples per channel |
| --- | ---: | --- | ---: | ---: |
| `01.wav` | 7.203 | G#1 standard | approximately 0 | 299 |
| `02.wav` | 13.019 | G#1 standard | approximately 0 | 9 |
| `03.wav` | 17.000 | G#1 standard | 0 | 1,456 |
| `04.wav` | 23.149 | G#1 standard | 0 | 205 |
| `05.wav` | 16.345 | Unconfirmed: G#1 standard or Drop F#1 | approximately 0 | 217 |
| `06.wav` | 51.510 | Drop F#1, inferred from "last three" | approximately 0 | 885 |
| `tapping1.wav` | 16.392 | Drop F#1, inferred from "last three" | -4.474 | 0 |
| `tapping2.wav` | 32.715 | Drop F#1, inferred from "last three" | approximately 0 | 134 |

Endpoint samples are exact integer PCM minima or maxima, not a diagnosis of
where clipping or limiting occurred. They are an input condition to distinguish
from engine-generated artifacts. Activity candidates use 50 ms RMS measurements;
they do not classify notes, chords, or playing techniques.

The user says these files were rendered in REAPER, probably with stereo
conversion and some high-quality resampling. Dry-DI/FX status is not yet confirmed.
The tuning labels reach F#1; real-input coverage below F#1 remains unestablished.

## Original recordings

Windows location: `D:\Reaper\shiftkey test\Media`.
WSL location: `/mnt/d/Reaper/shiftkey test/Media`.

There are ten original WAVs (40,010,442 bytes): nine dated 2026-10-08 in their
embedded metadata are mono PCM24 at 44.1 kHz; one dated 2025-06-08 is mono PCM24
at 48 kHz. Seven current originals also contain PCM endpoint samples. The two
other current originals and the older take have no endpoint hits. This does not
prove the absence of earlier analog clipping or processing.

Original takes and exported stems are separate source sets. Their exact edit,
trim, gain, and resampling mapping is not established by header inspection.
Originals were read for an audit, not copied or modified. Prefer these original
recordings for future tests once their selected intervals and tuning labels are
mapped, while retaining the exported-stem measurements as their own evidence.

## Listening excerpts

Three six-second intervals were selected from RMS-change candidates. Each is
processed with half a second of original source preroll. The output contains
that preroll, scheduled delay, and the full conservative drain. No fades,
resampling, normalization, limiting, or channel summation are applied.

| Source | Selected source interval | Source frames (end exclusive) |
| --- | --- | --- |
| `02.wav` | 1.8–7.8 s | 79,380–343,980 |
| `06.wav` | 9.7–15.7 s | 427,770–692,370 |
| `tapping1.wav` | 9.0–15.0 s | 396,900–661,500 |

Files are under `/tmp/pitchwing-listening-20261008/`, with one subdirectory per
source. Each contains `dry-delay383.wav`, `minus2.wav`, `minus7.wav`, and
`render.json`. These are diagnostic outputs from the first transport candidate,
now accepted by the user as the listening baseline for a native port. Its
measured DSP limitations remain. Temporary outputs can be recreated
from the saved recipes; their metadata is also saved in the repository.

| Excerpt | Dry reference | -2 semitones | -7 semitones |
| --- | --- | --- | --- |
| G#1 (`02`) | [WAV](/tmp/pitchwing-listening-20261008/02/dry-delay383.wav) | [WAV](/tmp/pitchwing-listening-20261008/02/minus2.wav) | [WAV](/tmp/pitchwing-listening-20261008/02/minus7.wav) |
| Drop F#1 (`06`) | [WAV](/tmp/pitchwing-listening-20261008/06/dry-delay383.wav) | [WAV](/tmp/pitchwing-listening-20261008/06/minus2.wav) | [WAV](/tmp/pitchwing-listening-20261008/06/minus7.wav) |
| `tapping1` | [WAV](/tmp/pitchwing-listening-20261008/tapping1/dry-delay383.wav) | [WAV](/tmp/pitchwing-listening-20261008/tapping1/minus2.wav) | [WAV](/tmp/pitchwing-listening-20261008/tapping1/minus7.wav) |

The sample configuration is still 2048/384/96, so scheduled delay at 44.1 kHz is
383 samples / 8.684807 ms. The dry reference has that same delay. The six-second
audition interval lies at output frames 22,433–287,033; each output has 289,177
frames in total. This delay-matched comparison can reveal timbral changes; it
cannot measure playing feel or end-to-end live latency.

All nine files were checked with ffprobe: mono IEEE float32 WAV, 44.1 kHz,
289,177 frames each. Together they occupy 10,411,398 bytes under `/tmp`.
Unity errors were 3.33e-16 to 4.44e-16. No pre-encoding output exceeded full
scale. Stored float32 samples can differ slightly from float64 metric values
through rounding; the saved result explicitly labels that metric domain.

RMS level changes for the full rendered streams were approximately -1.20/-1.36
dB (`02`, -2/-7), -1.07/-1.23 dB (`06`), and -0.59/-0.71 dB (`tapping1`). No
gain compensation hides these differences. These level statistics do not
establish correct polyphonic pitch or perceptual quality.

The user clarified that all these comparisons sounded good enough and that
`06/minus7` was probably the favorite for its pick attack, while noting that
this may depend on the recording. Preserve that exact source interval, shift,
preroll, gain, and configuration as the attack reference for the native port.
This is informal listening acceptance, not a blinded comparison, a live playing
test, or evidence of competitor parity or correct low-dyad spacing.

## Reproduction and evidence

The existing approved NumPy environment and installed ffmpeg/ffprobe suffice.
If missing in a future session, ask before installation. The auditor reads each
source once, combines hashing with PCM decoding, and retains only one source
waveform at a time. It writes no audio. Ten synthetic decoding/audit tests pass.

```sh
OPENBLAS_NUM_THREADS=1 /tmp/pitchwing-env/bin/python -B experiments/corpus/test_audit.py
OPENBLAS_NUM_THREADS=1 /tmp/pitchwing-env/bin/python -B experiments/corpus/audit_stems.py --input-dir stems --output /tmp/new-stems-audit.json
OPENBLAS_NUM_THREADS=1 /tmp/pitchwing-env/bin/python -B experiments/corpus/render_excerpt.py stems/02.wav --start 1.8 --duration 6 --channel 0 --output-dir /tmp/new-listening/02
OPENBLAS_NUM_THREADS=1 /tmp/pitchwing-env/bin/python -B experiments/corpus/render_excerpt.py stems/06.wav --start 9.7 --duration 6 --channel 0 --output-dir /tmp/new-listening/06
OPENBLAS_NUM_THREADS=1 /tmp/pitchwing-env/bin/python -B experiments/corpus/render_excerpt.py stems/tapping1.wav --start 9.0 --duration 6 --channel 0 --output-dir /tmp/new-listening/tapping1
```

Choose new output paths; existing results are refused. Saved evidence:

- [Stem audit and SHA256 identities](results/2026-10-08-stems-audit.json).
- [Original recording audit and identities](results/2026-10-08-originals-audit.json).
- [Original headers and recording dates](results/2026-10-08-original-headers.json).
- [Excerpt ranges, engine hash, and render measurements](results/2026-10-08-listening-renders.json).

Remaining annotations: `05` tuning, dry/FX status, exact original/export mapping.
Exact
Neural DSP reference renders and below-F#1 input recordings are still absent.

## Additional full-track native render

On 2026-10-08 the user supplied `stems/02 Taking Chances.m4a` as a more
complicated input. It is stereo AAC at 44.1 kHz, with 187.827 seconds of
container duration and embedded cover art. It is separate from the eight-WAV
guitar intake above; tuning, instrumentation, and source processing are not
established by this render.

The complete decoded audio was mixed explicitly as `0.5L + 0.5R` for the
current mono native engine, then shifted -7 semitones at 2048/384/96, block 128.
There is no sample-rate conversion. FFmpeg handled AAC timing once; actual
decoded length was 8283136 frames. Wet and delay-matched dry outputs each have
8285663 frames, including the full 2527-sample drain. Dry is exactly the
float32 input with 383 leading and 2144 trailing zero samples.

The unadjusted decoded dry and wet exceed full scale: peaks are +1.752 and
+3.010 dBFS respectively, with 149 and 3236 stored samples above absolute one.
Both are preserved as float32 WAVs, without limiting. For ordinary playback,
the listening pair applies the same fixed -6 dB to both; this preserves their
relative levels rather than independently normalizing either render. Stored
listening peaks are -4.248 dBFS dry and -2.990 dBFS wet, with no nonfinite or
over-range samples. Full-stream wet RMS is 1.161 dB below dry; this is not a
perceptual quality measurement.

- [Full native -7 listening WAV](/tmp/pitchwing-taking-chances-20261008-ozikic86/listen-minus7.wav).
- [Matching delayed dry listening WAV](/tmp/pitchwing-taking-chances-20261008-ozikic86/listen-dry-delay383.wav).
- [Exact commands, hashes, levels, and provenance](results/2026-10-08-taking-chances-native.json).

All four WAVs (unadjusted and listening pairs) are temporary files under
`/tmp/pitchwing-taking-chances-20261008-ozikic86/`, totaling 132571064 bytes.
Raw float64 intermediates were removed after verification. The saved commands
can regenerate them with fresh output paths. The native binary and source
hashes match the previous native validation; no build or installation was
needed. Stereo support, low-register pitch accuracy, and subjective quality
are not established by this mono listening render.
