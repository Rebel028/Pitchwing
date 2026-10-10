# Building and verifying on Apple Silicon

Status: **pending verification on the user's Mac** (macOS 26.5.1, Xcode 26.2,
no developer tools installed yet). Nothing below has been run on macOS; the
commands are derived from `CMakeLists.txt` and the bundled FFT header. Please
record the outcome in `DEVELOPMENT.md`.

## 1. Tools

```sh
xcode-select --install            # Apple Clang + SDK (Command Line Tools)
brew install cmake ninja          # Homebrew; nothing else is needed
cmake --version; clang --version  # expect CMake >= 3.20, Apple clang 17.x
```

The repository downloads nothing at configure time; the FFT is bundled under
`third_party/`.

## 2. Configure, build, test

From the repository root (an out-of-tree directory such as `build-mac` is
fine on a local disk; it is not git-ignored, so keep it out of commits or add
it to `.gitignore`):

```sh
cmake -S . -B build-mac -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64
cmake --build build-mac
ctest --test-dir build-mac --output-on-failure   # 2 tests: pitchwing_engine, pitchwing_live_engine
./build-mac/pitchwing_live_probe timing            # JSON callback timing at 44.1/48/96 kHz
./build-mac/pitchwing_live_probe steps             # pitch step-response timing
```

Tools and tests are on by default at the top level. Sanitizer builds also work
with Apple Clang: add `-DPITCHWING_ENABLE_ASAN=ON -DPITCHWING_ENABLE_UBSAN=ON`
in a separate build directory (see `docs/live-validation.md` for the known
sanitizer caveats on Linux).

## 3. Compiler flags and the FFT

- `CMakeLists.txt` adds only `-Wall -Wextra -Wpedantic`; it never sets
  `-ffast-math`. `third_party/signalsmith-linear/fft.h` (line 9) refuses to
  compile with `-ffast-math` on Apple Clang 16.0.0 because that compiler
  mis-generates ARM SIMD. Xcode 26.2 ships a newer clang, so the check should
  not fire; if a consumer build adds `-ffast-math` to this library and hits the
  `#error`, remove the flag for the Pitchwing target rather than defining
  `SIGNALSMITH_IGNORE_BROKEN_APPLECLANG`.
- The header can use Apple's Accelerate framework (`SIGNALSMITH_USE_ACCELERATE`,
  line 1375), but that path includes `platform/fft-accelerate.h`, which is not
  bundled (only `fft.h` and the licence are vendored). The portable C++ FFT is
  what the tests and parity evidence cover. Do not enable Accelerate without
  vendoring that header, linking `-framework Accelerate`, and re-running the
  parity checks in `docs/native-validation.md`; no CMake option was added.
- Denormals: the engine sets no flush-to-zero or denormals-are-zero mode
  (`grep -ri denormal src include` is empty) and does not depend on one. arm64
  runs with FZ off by default. If CPU rises on long chord decays, report it;
  that would be the first denormal evidence on any platform.

## 4. What to report back

1. `sw_vers`, `clang --version`, `cmake --version`.
2. Full `ctest --output-on-failure` output (pass/fail and run times).
3. The complete JSON of `pitchwing_live_probe timing`. For orientation, the
   WSL x86-64 gcc Release numbers after step 12 were 48 kHz, block 64: mean
   345 µs per callback, and 96 kHz block 32 still missed its budget (see
   `docs/results/2026-10-10-timing-step12.txt`). They are not a target-native
   claim for either platform.
4. Any compiler warnings (MSVC reported C4723 inside `<complex>`; Apple Clang
   may show something different).
5. Optional: wall time of `pitchwing_live_render` on a real excerpt
   (`scripts/real_material_gate.py` prints `realtime_factor`; it needs the
   local `stems/` corpus and the approved Python environment).
