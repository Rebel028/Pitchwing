# Streaming spectral transport experiment

This is the first original Pitchwing engine experiment. It tests a candidate
algorithm behind a small streaming interface. It is mono, uses a fixed pitch
ratio per stream, and is research code, not a native real-time engine.

The product scope is engine-only. No VST SDK, plug-in wrapper, or UI is needed.
The preserved `research/` checkpoint remains the source of the starting design
and baseline evidence.

## What this experiment establishes

Two window configurations use the same processing method and exact output
schedule: a 2048-sample asymmetric analysis with 384-sample synthesis, and a
384-sample symmetric analysis/synthesis baseline. Both use a 96-sample hop and
383 samples of scheduled delay (7.979 ms at 48 kHz).

The interface checks establish delayed identity at unity, arbitrary input block
handling, reset/drain behavior, input validation, and basic transposition of
resolved tones. The evaluator separately measures pitch, residual energy,
low-tone beat spacing, and synthetic envelope behavior. Passing interface checks
does not imply satisfactory low-guitar quality.

Low-register fixtures include inputs below F#1. E1 and B0 are engineering stress
cases; they do not define a guaranteed supported floor. Real dry DI recordings,
human listening, stereo, pitch automation, sample-rate coverage, and native
deadline measurements remain necessary for later engine decisions.

## Running with existing dependencies

Requires Python 3.8 or newer and NumPy. This session used Python 3.8.10 and
NumPy 1.24.4 in a user-approved isolated environment under `/tmp`.

```sh
/tmp/pitchwing-env/bin/python -B experiments/transport/test_engine.py
/tmp/pitchwing-env/bin/python -B experiments/transport/test_metrics.py
/tmp/pitchwing-env/bin/python -B experiments/transport/evaluate.py --help
OPENBLAS_NUM_THREADS=1 /tmp/pitchwing-env/bin/python -B experiments/transport/evaluate.py --output /tmp/pitchwing-new-run.json
```

The temporary environment may disappear. If dependencies are unavailable, ask
the user before installing or recreating them. There is no automatic dependency
installation in these scripts. Use `-B` to avoid bytecode writes on the project
drive. Synthetic audio stays in memory; choose an explicit compact result path
when running the evaluator. Do not run the old research scripts in place: they
overwrite their own saved results.

## Processing interface

```python
from engine import TransportEngine

engine = TransportEngine(semitones=-7)
output_block = engine.process(input_mono_block)
tail = engine.flush()
```

`process` returns exactly one output sample per input sample. The internal hop
clock is independent of input block size. `latency_samples` describes scheduled
delay; it is not a promise about onset or low-frequency settling after shifting.

Pitch is static once nonempty input has been processed. `flush` drains the
remaining analysis history and synthesis contributions, then ends the stream;
a repeated flush returns an empty array. `reset` clears history and permits a
new stream and pitch setting. The drain includes conservative trailing zeros;
callers evaluating a finite source must distinguish this tail from its content.

See [ENGINE_NOTES.md](ENGINE_NOTES.md) for transport and phase conventions,
[METRICS.md](METRICS.md) for metric definitions, and
[DEVELOPMENT.md](../../DEVELOPMENT.md) for decisions and measured findings.

The [first findings](FINDINGS.md) reject this transport candidate for the product:
it preserves the wrong low-dyad beat spacing and mishandles DC under shifting.
The saved experiment remains useful as a falsifiable baseline. Following the
user's acceptance of the real-guitar listening set and explicit request for
C++, it also serves as the numerical reference for the first native engine.
That sequencing decision does not remove the measured defects.
