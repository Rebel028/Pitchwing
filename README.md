# Pitchwing

A reusable C++ guitar pitch-shifting engine. Low-register polyphonic quality
and 8–10 ms added DSP latency are co-primary goals. VST/plugin development is
outside this project.

`LiveEngine` provides linked stereo, live fractional pitch controls through ±49
semitones, arbitrary blocks, and about 10 ms fixed DSP delay. It follows the
separate ShiftKey project's control and buffer requirements. The original mono,
static `Engine` remains a reference port of the accepted Python experiment,
with an explicit deterministic startup policy. New output needs listening
against the preserved originals. Known DC and unresolved low-dyad defects remain;
these engines are not yet validated production replacements. See
[project scope](PROJECT.md), [development record](DEVELOPMENT.md), and
[measured DSP limitations](experiments/transport/FINDINGS.md).

See [live validation](docs/live-validation.md) and
[ShiftKey integration](docs/shiftkey-integration.md) for the consumer API and
checks. [Original native validation](docs/native-validation-results.md) retains
the static engine's listening render, parity, and timing evidence.

## Build

Requires a C++17 compiler and CMake 3.20 or newer. The small MIT-licensed FFT
dependency is bundled; the build downloads nothing. In this WSL workspace,
keep generated files on the Linux filesystem:

```sh
export PATH="/tmp/pitchwing-env/bin:$PATH"  # Approved temporary CMake installation.
cmake -S . -B /tmp/pitchwing-build -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/pitchwing-build --parallel 2
ctest --test-dir /tmp/pitchwing-build --output-on-failure
```

If a tool is missing, obtain approval before installing it. See
[native validation](docs/native-validation.md) for the offline comparison runner
and [native core](docs/native-core.md) for the processing contract.

## Use

```cpp
#include <pitchwing/LiveEngine.hpp>

pitchwing::LiveEngine engine({44100.0, -7.0}); // Prepare outside the callback.

// Both channels contain frameCount samples. Output planes must be separate.
auto status = engine.setPitchSemitones(-5.25); // Audio thread, without resetting.
if (status == pitchwing::Status::Ok)
    status = engine.process(inputLeft, inputRight, outputLeft, outputRight, frameCount);
// Check status. Float/double, in-place, and duplicated mono input are supported.
```

Link `pitchwing::pitchwing` through `add_subdirectory` or installed
`find_package(pitchwing CONFIG REQUIRED)`. Tools/tests default off when embedded;
no packages are downloaded. Query `latencySamples()` for audio/dry alignment:
439 at 44.1 kHz, 479 at 48 kHz, 959 at 96 kHz. Pitch response timing is a separate
measurement. Prepare storage before processing; processing, pitch setters,
reset, and flush allocate nothing. Instances require one caller at a time.
For offline output, allocate two planes of `tailSamples()` and call `flush()`
once; it closes the stream until reset. Reset discards history and is not a live
bypass operation. See [the full live contract](docs/live-engine.md).

The numerical reference is in `experiments/transport/`. Corpus descriptions,
render recipes, and the user's preferred `06/minus7` attack example are in
[the corpus guide](experiments/corpus/README.md). Imported research and its
measurements remain unchanged in `research/`.
