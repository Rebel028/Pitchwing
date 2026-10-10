# ShiftKey integration

ShiftKey builds Pitchwing as a CMake source subdirectory and wraps
`LiveEngine` in its `PitchwingShifter` backend, which is the default engine
whenever the build finds Pitchwing. This document describes that current
state in the sibling checkout `../ShiftKey`, the engine facts the backend
relies on, and the checks that exist for the pairing. ShiftKey's own source,
UI, MIDI handling, and packaging are owned by that project; the engine
contract is owned by [the live engine design](live-engine.md).

## Current consumer state

The consumer's CMake (`../ShiftKey/CMakeLists.txt:33-41`) exposes the option
`SHIFTKEY_PITCHWING` (default `ON`) and the cache path `PITCHWING_DIR`
(default `${CMAKE_CURRENT_SOURCE_DIR}/../Pitchwing`). When the option is on
and `${PITCHWING_DIR}/CMakeLists.txt` exists, it calls `add_subdirectory` on
that checkout and sets `SHIFTKEY_HAVE_PITCHWING`; otherwise it prints
`Pitchwing: not found` and builds without the engine. With the engine found,
the `ShiftKey` plug-in and the `pitch_offset` tool link
`pitchwing::pitchwing` and compile with `SHIFTKEY_HAVE_PITCHWING=1`
(`CMakeLists.txt:99-103`). ShiftKey requires CMake 3.24 and C++17
(`CMakeLists.txt:1-5`); Pitchwing is not a vcpkg dependency.

The backend `PitchwingShifter` (`../ShiftKey/src/PitchShifter.h:240-264`)
implements the consumer's `PitchShifter` interface (`PitchShifter.h:15-26`:
stereo in, stereo out, input and output distinct, `prepare()` allocates,
everything else runs on the audio thread):

| Method | Behaviour |
| --- | --- |
| `prepare(sampleRate)` | Constructs a new `pitchwing::LiveEngine` with the host rate and the last accepted pitch, which survives re-preparation. |
| `reset()` | Calls `LiveEngine::reset()`, which discards engine history. |
| `setShiftSemitones(s)` | Forwards finite values; a rejected value (non-finite or outside $\pm 49$) keeps the previous target. |
| `setFormant`, `setHighQuality` | No-ops: Pitchwing has no formant or quality control. |
| `latencySamples()` | Returns `LiveEngine::latencySamples()`. |
| `process(in, out, n)` | Calls `LiveEngine::process(in[0], in[1], out[0], out[1], n)`; on any status other than `Ok` it fills both output planes with zeros, since the engine leaves output untouched on rejection. |

The backend exposes no status; a rejected setter or block is silent apart
from the zeroed output. `reset()` and the other audio-thread methods
dereference the engine pointer, so `prepare()` must run first, as the
interface requires.

The processor lists Pitchwing first, so it is the default engine when built
in (`../ShiftKey/src/PluginProcessor.h:7-12`), and saves the engine choice by
name so a project loads the same engine in builds with or without Pitchwing
(`PluginProcessor.cpp:276-280`). The host latency is set from the active
engine's `latencySamples()` at preparation and at every engine switch
(`PluginProcessor.cpp:97`, `:141`). The MIDI clock compensation table
`clockDelay48k` carries 0 for Pitchwing with the consumer's note "measured
late, never early" (`PluginProcessor.cpp:31-36`), scaled by the host rate
over 48000 (`:144`). The processor splits each host block at delayed MIDI
events and then into chunks of at most 32 samples, setting the shift before
every chunk without a clamp (`PluginProcessor.cpp:207-220`). The step-response
harness `tools/pitch_offset.cpp` includes the Pitchwing backend when it is
built in (`pitch_offset.cpp:26-27`, `:44-45`).

## Consumer requirements and the engine's answer

| Requirement | Evidence in `../ShiftKey` | Engine behaviour |
| --- | --- | --- |
| Stereo planar float, separate input and output buffers | `src/PitchShifter.h:15-23` | `LiveEngine::process` takes planar float; ShiftKey duplicates mono input to its second plane; output planes stay separate. |
| Preparation may allocate; every other call runs on the audio thread | `src/PitchShifter.h:15`; `src/PluginProcessor.cpp:84-88` | Construction allocates; `process`, `reset`, and the setter allocate nothing. One caller per instance. |
| Pitch changes before every chunk, during playback | `src/PluginProcessor.cpp:207-220` | The setter applies from the next input sample without resetting history; chunks of at most 32 samples and one-sample chunks at MIDI boundaries are supported. |
| Fractional total pitch from -49 to +49 semitones | `src/PluginProcessor.cpp:13-17` (base $\pm 24$, fine $\pm 100$ cents); `src/Layout.h:106` (curve amount $\pm 24$) | The sum is accepted without a clamp; this is the control envelope, not an established quality range. |
| Authored curves and instantaneous steps | `src/Playback.h`, `src/Layout.h` | The engine imposes no slew on targets; returns through zero keep their authored timing. |
| Queryable, fixed audio delay while prepared | `src/PluginProcessor.cpp:88`, `:97`, `:141` | `latencySamples()` is fixed per prepared rate and does not change with pitch. |
| MIDI clock compensation distinct from audio delay | `src/PluginProcessor.cpp:31-36`, `:144`; `tools/pitch_offset.cpp` | The audio latency is not the clock compensation; `clockDelay48k` comes from the step measurement in [live validation](live-validation.md). |
| Arbitrary block lengths | `src/PluginProcessor.cpp:207-220` | Any block length is accepted; no hop multiple is assumed. |
| C++17 engine dependency | `CMakeLists.txt:1-5`, `:33-41`, `:99-103` | The self-contained `pitchwing::pitchwing` target, built with the plug-in's toolchain. |
| Formant and quality callbacks exist | `src/PitchShifter.h:22`, `:25` | Not supported; the backend ignores both callbacks. |

The processor passes the host sample rate without a whitelist. `LiveConfig`
accepts 8 to 192 kHz; acceptance alone establishes neither sound quality nor
real-time performance at every rate, and the backend reconstructs the engine
on every `prepare()`.

## Engine facts the backend relies on

Use `LiveEngine`, not the static `Engine`: the static engine is the mono,
fixed-ratio research reference with a $\pm 12$ control limit and a
383-sample default delay, and the earlier listening renders used it. The two
APIs have different contracts.

`LiveEngine` has rate-dependent windows and a fixed delay per prepared
configuration ([geometry](live-engine.md#rate-dependent-geometry-and-scheduling)):

| Sample rate | Hop | Synthesis window | Reported delay | Delay in ms |
| --- | ---: | ---: | ---: | ---: |
| 44.1 kHz | 88 | 352 | 439 | 9.955 |
| 48 kHz | 96 | 384 | 479 | 9.979 |
| 96 kHz | 192 | 768 | 959 | 9.990 |

Query the engine instead of hardcoding this table. A pitch target takes
effect from the next input sample in the control timeline, while spectral
analysis and overlap determine the audible transition, so a one-sample
audible change is not promised. `flush()` is an offline terminal drain, never
a per-buffer call. Keep processing at zero semitones: unity output still
carries the reported delay. Engine resets discard history; ShiftKey's
processor reset clears notes only, and the transport-reset policy for engine
history is that project's decision. Mix law, dry alignment, MIDI note
selection, authored curves, and host latency notification stay with ShiftKey.

## Alternative: installed package

The consumer currently uses the source subdirectory route above. A staged
native build also works:

```cmake
find_package(pitchwing 0.1 CONFIG REQUIRED)
target_link_libraries(ShiftKey PRIVATE pitchwing::pitchwing)
```

Set `CMAKE_PREFIX_PATH` to the staged prefix from `cmake --install`. The
package contains the static library, public headers, CMake config, targets,
and version files, and the bundled FFT's MIT notice. The static library uses
position-independent code for shared-library consumers. Build it with the
same platform, architecture, compiler, runtime-library settings, and
configuration as the consumer; a WSL archive cannot be linked into a Windows
VST. Tools and tests default off when Pitchwing is a subdirectory and on at
the top level; `PITCHWING_BUILD_TOOLS`, `PITCHWING_BUILD_TESTS`, and
`BUILD_TESTING=OFF` override that. The build downloads nothing and adds no
JUCE dependency.

The standalone [`tests/consumer`](../tests/consumer/CMakeLists.txt) project
tests both routes: `MODE=source` uses `PITCHWING_SOURCE_DIR` or the enclosing
checkout, `MODE=installed` uses `find_package`. Each builds a shared consumer
linked to the static engine and an executable that checks stereo unity delay
and active pitch changes. Build and stage under `/tmp` in WSL; the results in
[live validation](live-validation.md) do not establish Windows or DAW
readiness.

## Validation boundary

Stereo linkage, live automation, and CMake packaging do not establish
low-note or dyad fidelity, $\pm 49$-semitone sound quality, or a Windows
real-time deadline. Compare live-engine output against the preserved
reference renders independently, and do not copy the static engine's
383-sample delay or another backend's `clockDelay48k` into the Pitchwing
entry. The 48 octave-step cases at 48 kHz in
[live validation](live-validation.md) support the provisional
`clockDelay48k = 0`: 0 to $\pm 12$ midpoint offsets are near zero after
subtracting the audio latency, while returns to unity vary up to 131.625
samples in that set. Zero is not a guarantee for every curve or low note.
