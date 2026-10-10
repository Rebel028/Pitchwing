# ShiftKey consumer requirements

ShiftKey requires a planar stereo float engine that is prepared outside the
audio thread, accepts a fractional pitch target before every chunk of at
most 32 samples without smoothing it, reports one fixed audio delay per
prepared rate, and builds as a C++17 CMake target with the plug-in's Windows
toolchain. These requirements are read from the sibling checkout
`../ShiftKey` without changing it; current consumer code takes precedence
over its historical sketches. The engine's answer to each requirement is the
contract in [the live engine design](live-engine.md); the consumer-side
wiring is in [ShiftKey integration](shiftkey-integration.md). The engine is
adapted here; no VST is implemented or packaged in this repository.

## Requirements

| Consumer evidence | Engine requirement |
| --- | --- |
| `src/PitchShifter.h:15-26` | Planar stereo float with input and output distinct; `prepare()` may allocate; `reset`, the setter, `process`, and `latencySamples` run on the audio thread without allocating. The static `Engine` is preserved and `LiveEngine` added beside it. |
| `src/PluginProcessor.cpp:207-220` | The pitch setter runs before chunks of at most 32 samples, split at exact MIDI event offsets, so one-sample calls and fractional live controls are required. |
| `src/PluginProcessor.cpp:13-17`; `src/Layout.h:106` | Base $\pm 24$ semitones plus fine $\pm 100$ cents plus curve amount $\pm 24$ semitones sum to $\pm 49$ semitones, applied with no clamp (`PluginProcessor.cpp:219`). Older $\pm 48$ prose omits fine tuning. |
| `.scratch/midi-pitch-blocks/issues/11-pitch-control-signal.md`; `issues/21-block-playback.md` | No added smoothing ramp: short curves and immediate note-off returns keep their authored timing. Overlap-add settling intrinsic to the algorithm is accepted. |
| `src/PluginProcessor.cpp:88`, `:97`, `:141` | A stable audio latency per prepared rate for host compensation and the delayed dry mix; geometry scales with the sample rate. |
| `src/PluginProcessor.cpp:31-36`, `:144`; `issues/15-measure-pitch-offset.md`; `tools/pitch_offset.cpp` | The curve-clock offset is distinct from audio latency. Measure the 220 Hz step response with the 1024-sample Hann old/new amplitude share and report $t_{50}$ minus the event minus the audio delay, the transition width, and the phase dependence. |
| `src/PitchShifter.h:22`, `:25`, `:139` | Formant and quality callbacks exist and an existing backend ignores them; the engine may report both as unsupported. |
| `README.md:98`; `CMakeLists.txt:1-5` | C++17; Windows x64 with VS2019 Build Tools (MSVC 14.29); the consumer requires CMake 3.24, the engine 3.20. A Linux build infers nothing about the native target. |

The consumer has no sample-rate whitelist and no numerical CPU allowance.
The engine therefore validates 44.1, 48, and 96 kHz first and measures
callback time against each block duration. Instances require exclusive
caller access; setters and `process` belong on the audio thread, and the
consumer's parameter handoff is outside this engine's contract.

## Engine decisions taken from these requirements

- Stereo is analysed jointly and rendered per channel without downmixing, so
  anti-phase, swapped, dual-mono, and silent-channel inputs keep their
  relations; the tests for these invariants are listed in
  [live validation](live-validation.md).
- The geometry is a function of the sample rate with a delay of about 10 ms
  at every rate; the formulas are in [the live engine
  design](live-engine.md#rate-dependent-geometry-and-scheduling).
- Spectra, entries, control snapshot, and output destination of a frame are
  immutable until the frame completes, and the frame's inverse transforms are
  spread across the following hop. Frame analysis remains a burst and is
  timed, not proven.
- Pitch controls are integrated per sample over each hop, so a command shorter
  than a hop still contributes; startup prehistory is zero. Discrepancy with
  the original requirement text: the per-sample support correction over
  $(\text{sourceSample}, \text{currentFrame}]$ is replaced by the frame's
  mean control, see [pitch control
  integration](live-engine.md#pitch-control-integration).
- Sustained zero control reacquires exact delayed identity after the earlier
  overlap-add contributions drain, without discarding input history; the
  transition can still dip and needs listening.
- Frame-end Nyquist guarding does not guarantee alias prevention for a brief
  upward excursion that ends before the frame boundary, and neither the
  interface range nor the invariant tests establish extreme-shift audio
  quality.

Shifted DC and low-dyad defects within the limits stated in the design
document, target-native performance, and new listening remain tracked
limitations.
