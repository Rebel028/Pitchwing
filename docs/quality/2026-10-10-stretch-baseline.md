# Matched-delay baseline: Signalsmith Stretch vs Pitchwing live engine (2026-10-10)

Synthetic WSL diagnostics only. Numbers come from `experiments/transport/evaluate.py`
and `scripts/artifact_scan.py`; none of this is a perceptual result or a target-native
real-time measurement. Signalsmith Stretch 1.3.2 (MIT, `research/open-source/stretch-LICENSE.txt`)
was compiled from the unmodified research snapshot; nothing was vendored into the engine.

## Build and configuration

```sh
experiments/stretch-baseline/build.sh
# = g++ -std=c++17 -O2 -I research/open-source experiments/stretch-baseline/stretch_render.cpp -o /tmp/pitchwing-stretch/stretch_render
cd experiments/transport
STRETCH_PRESET=a /tmp/pitchwing-env/bin/python3 -B evaluate.py --native /tmp/pitchwing-stretch/stretch_render --output docs/results/2026-10-10-stretch-a-full.json
STRETCH_PRESET=b /tmp/pitchwing-env/bin/python3 -B evaluate.py --native /tmp/pitchwing-stretch/stretch_render --output docs/results/2026-10-10-stretch-b-full.json
/tmp/pitchwing-env/bin/python3 scripts/summarize_eval.py docs/results/2026-10-10-live-baseline-full.json docs/results/2026-10-10-stretch-a-full.json docs/results/2026-10-10-stretch-b-full.json
```

Stretch: `configure(1, block, hop, splitComputation=false)`, `setTransposeSemitones(s, tonalityLimit=0)`
(strict uniform transposition, no additive high-frequency mapping), no formant processing,
mono float, 32-sample chunks at unity time ratio, pitch set once, tail drained with `flush(block+hop)`.

| preset | 48 kHz block/hop | declared latency | measured impulse delay |
|---|---|---|---|
| Stretch a | 480/96 (10.0 ms, Pitchwing's hop) | 480 | 480 |
| Stretch b | 512/64 (10.667 ms, research custom config) | 512 | 512 |
| Pitchwing live (baseline) | - | 479 | 479 |

Harness sanity check (not a matched-delay case): the same tool with Stretch's default
120 ms/30 ms blocks (`preset d`) transposes 110 Hz and 440 Hz sines within 0-12 cents at
-7/+12 and 30.9 Hz within 0/93 cents, so the errors below are the algorithm at 10 ms
block size, not the renderer.

## Evaluator summary, side by side

`cents_err` = strongest-line cents error, `fit` = fitted fraction of AC energy on the expected
target harmonics. Pitchwing = `2026-10-10-live-baseline-full.json`.

Tones (fixture, shift): cents error / gain dB / fit

| | Pitchwing | Stretch a | Stretch b |
|---|---|---|---|
| B0 -7 | 0.00 / -1.13 / 0.962 | 538 / -3.10 / 0.000 | 191 / -3.65 / 0.010 |
| B0 -1 | -1.08 / -1.04 / 0.970 | 74 / -3.38 / 0.057 | 44 / -2.57 / 0.039 |
| B0 +1 | -0.67 / -1.10 / 0.969 | 214 / -2.13 / 0.003 | 249 / -2.23 / 0.001 |
| B0 +7 | 0.00 / -1.10 / 0.971 | 988 / -0.87 / 0.000 | 1030 / -1.06 / 0.000 |
| E1 -7 | 0.00 / -1.35 / 0.971 | 533 / -2.73 / 0.000 | 269 / -3.29 / 0.000 |
| E1 +7 | 0.00 / -1.32 / 0.964 | 733 / -0.73 / 0.000 | 746 / -0.98 / 0.000 |
| F#1 -7 | 0.00 / -1.05 / 0.980 | 527 / -2.62 / 0.000 | 293 / -3.11 / 0.001 |
| F#1 +7 | 0.00 / -1.04 / 0.977 | 647 / -0.64 / 0.000 | 643 / -0.89 / 0.000 |
| E2 -7 | 7.03 / -0.90 / 0.811 | 484 / -1.44 / 0.000 | 325 / -1.91 / 0.001 |
| E2 -1 | 0.84 / -0.51 / 0.992 | 77 / -0.68 / 0.001 | 59 / -1.22 / 0.000 |
| E2 +7 | -4.71 / -0.51 / 0.616 | 209 / -0.35 / 0.000 | 237 / -0.52 / 0.000 |
| A4 -7 | 0.00 / 0.00 / 1.000 | 43 / -0.14 / 0.000 | 42 / -0.08 / 0.000 |
| A4 +7 | 0.00 / 0.00 / 1.000 | 11 / -0.14 / 0.005 | 4 / -0.07 / 0.022 |

All 0-semitone rows are identity for all three engines (fit 1.000, 0 dB).

Dyads (required spacing Hz / measured Hz / fit)

| | Pitchwing | Stretch a | Stretch b |
|---|---|---|---|
| B0/C1 -7 | 1.23 / 1.84 / 0.025 | 1.23 / 1.83 / 0.000 | 1.23 / 1.84 / 0.003 |
| B0/C1 +7 | 2.75 / 1.84 / 0.024 | 2.75 / 1.83 / 0.000 | 2.75 / 1.18 / 0.000 |
| E1/F1 -7 | 1.64 / 2.45 / 0.038 | 1.64 / 2.44 / 0.000 | 1.64 / 0.69 / 0.000 |
| E1/F1 +7 | 3.67 / 2.45 / 0.002 | 3.67 / 2.27 / 0.000 | 3.67 / 2.44 / 0.000 |

DC (input 0.20): output mean / AC rms

| shift | Pitchwing | Stretch a | Stretch b |
|---|---|---|---|
| -7 | 0.02 / 0.00125 | -0.07 / 0.087 | 0.01 / 0.121 |
| +7 | 0.15 / 0.00489 | -0.00 / 0.178 | 0.00 / 0.174 |

Temporal: onset diff ms / env lag ms / env gain / env NRMSE / late-fit share

| | Pitchwing | Stretch a | Stretch b |
|---|---|---|---|
| B0 gate -7 | 1.25 / -2 / 0.797 / 0.241 / 0.846 | -0.23 / -1 / 0.682 / 0.266 / 0.028 | 5.58 / -1 / 0.652 / 0.247 / 0.344 |
| B0 gate +7 | 0.54 / -2 / 0.848 / 0.150 / 0.725 | 0.60 / -1 / 0.897 / 0.161 / 0.002 | 0.85 / -1 / 0.881 / 0.160 / 0.003 |
| low chord xfade -7 | 0.15 / 0 / 0.757 / 0.395 / 0.166 | -2.40 / -4 / 0.727 / 0.380 / 0.091 | -2.52 / -2 / 0.716 / 0.338 / 0.169 |
| low chord xfade +7 | 3.27 / 1 / 0.771 / 0.301 / 0.042 | 2.02 / 0 / 0.891 / 0.337 / 0.351 | 2.21 / -1 / 0.881 / 0.333 / 0.313 |

## Real DI chord render (44.1 kHz, 958400 frames, Stretch preset a = 441/88, latency 441)

`scripts/artifact_scan.py <render> 44100 --ref /tmp/pitchwing-chord/chord.f64 --offset <latency>`.
Pitchwing renders are the already-present `/tmp/pitchwing-chord/chord_{12,-12}.f64` (offset 439),
rescanned to scratch; their committed scans are `2026-10-10-chord-*-scan.json`. "Loud" = the 10
seconds where the dry DI is above -40 dBFS. Dry DI itself: 235 abs steps > 0.03, 8713 relative steps > 1.
Stretch scans: `docs/results/2026-10-10-stretch-a-chord-{12,-7}-scan.json`.

| render | peak | abs steps > 0.03 | rel steps > 1 (all / loud) | HF wet/dry > 2 kHz, loud seconds: median / p90 / max |
|---|---|---|---|---|
| Pitchwing +12 | 0.982 | 1779 | 8975 / 674 | 21.8 / 1136 / 1136 |
| Stretch a +12 | 0.992 | 2110 | 10300 / 859 | 1.38 / 8.4 / 8.4 |
| Pitchwing -12 | 0.937 | 3 | 1096 / 102 | 1.55 / 10.1 / 10.1 |
| Stretch a -7 | 0.866 | 10 | 1429 / 152 | 0.67 / 0.84 / 0.84 |

(Pitchwing -12 and Stretch -7 are different shifts; the -7 Stretch render was requested for listening.)
Listening excerpts (16-bit WAV, 8-19 s, un-aligned): `/tmp/pitchwing-chord/excerpt_stretch_a_{-7,12}_8-19s.wav`.
No listening was done; these are only files for the user.

## Interpretation (diagnostic, not perceptual)

- Low tones: at a 10 ms block the STFT bin is ~100 Hz wide, far above the B0-E2 fundamentals
  (31-82 Hz) and their harmonic spacing. Stretch's peak-following phase vocoder then cannot locate
  or map those partials; the strongest output line is hundreds of cents off and essentially none of
  the energy lands on the expected target harmonics (fit 0.000-0.06). Even A4 sits 11-43 cents off.
  Pitchwing's past-heavy transport keeps 0-7 cents and 0.6-0.98 fit on the same fixtures. This is the
  decisive result: a conventional phase vocoder is outside its operating range at 10 ms, which is why
  Stretch ships 120 ms by default (preset `d` confirms the same code is accurate there).
- Dyads: neither engine resolves 1-4 Hz dyad spacings at this delay; Stretch's fit share is 0.000 vs
  Pitchwing's 0.002-0.038, i.e. both fail, Pitchwing marginally less so.
- DC: Stretch removes DC at -7/+7 (mean ~0) but turns it into 0.09-0.18 rms AC junk, 20-100x
  Pitchwing's 0.001-0.005. Pitchwing passes a shifted fraction of the DC instead.
- Attacks/envelope: this is the only area where Stretch is competitive or slightly better. Onset
  differences are within a few ms for both; Stretch a has smaller envelope lag at -7 on the gate
  (-1 vs -2 ms) and better envelope gain on the +7 cases (0.89 vs 0.77-0.85), but its late-fit share
  (correct harmonics after the attack) collapses to 0.002-0.35 vs Pitchwing's 0.04-0.85. Stretch b
  (512/64) is worse on the -7 gate onset (5.6 ms) than a.
- Real DI, +12: step counts are similar (Stretch slightly more clicks: 2110 vs 1779), but Pitchwing
  shows seconds with 20-1000x more > 2 kHz energy than the dry signal, versus Stretch's 1.4-8x.
  Pitchwing's +12 HF bursts are a real defect to track; Stretch is cleaner spectrally there even
  though its pitch mapping is unreliable.
- Downward real DI: both are quiet (3-10 abs steps); Stretch -7 at 0.67 HF ratio is darker than dry.
- Preset b (512/64, 10.667 ms) is not better than a: its tone errors are of the same order and its
  dyad/onset numbers are mixed. The extra 0.7 ms buys nothing measurable.

Net: at matched ~10 ms delay, Stretch is not a usable reference for low-register pitch accuracy;
Pitchwing is far ahead on tones and DC, roughly even on attacks, and behind on +12 HF cleanliness
on real DI. Any future "conventional PV" comparison should state that the comparison is in a regime
the PV was never designed for.

## Limitations and remaining work

- Synthetic fixtures and heuristic scans under WSL; no listening, no stereo, no automation.
- Stretch was not tuned beyond block/hop; a tonality limit > 0, split computation, or formant mode
  could change HF behaviour but would no longer be strict transposition.
- The scan thresholds are heuristics shared with the Pitchwing chord scans; "loud" seconds were
  chosen by the dry DI level only.
- Pitchwing's +12 HF bursts on the real DI remain an open defect independent of this baseline.
