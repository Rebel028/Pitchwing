# Signalsmith Stretch matched-delay baseline

Offline mono renderer that drives Signalsmith Stretch 1.3.2 (MIT, headers in
`research/open-source/`, unmodified and not vendored into the engine) with the
same CLI contract as `tools/pitchwing_live_render.cpp`, so
`experiments/transport/evaluate.py --native` and `scripts/artifact_scan.py` can
compare a conventional phase vocoder at ~10 ms delay against Pitchwing.

```sh
experiments/stretch-baseline/build.sh            # g++ -std=c++17 -O2 -> /tmp/pitchwing-stretch/stretch_render
/tmp/pitchwing-stretch/stretch_render in.f64 out.f64 48000 -7 32 a
STRETCH_PRESET=b /tmp/pitchwing-stretch/stretch_render in.f64 out.f64 48000 12   # env form used by evaluate.py
```

Presets (6th argument or `STRETCH_PRESET`, default `a`), block/hop derived from the sample rate:

| preset | block | hop | 48 kHz | 44.1 kHz | latency (inputLatency+outputLatency) |
|---|---|---|---|---|---|
| a | 10 ms | 2 ms | 480/96 | 441/88 | = block (10.0 ms) |
| b | 32/3 ms | 4/3 ms | 512/64 | 470/59 | = block (10.667 ms) |
| d | 120 ms | 30 ms | 5760/1440 | 5292/1323 | = block (120 ms); harness sanity reference only |

Tonality limit 0 (strict uniform transposition), split computation off, fixed
random seed, 32-sample process chunks, tail = block + hop via `flush()`. Stderr
ends with `latency <N>` as the evaluator expects. Results and interpretation:
`docs/quality/2026-10-10-stretch-baseline.md`.
