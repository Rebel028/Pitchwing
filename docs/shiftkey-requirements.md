# ShiftKey consumer requirements and engine decisions

Recorded 2026-10-09 from the sibling checkout, read without changing it.
Current consumer code takes precedence over historical sketches. The task is
to adapt the reusable engine, not implement or package a VST in this repository.

| Consumer evidence | Engine requirement / decision |
| --- | --- |
| `../ShiftKey/src/PitchShifter.h:12–22` | Planar stereo float, prepare outside audio callback, allocation-free reset/set/process, queried latency. Add `LiveEngine`; preserve static `Engine`. |
| `../ShiftKey/src/PluginProcessor.cpp:198–214` | Pitch setter before chunks of at most 32 samples, split at exact MIDI offsets; support one-sample calls and fractional live controls. |
| `PluginProcessor.cpp:14–17,180,210`; `../ShiftKey/src/Layout.h:50–60,106` | Base ±24 + fine ±1 + curve contribution ±24 = ±49 semitones. Older ±48 prose omits fine tuning. No product clarification needed to support this arithmetic. |
| `../ShiftKey/.scratch/midi-pitch-blocks/issues/11-pitch-control-signal.md:13–16`; issue 21:56 | No added smoothing ramp. Short curves and immediate note-off returns must be retained. OLA remains intrinsic to the algorithm. |
| `PluginProcessor.cpp:79,84,88,132,185–186,220–233` | Stable audio latency for host compensation and delayed dry mix. Scale geometry with sample rate. |
| `PluginProcessor.cpp:30–31,135,148`; issue `15-measure-pitch-offset.md:13–17`; `../ShiftKey/tools/pitch_offset.cpp` | Curve-clock offset is distinct from audio latency. Measure 220 Hz step response using 1024-sample Hann old/new-frequency amplitude share; report t50 minus event minus audio delay, plus transition width and phase dependence. |
| `PitchShifter.h:118–136` | Existing backend allows no-op formant control; report Pitchwing formants/quality selection as unsupported. |
| ShiftKey build documentation; `../ShiftKey/CMakeLists.txt:1–5` | C++17, Windows x64 MSVC 14.29/VS2019; consumer requires CMake 3.24+, engine requires 3.20+. No native target validation can be inferred from Linux builds. |

No consumer sample-rate whitelist or numerical CPU allowance was found. Validate
44.1/48/96 kHz first and measure callback deadlines against each block duration.
Instances require exclusive caller access; setters/process belong on the audio
thread, with consumer parameter handoff outside this engine's contract.

## Implementation design and review

`LiveEngine` uses joint stereo magnitudes and summed per-channel phase
cross-products, preserving anti-phase inputs without downmixing. Near-cancelling
cross-products need a coherence gate and parabolic-frequency fallback. Shared
regions can interact across channels; channel swapping, dual mono, anti-phase
and silent-channel invariants are tested rather than claiming independent DSP.

At sample rate Fs: H=floor(0.002 Fs), L=4H, N=FFT-fast-size-at-least
ceil(2048 Fs/48000), audio delay D=L−1+H. The extra hop spreads regional inverse
transforms across samples while keeping about 10 ms delay. Spectra, regions,
phase/control integrals, unity flag and guard ratio must stay immutable until
the frame completes. Frame analysis remains a burst and must be timed.

Integrate ratio minus one over `(previousFrame, currentFrame]`, with source
support correction over `(sourceSample, currentFrame]`; startup prehistory is
zero. This retains commands shorter than a hop. Full-support unity control
reacquires exact delayed identity after prior OLA contributions drain, without
discarding input history. Transition phase/gain dips remain possible and need
listening. Frame-end Nyquist guarding cannot guarantee alias prevention for a
brief upward excursion ending before the frame boundary. Neither the interface
range nor invariant tests establish extreme-shift audio quality.

Independent bounded subagents reviewed consumer requirements, CMake/API needs,
and frame-scheduling invariants; edits have separate ownership. Builds and
measurements are coordinated by the main agent under `/tmp` to avoid duplicate
I/O. Detailed API and consumer instructions live in [live-engine.md](live-engine.md)
and [shiftkey-integration.md](shiftkey-integration.md). Existing DC and low-dyad
defects, target-native performance, and new listening remain tracked limitations.
