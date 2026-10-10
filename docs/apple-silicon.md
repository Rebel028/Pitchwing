# Building and verifying on Apple Silicon

Status: **pending verification on the user's Mac**. The user reports
macOS 26.5.1 and Xcode 26.2 with no developer tools installed yet. No command
below has been run on macOS; each is derived from `CMakeLists.txt` and the
bundled FFT header `third_party/signalsmith-linear/fft.h`. Record the outcome
in `DEVELOPMENT.md`.

## Install tools (not yet run)

```sh
xcode-select --install            # Apple Clang + SDK (Command Line Tools)
brew install cmake ninja          # Homebrew; nothing else is needed
cmake --version; clang --version  # expect CMake >= 3.20 (CMakeLists.txt line 1)
```

The compiler version Xcode 26.2 ships is not verified here; report what
`clang --version` prints. Configuration downloads nothing; the FFT is bundled
under `third_party/` (see `third_party/README.md`).

## Configure, build, and test (not yet run)

Run from the repository root. `build-mac/` is listed in `.gitignore`.

```sh
cmake -S . -B build-mac -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64
cmake --build build-mac
ctest --test-dir build-mac --output-on-failure   # 2 tests: pitchwing_engine, pitchwing_live_engine
./build-mac/pitchwing_live_probe timing            # JSON callback timing at 44.1, 48, and 96 kHz
./build-mac/pitchwing_live_probe steps             # pitch step-response timing
```

Tools and tests are on by default at the top level (`PITCHWING_BUILD_TOOLS`,
`PITCHWING_BUILD_TESTS`). The sanitizer options `PITCHWING_ENABLE_ASAN` and
`PITCHWING_ENABLE_UBSAN` accept any Clang in `CMakeLists.txt`, so a separate
build directory with both set to `ON` should configure with Apple Clang; this
has not been tried. [Live validation](live-validation.md) lists the sanitizer
caveats seen on Linux.

## Compiler flags, FFT, and denormals

These engine-side facts are verified in the repository; their macOS
consequences are untested.

- `CMakeLists.txt` adds only `-Wall -Wextra -Wpedantic` for GCC and Clang and
  never sets `-ffast-math`. `third_party/signalsmith-linear/fft.h` line 9
  refuses to compile with `-ffast-math` on Apple Clang 16.0.0 to 16.0.0.99,
  which it says mis-generates ARM SIMD. If a consumer build adds `-ffast-math`
  to this library and hits that `#error`, remove the flag for the Pitchwing
  target rather than defining `SIGNALSMITH_IGNORE_BROKEN_APPLECLANG`.
- The header can use Apple's Accelerate framework through
  `SIGNALSMITH_USE_ACCELERATE` (line 1375), but that path includes
  `./platform/fft-accelerate.h`, which is not vendored: only `fft.h` and the
  license are. The portable C++ FFT is what the tests and parity evidence
  cover. Enabling Accelerate would need that header vendored, `-framework
  Accelerate` linked, and the parity checks in
  [native validation](native-validation.md) rerun; no CMake option exists for
  it.
- The engine sets no flush-to-zero or denormals-are-zero mode
  (`grep -ri denormal src include` finds nothing) and does not depend on
  one. If CPU use rises on long chord decays, report it: it would be the first
  denormal evidence on any platform.

## Report back

1. `sw_vers`, `clang --version`, `cmake --version`.
2. The full `ctest --output-on-failure` output (pass/fail and run times).
3. The complete JSON of `pitchwing_live_probe timing`. For orientation, the
   WSL x86-64 GCC release numbers in
   `docs/results/2026-10-10-timing-step12.txt` are 48 kHz, block 64: mean
   345 µs per callback, and 96 kHz, block 32: 223 of 1500 callbacks over
   budget. Neither is a target-native claim for either platform.
4. Any compiler warnings. MSVC 14.29 reported C4723 (possible division by
   zero) inside `<complex>` and C4456 in `src/LiveEngine.cpp`; Apple Clang may
   show something different.
5. Optional: wall time of `pitchwing_live_render` on a real excerpt.
   `scripts/real_material_gate.py` prints `realtime_factor`; it needs the
   local `stems/` corpus and the approved Python environment.
