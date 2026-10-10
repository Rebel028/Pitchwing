# ShiftKey engine contract

Reviewed on 2026-10-09 against the sibling `../ShiftKey` source checkout. This
document records engine requirements and a consumer adapter example. No ShiftKey
source, plug-in registration, UI, MIDI handling, or packaging is changed here.

## Requirements found in the consumer

| Requirement | Source evidence in `../ShiftKey` | Pitchwing consequence |
| --- | --- | --- |
| Stereo planar float, separate input/output buffers | `src/PitchShifter.h:12–22`; `src/PluginProcessor.cpp:195–214` | Use `LiveEngine::process(left, right, outLeft, outRight, frames)`. ShiftKey duplicates mono input to its second plane; keep both output planes separate. |
| Preparation may allocate; all other engine calls run on the audio thread | `src/PitchShifter.h:12–22`; `src/PluginProcessor.cpp:72–89,127–132,178–214` | Construct/reconstruct outside processing. Process, reset, and pitch setters must preserve allocation-free operation. Each instance has one caller at a time. |
| Pitch changes before every chunk, including during playback | `src/PluginProcessor.cpp:198–215` | Accept active changes without resetting history. Chunks are at most 32 samples and may be one sample at MIDI boundaries. |
| Fractional total pitch from −49 to +49 semitones | `src/PluginProcessor.cpp:14–17,180,210`; `src/Layout.h:50–60,106`; `src/Playback.h:62–66` | Base ±24, fine ±1, and curve contribution ±24 sum without a final clamp. This is a control envelope, not an established quality range. |
| Curves and instantaneous steps | `src/Playback.h:32–39,69–74`; `src/Layout.h:129–136` | Preserve authored timing, including returns through zero; do not impose an undocumented fixed slew on every target. |
| Queryable, fixed audio delay while prepared | `src/PluginProcessor.cpp:79–88,132,185–186,220–233` | Report `latencySamples()` to the host and to dry alignment. Changing pitch must not change that value. |
| MIDI clock compensation is distinct from audio delay | `src/PluginProcessor.cpp:30–31,135,148`; `tools/pitch_offset.cpp:1–9,43–63` | Measure pitch-change response before adding a `clockDelay48k` entry. The audio latency is not the clock compensation. |
| Arbitrary block lengths | `src/PluginProcessor.cpp:189–214` | Host blocks are sliced into prepared-size pieces and then into short control chunks. No FFT-hop multiple is guaranteed. |
| C++17 engine dependency | `CMakeLists.txt:1–5,61–73` | Link the self-contained `pitchwing::pitchwing` target; build it using the plug-in's Windows toolchain. |
| Formant and quality callbacks exist, with backend-specific support | `src/PitchShifter.h:19,22,118–136`; `src/PluginProcessor.cpp:77,179` | Pitchwing currently has no formant-preservation or quality-mode control. Expose that limitation; an adapter may explicitly ignore those callbacks, as an existing backend does. |

The processor currently exposes float processing only (`src/PluginProcessor.h:17`).
`LiveEngine` also accepts doubles, but the current ShiftKey adapter does not
need them. The consumer passes the host sample rate without a whitelist.
`LiveConfig` accepts 8–192 kHz; acceptance alone does not establish sound quality
or real-time performance at every rate. Reconstruct the engine when preparation
changes the rate.

## Choosing the engine API

Use [`LiveEngine`](../include/pitchwing/LiveEngine.hpp) for ShiftKey. It provides
linked stereo and live pitch targets. The original [`Engine`](../include/pitchwing/Engine.hpp)
remains the mono, fixed-ratio research reference, including its ±12 control
limit and 383-sample default delay. The two APIs deliberately have different
contracts; the earlier listening renders used the original engine.

`LiveEngine` has sample-rate-dependent windows and a fixed delay for each
prepared configuration. At the common rates the current values are:

| Sample rate | Hop | Synthesis window | Reported delay | Delay in ms |
| --- | ---: | ---: | ---: | ---: |
| 44.1 kHz | 88 | 352 | 439 | 9.955 |
| 48 kHz | 96 | 384 | 479 | 9.979 |
| 96 kHz | 192 | 768 | 959 | 9.990 |

Always query the engine instead of hardcoding this table. Pitch targets take
effect from the next input sample in the engine's control timeline. Spectral
analysis and overlap still determine the audible transition, so this does not
promise a one-sample audible pitch change. `flush()` is an offline terminal
drain, never a call to make after each DAW buffer. Keep processing at zero
semitones: unity output still carries the reported audio delay.

Mix law, dry alignment, MIDI note selection, authored curves, and host latency
notification stay with ShiftKey. Its current processor reset clears notes only
(`src/PluginProcessor.h:15`); transport-reset policy for engine history must be
chosen in that project. Engine resets intentionally discard history.

## Source and installed dependencies

For a sibling source checkout, add this in the consuming project's CMake file
before linking the plug-in:

```cmake
add_subdirectory("../Pitchwing" "${CMAKE_CURRENT_BINARY_DIR}/pitchwing")
target_link_libraries(ShiftKey PRIVATE pitchwing::pitchwing)
```

Tools and tests default off when Pitchwing is a subdirectory. At the Pitchwing
top level, tools and tests default on; `BUILD_TESTING=OFF` suppresses its tests.
`PITCHWING_BUILD_TOOLS` and `PITCHWING_BUILD_TESTS` provide explicit overrides.
The build performs no dependency downloads and adds no JUCE dependency.

Alternatively, stage a native build with `cmake --install` and use:

```cmake
find_package(pitchwing 0.1 CONFIG REQUIRED)
target_link_libraries(ShiftKey PRIVATE pitchwing::pitchwing)
```

Set `CMAKE_PREFIX_PATH` to the staged prefix. The package contains the static
library, public headers, CMake config/targets/version files, and the bundled
FFT's MIT license notice. The static library uses position-independent code
for shared-library consumers. Use the same platform, architecture, compiler,
runtime-library settings, and appropriate build configuration as the consumer;
the WSL archive cannot be linked into a Windows VST.

The standalone [`tests/consumer`](../tests/consumer/CMakeLists.txt) project
exercises both dependency routes. `MODE=source` uses `PITCHWING_SOURCE_DIR` or
the enclosing checkout; `MODE=installed` uses `find_package`. Each builds a
shared consumer linked to the static engine and an executable that checks
stereo unity delay and active pitch changes. Build and stage these checks
under `/tmp` when working in WSL. Their results belong in the development
record; they do not establish Windows/DAW readiness.

## Minimal adapter for ShiftKey's existing interface

This example belongs in the consuming project when adding a new backend. It
derives from the existing `PitchShifter` interface, whose callbacks return void,
so it preserves an inspectable status and silences failed output blocks. No
logging, engine reconstruction, or allocation occurs in the audio callbacks.
Preparation errors remain exceptions to handle outside processing.

```cpp
#include <pitchwing/LiveEngine.hpp>
#include <algorithm>
#include <cmath>
#include <memory>

class PitchwingShifter final : public PitchShifter {
public:
    void prepare(double sampleRate) override {
        engine = std::make_unique<pitchwing::LiveEngine>(
            pitchwing::LiveConfig{sampleRate, pitch});
        lastStatus = pitchwing::Status::Ok;
    }
    void reset() override {
        lastStatus = engine ? engine->reset() : pitchwing::Status::NotPrepared;
    }
    void setShiftSemitones(float st) override {
        if (!std::isfinite(st) || st < -49.0f || st > 49.0f) {
            lastStatus = pitchwing::Status::InvalidPitch;
            return;
        }
        lastStatus = engine ? engine->setPitchSemitones(st) : pitchwing::Status::Ok;
        if (lastStatus == pitchwing::Status::Ok) pitch = st;
    }
    // Unsupported capabilities: display them as unavailable for this backend.
    void setFormant(bool) override {}
    void setHighQuality(bool) override {}
    int latencySamples() const override {
        return engine ? static_cast<int>(engine->latencySamples()) : 0;
    }
    void process(const float* const* in, float* const* out, int n) override {
        if (n < 0 || in == nullptr || out == nullptr) {
            lastStatus = pitchwing::Status::InvalidBuffer;
            return;
        }
        lastStatus = engine
            ? engine->process(in[0], in[1], out[0], out[1], static_cast<std::size_t>(n))
            : pitchwing::Status::NotPrepared;
        if (lastStatus != pitchwing::Status::Ok)
            for (int channel = 0; channel < 2; ++channel)
                if (out[channel] != nullptr) std::fill_n(out[channel], n, 0.0f);
    }
    pitchwing::Status status() const noexcept { return lastStatus; }
private:
    std::unique_ptr<pitchwing::LiveEngine> engine;
    double pitch = 0.0;
    pitchwing::Status lastStatus = pitchwing::Status::NotPrepared;
};
```

This assumes ShiftKey's documented two-plane input/output contract. Read
`status()` on the same owner thread, or publish a separate atomic status for a
UI. Check rejected setters when they occur; `status()` describes the most
recent operation, not a permanent error latch. A rejected setter leaves the
previous valid pitch target active. The consumer must still add its backend
choice and object, link the library, report the queried latency, and select
clock compensation from measurements. None of those external edits is made
by this engine task.

## Validation boundary

This integration contract separates accepted controls from verified audible
quality. Stereo linkage, live automation, and CMake packaging do not establish
low-note/dyad fidelity, ±49-semitone sound quality, or a Windows real-time
deadline guarantee. Preserve the older reference renders and measurements;
compare new live-engine output independently. In particular, do not copy the
old 383-sample delay or an existing backend's `clockDelay48k` into the new
consumer adapter. Control-response measurements and native/consumer checks
are recorded with this task in [DEVELOPMENT.md](../DEVELOPMENT.md).

The [live validation report](live-validation.md) measures 48 octave-step cases
at 48 kHz. It supports a provisional `clockDelay48k = 0` for an initial trial:
0→±12 midpoint offsets are near zero after subtracting audio latency. Returns
to unity are more variable, reaching a 131.625-sample offset in this set. Keep
that limitation visible; zero is not a guarantee for every curve or low note.
