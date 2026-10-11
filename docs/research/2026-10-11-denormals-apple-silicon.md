# Denormal behaviour on Apple Silicon

Date: 2026-10-11. Status: research note resolving
`.scratch/apple-silicon/issues/04-research-denormals-apple-silicon.md`.

## Recommendation

No. The engine needs no flush to zero (FZ) or denormals are zero handling on
Apple Silicon, and no engine-side change is recommended. Two independent
reasons each suffice:

1. The engine cannot produce double-precision subnormals from any input in
   the float range, and it holds no recursive state that could decay into
   them. Every output sample is a finite sum of recent inputs times bounded
   coefficients, and every accumulator is cleared each cycle
   ([engine paths](#engine-paths-that-could-produce-subnormals)).
2. On the one Apple Silicon machine measured here (M4 Pro), subnormal
   operands and results cost the same as normal ones in scalar double, scalar
   float, and NEON float32x4, with FZ off, so even a subnormal would not
   stall ([local measurement](#local-measurement-on-an-m4-pro)).

If a consumer wants FZ anyway, the cheapest correct mitigation is one call
on the audio thread outside the engine, `fesetenv(FE_DFL_DISABLE_DENORMS_ENV)`
from the macOS SDK, or the equivalent host scoped guard such as JUCE
`ScopedNoDenormals`; it belongs in the consumer, not the engine
([mitigation](#cheapest-correct-mitigation-if-a-consumer-wants-one)).
`docs/apple-silicon.md` lines 59 to 62 stay correct: the engine sets no mode
and does not depend on one.

## AArch64 subnormal semantics and FPCR bits

Source: Arm Architecture Registers for A-profile, DDI 0601, FPCR page
(https://developer.arm.com/documentation/ddi0601/latest/AArch64-Registers/FPCR--Floating-point-Control-Register).
The developer.arm.com page renders through JavaScript and returned no text
to the fetch tool, so the verbatim quotes below were taken from Arm's
released System Register XML bundle, release 2026-03, hosted at
https://kib.kiev.ua/x86docs/ARM/XML/2026-09/SysReg_xml_A_profile_2026-03_96-2026-03_rel/xhtml/AArch64-fpcr.html;
treat that host as a copy of the primary, not as the primary.

- FZ, bit 24. With AH = 0 and FZ = 1: "denormalized single-precision and
  double-precision inputs to, and outputs from, floating-point instructions
  are flushed to zero." With AH = 1 and FZ = 1 only outputs are flushed. With
  FZ = 0 flushing is "not enabled by this control, but other factors might
  cause the input denormalized numbers to be flushed to zero." FZ covers
  single and double only.
- FZ16, bit 19, present with FEAT_FP16: "Flushing denormalized numbers to
  zero control bit on half-precision data-processing instructions." It does
  not affect single or double arithmetic.
- AH, bit 1, and FIZ, bit 0, present with FEAT_AFP. AH: "Alternate Handling.
  Controls alternate handling of floating-point numbers." FIZ: "Flush Inputs
  to Zero. Controls whether single-precision, double-precision and BFloat16
  input operands that are denormalized numbers are flushed to zero." Under
  FEAT_AFP, input flushing is FIZ and output flushing is FZ when AH = 1. The
  M4 Pro used below reports `hw.optional.arm.FEAT_AFP = 1`, so these bits
  exist on it; macOS leaves them clear (next section).
- Advanced SIMD honours FPCR in AArch64. The A64 `FADD (vector)` operation
  pseudocode computes each lane with `FPAdd(element1, element2, FPCR())`
  (ISA XML, `fadd_advsimd.xml`, same bundle), the same control as scalar
  instructions. In AArch32, by contrast, the FPSCR page states for FZ: "The
  value of this bit controls only scalar floating-point arithmetic. Advanced
  SIMD arithmetic always uses the Flush-to-zero setting, regardless of the
  value of the FZ bit" (`AArch32-fpscr.html`, same bundle), and the AArch32
  `VADD` pseudocode selects `StandardFPCR()`, which forces FZ = 1 and DN = 1,
  for the Advanced SIMD form. The AArch32 always flush behaviour therefore
  does not carry over to AArch64 code, and there is no separate NEON flush
  mode to configure on Apple Silicon.
- Reset value. Every FPCR field on the page "On a Warm reset, this field
  resets to an architecturally UNKNOWN value", so the value a user thread
  sees is whatever the operating system installs.
- Cost of subnormals. The architecture makes no statement that subnormal
  operands are handled without a trap or assist; the Arm ARM lists only the
  implementation options for floating-point support (with or without
  exception trapping, or none). Subnormal cost is a property of each
  implementation, which is why the measurement below was made.

## macOS thread default

XNU installs FPCR = 0 for every new 64-bit thread. In the latest published
XNU (tag xnu-12377.121.6, https://github.com/apple-oss-distributions/xnu):

- `osfmk/arm64/proc_reg.h` lines 852 to 876 define `FPCR_FZ_SHIFT 24`,
  `FPCR_DN_SHIFT 25`, `FPCR_FZ (1 << FPCR_FZ_SHIFT)`, `FPCR_DN (1 <<
  FPCR_DN_SHIFT)`, `FPCR_DEFAULT (0)`, and `FPCR_DEFAULT_32 (FPCR_DN|FPCR_FZ)`.
  No AH or FIZ macro exists in that file.
- `osfmk/arm64/status.c` lines 2071 to 2089, `machine_thread_state_initialize`,
  set `context->ns.ns_64.fpcr = FPCR_DEFAULT` for `ARM_NEON_SAVED_STATE64`
  and `ns_32.fpcr = FPCR_DEFAULT_32` otherwise; it is called from
  `machine_thread_create` (`osfmk/arm64/pcb.c` line 647). So a 64-bit thread
  starts with FZ = 0, DN = 0, AH = 0, FIZ = 0, and only a 32-bit thread gets
  flush to zero and default NaN.
- `osfmk/arm64/status.c` lines 2127 to 2150, `machine_thread_dup`, copies the
  whole NEON save area including `fpcr` from the parent, so a forked process
  inherits the forking thread's FPCR. Whether libpthread copies FPCR from the
  creating thread at `pthread_create` was not verified in source; the probe
  below observed FPCR = 0 on a new pthread created from a thread with
  FPCR = 0, which does not distinguish the two.
- `osfmk/arm64/proc_reg.h` lines 3543 to 3551, macro `SANITIZE_FPCR`, resets
  FPCR to `FPCR_DEFAULT` on kernel entry when it differs, which is why the
  kernel itself never runs with a user FZ setting.

The probe below confirms the user-visible result on macOS 26.5.1: `mrs fpcr`
reads 0 on the main thread and on a fresh pthread, and `fegetenv` reports
`__fpcr = 0`.

## Apple documentation

No first-party Apple document states the subnormal performance of M-series
CPU cores or the default denormal mode. The documentation JSON behind
"Porting your audio code to Apple silicon", "Writing ARM64 code for Apple
platforms", "Porting your macOS apps to Apple silicon", and the vDSP
reference contains no match for denormal, subnormal, flush to zero, FPCR, or
fenv (checked by the source-gathering agent on 2026-10-11 via
`developer.apple.com/tutorials/data/documentation/<path>.json`). The closest
Apple statements are:

- Apple Developer Forums thread 723778, "FCPR on Apple Silicon", an Apple
  staff reply of August 2023: "The standard C APIs to control floating-point
  behavior are described in man 3 fenv. For Apple silicon, please use Xcode
  14.3+ where support was officially added"
  (https://developer.apple.com/forums/thread/723778).
- The SDK header `fenv.h` itself, cited in the mitigation section, which is
  the only Apple text describing `FE_DFL_DISABLE_DENORMS_ENV` for arm64;
  Apple's published Libm source (https://github.com/apple-oss-distributions/Libm,
  tag Libm-2026, `Source/fenv.h` line 29 and `Source/ARM/fenv.h`) covers only
  32-bit `__arm__` and defines no arm64 variant.
- Metal only: forum thread 844598 quotes the Metal Shading Language
  specification that denormals "may be flushed to zero" on the GPU
  (https://developer.apple.com/forums/thread/844598). This does not describe
  the CPU.

## Apple M-series subnormal cost

Verified for M4: subnormal arithmetic costs the same as normal arithmetic.
Unverified for M1, M2, and M3: no published measurement was found, only
anecdotes. The evidence, labelled by kind:

- Published, secondary, reproducible: Daniel Lemire, "Subnormal
  floating-point numbers are expensive... on Intel processors", 2026-09-15,
  https://lemire.me/blog/2026/09/15/subnormal-floating-point-numbers-are-expensive-on-intel-processors/,
  code at
  https://github.com/lemire/Code-used-on-Daniel-Lemire-s-blog/tree/master/2026/09/15.
  On an Apple M4 Max with Apple clang 17 at `-O3 -march=native`, double
  precision, nanoseconds per element, normal versus subnormal: multiply 0.06
  versus 0.06, add 0.12 versus 0.12, divide 0.11 versus 0.11, normal input
  with subnormal output 0.06 versus 0.06, dependent chain 0.72 versus 0.75.
  The same post measures a multiply at 0.17 versus 8.35 ns on Intel Granite
  Rapids. The post does not state the FZ setting; the raw log in the
  repository covers the Intel run, and the Apple figures appear only in the
  post's table.
- Local, this note, primary for this machine: the M4 Pro probe below,
  0.78 ns per dependent FMA for normal and subnormal operands alike, with
  the FZ state read from FPCR before and after.
- Anecdotal, secondary, no code: KVR Audio thread 573073, "Are denormals a
  problem on arm64/M1 systems?", 2021,
  https://www.kvraudio.com/forum/viewtopic.php?t=573073, where one poster
  reports no measurable difference on an M1 and a 17 times speedup from FZ
  on x86. A reply in the same thread claiming that M1 flushes to zero by
  default is contradicted by the XNU default and the FPCR read above.
- Non-Apple Arm, secondary, with code: https://mu.krj.st/denormal/ (2021,
  Raspberry Pi 4) reports a decay loop at 0.26 s with and without FZ against
  3.46 s versus 0.11 s on an x86 laptop.
- Not covering the question: Dougall Johnson's Firestorm instruction tables
  (https://dougallj.github.io/applecpu/firestorm.html) give FADD latency 3
  and throughput 0.25 cycles without any operand-dependent note.

One Apple header is relevant to library calls rather than to the CPU: the
macOS 26 SDK `vForce.h` (Accelerate, vecLib) line 32 states "vForce may
treat some or all denormal numbers as zero" and line 39 that the treatment
"will vary across different microarchitectures and versions". The engine
does not call vForce or vDSP (`docs/apple-silicon.md`, Accelerate paragraph).

## Host and framework behaviour

Summary: no host or framework examined sets FZ on the engine's behalf on
macOS arm64 by default, and none documents the render thread's FPCR; the
ones that offer FZ offer it as a scoped guard the plug-in opts into.

- JUCE (primary, source as of 2026-10-11 master):
  `modules/juce_audio_basics/buffers/juce_FloatVectorOperations.cpp`
  (https://raw.githubusercontent.com/juce-framework/JUCE/master/modules/juce_audio_basics/buffers/juce_FloatVectorOperations.cpp)
  reads FPCR with `mrs %0, fpcr` (line 1451) and writes it with `msr fpcr,
  %0` (line 1479); `disableDenormalisedNumberSupport` (lines 1511 to 1527)
  and `ScopedNoDenormals` (lines 1544 to 1563) OR in `(1 << 24 /* FZ */)` on
  Arm (lines 1517 and 1550) and the destructor restores the saved register.
  The header (`juce_FloatVectorOperations.h` lines 205 to 238) says "On arm
  CPUs this will enable flush to zero mode." The AU, AUv3, VST3, AAX, LV2,
  and standalone wrappers under `juce_audio_plugin_client` contain no
  denormal handling, so a JUCE plug-in gets FZ only if it constructs the
  guard itself.
- Steinberg VST3 SDK (primary, GitHub code search of `steinbergmedia`
  repositories): no occurrence of FLUSH_ZERO, fpcr, or denormal in the SDK
  or hosting code; the only hits are the mda sample plug-ins trapping
  denormals in software, for example
  `samples/vst/mda-vst3/source/mdaDelayProcessor.cpp` line 139. Not found.
- Apple CoreAudio and Audio Units: no Apple statement about the render
  thread's FPCR was found. "Porting your audio code to Apple silicon"
  (https://developer.apple.com/documentation/apple-silicon/porting-your-audio-code-to-apple-silicon)
  does not mention floating-point modes. A 2014 Intel-era claim in Mozilla
  bug 1027864 (https://bugzilla.mozilla.org/show_bug.cgi?id=1027864) that
  CoreAudio sets FTZ and DAZ cites a mailing-list post whose archive could
  not be retrieved; it is unverified and predates Apple Silicon.
- Ardour (primary, source): `libs/pbd/fpu.cc`
  (https://raw.githubusercontent.com/Ardour/ardour/master/libs/pbd/fpu.cc)
  returns early on non-Intel architectures and detects flush modes only
  through x86 CPUID and MXCSR, so Ardour on arm64 sets nothing.
- Cockos WDL (primary, source): `WDL/denormal.h` lines 48 to 70
  (https://raw.githubusercontent.com/justinfrankel/WDL/main/WDL/denormal.h)
  defines an arm64 `WDL_denormal_ftz_scope` that sets bit 24 through
  `mrs`/`msr fpcr`. Whether REAPER applies it on its render threads is not
  public.
- Chromium and WebKit audio (primary, source): `DenormalDisabler.h`
  (https://chromium.googlesource.com/chromium/blink/+/HEAD/Source/platform/audio/DenormalDisabler.h)
  sets bit 24 for the scope of a render quantum and restores it.

The practical consequence: a host process on macOS arm64 runs the engine
with FPCR = 0, that is full IEEE 754 subnormal arithmetic, unless the plug-in
layer around the engine sets FZ itself.

## Compiler behaviour

Apple clang does not set FZ at program start, with or without `-ffast-math`.
Clang links `crtfastmath.o` under `-ffast-math` only when the toolchain can
find that object (`clang/lib/Driver/ToolChain.cpp`,
`addFastMathRuntimeIfAvailable`, lines 1854 to 1896 on main,
https://raw.githubusercontent.com/llvm/llvm-project/main/clang/lib/Driver/ToolChain.cpp),
and only the GNU, Cygwin, MinGW, and Solaris toolchain drivers call it; the
Darwin driver (`clang/lib/Driver/ToolChains/Darwin.cpp`) contains no
reference to fastmath, crtfastmath, or DAZ. The object itself comes from
GCC's libgcc (`libgcc/config/aarch64/crtfastmath.c` lines 24 to 35,
https://raw.githubusercontent.com/gcc-mirror/gcc/master/libgcc/config/aarch64/crtfastmath.c,
which sets `0x1000000` in FPCR from a constructor), which is what Linux
arm64 builds get. The source-gathering agent confirmed on this Mac that the
SDK and toolchain ship no `crtfastmath*` object and that a probe built with
`-O2`, `-O2 -ffast-math`, and `-Ofast` prints FPCR = 0 and preserves a
float subnormal product in all three cases. This matters to the engine only
as a boundary condition: `CMakeLists.txt` never adds `-ffast-math`
(`docs/apple-silicon.md` lines 45 to 50), and even a consumer build that
did would not change FPCR on macOS.

## Engine paths that could produce subnormals

The engine computes in double. `src/LiveEngine.cpp` declares
`using Complex = std::complex<double>` and
`using Transform = signalsmith::linear::SplitFFT<double>` (lines 33 to 34),
and every state buffer is `std::vector<double>` or `std::vector<Complex>`
(lines 1204 to 1231). The `float` overloads of `process` and `flush` convert
at the boundary only (`include/pitchwing/LiveEngine.hpp`; the templated
`process` at `LiveEngine.cpp:700` casts the double result per sample at
lines 751 to 752).

A double is subnormal below $2^{-1022} \approx 2.2 \times 10^{-308}$ and a
float below $2^{-126} \approx 1.2 \times 10^{-38}$ (IEEE 754-2019 section
3.3, parameters $emin$ and $p$ for binary32 and binary64; the probe below
prints a double result of $1.5 \times 10^{-310}$, confirming the range). The
input contract bounds samples at $10^{30}$ but has no lower bound
(`docs/live-engine.md`, sample validation row; `LiveEngine.cpp:714-722`).

The ticket names three candidate paths. Each is examined against the code.

### Decaying chord tails

The engine has no decay of its own. The signal path per sample
(`processSample`, `LiveEngine.cpp:759-810`) is: write the input into the
`history` ring (lines 760 to 763), run a finite FIR into the `decimated`
ring every `decimation` samples (lines 765 to 778), once per hop analyse a
windowed frame by FFT (`prepareFrame`, lines 1013 to 1033), accumulate
region spectra into `termSpectrum` (`accumulateRegion`, lines 1075 to 1160),
inverse transform and overlap-add into the `output` ring (`renderTerm`,
lines 1163 to 1182), and read one output sample, zeroing the ring slot after
reading it (lines 797 to 799). `termSpectrum` is cleared after each inverse
transform (line 1168). No sample is fed back: there is no IIR filter,
one-pole smoother, or exponential envelope anywhere in the audio path
(`grep -n -i 'floor\|1e-\|decay\|recur\|exp(' src/LiveEngine.cpp` finds
only constants, tolerance checks, and the constructor's Bessel series).

Consequently a decaying chord decays only because the input decays. Once the
input is exactly zero for $N$ samples, the analysis frame is all zero, the
peak search finds `largest == 0.0` and returns with no regions
(`findRegions`, lines 826 to 829), the DC term is zero, and the output ring
drains to exact zeros within `tail` samples (`tail = N + D + H`,
`docs/live-engine.md`, geometry formula). The engine cannot prolong a quiet
tail beyond `tailSamples()`.

The only decaying recurrence in either engine is the `rotation` slew on a
unity frame (`LiveEngine.cpp:871-880`): `rotation -= clamp(rotation, -slew,
slew)`, which subtracts a fixed step and reaches exactly 0.0, so it never
shrinks geometrically. The static engine's `modulation *= step`
(`src/Engine.cpp:377`) rotates a unit-magnitude complex and is re-anchored
every 64 samples (line 369); its magnitude never approaches zero.

### Window edges

Both windows are a sine rise to the pivot and a cosine fall after it
(`LiveEngine.cpp:174-184`). Index 0 is `sin(0)`, an exact zero, and every
other coefficient is at least the first sine sample. At 48 kHz, $N = 2048$
(`fastSizeAbove(2048)` returns 2048, `third_party/signalsmith-linear/fft.h:333-340`;
geometry at `LiveEngine.cpp:144-149`) and $L/2 = 192$, so the smallest
nonzero analysis coefficient is $\sin(\pi/3712) \approx 8.5 \times 10^{-4}$
and the last cosine sample is about $8.2 \times 10^{-3}$. Multiplying by a
coefficient of $10^{-4}$ or larger moves a normal double into the subnormal
range only if the input is already below about $2 \times 10^{-304}$, which no
float-range or ordinary double-range signal reaches. The synthesis taper
(`accumulateRegion`, lines 1088 to 1098) is 1.0 or a raised cosine that can
be small near the Nyquist guard, but it multiplies spectrum bins of the same
order as the input, with the same conclusion.

### Recurrences and small factors in the spectral path

- `hopArea` sums `ratioMinusOne` over one hop and is reset each frame
  (lines 783 to 787); it is a sum, not a product.
- The Taylor weights `weight[p] = weight[p-1] * (i epsilon / p)` for
  `taylorTerms = 4` (line 30; lines 1106 to 1109) shrink by $\epsilon/p$ per
  term, where $\epsilon$ is the sub-bin remainder of the shift `delta`. The
  smallest nonzero `ratioMinusOne` that `std::exp2(semitones / 12.0) - 1.0`
  can return is one ulp of 1.0, $2.2 \times 10^{-16}$ (reached near
  $2 \times 10^{-15}$ semitones; `LiveEngine.cpp:149` and `:1306`), so
  $\epsilon$ is either exactly 0 or at least about $\omega \times 10^{-16}$,
  and `weight[3]` stays far above $10^{-308}$ for any region frequency the
  peak search can report. An exactly zero $\epsilon$ gives exactly zero
  weights, not subnormals.
- Energy and residual sums use `std::norm`, which squares magnitudes
  (lines 281 to 308, 493 to 561, 1119 to 1128). Squaring reaches the
  subnormal range only below $1.5 \times 10^{-154}$, again unreachable from
  float-range input.
- The explicit floors (`1e-300` in the Cholesky and log paths,
  `LiveEngine.cpp:537`, `Engine.cpp:269-271`; `1e-12` determinant and
  flatness checks; `1e-4` and `1e-3` relative peak and residual floors) are
  tolerance constants compared against or added to normal values; none
  creates a subnormal operand.
- The constructor's Bessel series (`LiveEngine.cpp:208-215`) runs 49 terms
  with $x = \beta \approx 8.96$; the last term is about $10^{-62}$, normal,
  and the series runs once at construction, not on the audio thread.

### Float output and consumer-side subnormals

When a consumer calls the `float` overload, the per-sample cast
(`LiveEngine.cpp:751-752`) can produce a float subnormal whenever the double
result lies between $1.4 \times 10^{-45}$ and $1.2 \times 10^{-38}$. The
engine applies no limiter or gain (`docs/live-engine.md`, consumer
contract), so this happens only when the input signal itself sits in that
range, for example an upstream reverb or filter tail in float, and it lasts
at most `tailSamples()` after the input leaves that range. Whether the cast
or the consumer's later float arithmetic on those values stalls is the
consumer's platform question, answered by the sections above for Apple
Silicon: it does not stall there.

## Local measurement on an M4 Pro

This is a measurement made for this note, not a published source. Machine:
Apple M4 Pro (`sysctl machdep.cpu.brand_string`), macOS 26.5.1 build 25F80
(`sw_vers`), Apple clang 21.0.0 (clang-2100.1.1.101), SDK 26.5,
`hw.optional.arm.FEAT_AFP = 1`. Core type was not pinned. The probe source
is reproduced in full in the appendix; build and run with
`clang++ -std=c++17 -O2 denorm_probe.cpp -o denorm_probe && ./denorm_probe`.

What the probe does: reads FPCR with `mrs x, fpcr` on the main thread and on
a fresh `pthread`, prints the `__fpcr` word of `FE_DFL_DISABLE_DENORMS_ENV`,
then for FZ off and FZ on times a throughput loop `c[i] = a[i] * 0.5 + b[i]`
over 16 KiB arrays whose operands and results stay subnormal on every pass,
and a dependent latency chain `x = x * 0.5 + a` whose fixed point $2a$ is
subnormal when $a$ is. Each loop runs in double, float, and explicit NEON
`float32x4` (`vfmaq_f32`). Best of five.

Second run output, verbatim:

```
fpcr main thread            = 0x0
fpcr new pthread            = 0x0
fegetenv default __fpcr     = 0x0
FE_DFL_DISABLE_DENORMS_ENV  = __fpcr 0x1000000
FZ=0  normal    throughput: double 0.108  float 0.061  neon-f32 0.114 ns/elem  (c = 0.0015 / 0.0015)
FZ=0  normal    latency:    double 0.782  float 0.779  neon-f32 1.086 ns/op    (x = 0.002 / 0.002)
FZ=0  subnormal throughput: double 0.085  float 0.044  neon-f32 0.102 ns/elem  (c = 1.5e-310 / 1.49999e-40)
FZ=0  subnormal latency:    double 0.780  float 0.781  neon-f32 1.087 ns/op    (x = 2e-310 / 1.99999e-40)
fpcr after fesetenv(FE_DFL_DISABLE_DENORMS_ENV) = 0x1000000
FZ=1  normal    throughput: double 0.084  float 0.048  neon-f32 0.102 ns/elem  (c = 0.0015 / 0.0015)
FZ=1  normal    latency:    double 0.789  float 0.783  neon-f32 1.088 ns/op    (x = 0.002 / 0.002)
FZ=1  subnormal throughput: double 0.087  float 0.043  neon-f32 0.102 ns/elem  (c = 0 / 0)
FZ=1  subnormal latency:    double 0.780  float 0.777  neon-f32 1.085 ns/op    (x = 0 / 0)
fpcr after fesetenv(FE_DFL_ENV) = 0x0
```

Reading: the dependent chain costs 0.78 ns per double or float FMA and
1.09 ns per NEON FMA whether the operands are normal or subnormal and whether
FZ is off or on; the differences are under 2 percent. The throughput rows
agree except that the first row of each run is slower, which a first run
also showed (0.211, 0.093, 0.176) and which is consistent with clock ramp on
the first timed loop rather than with the operand class, since it is the
normal case. The printed results confirm that FZ off really produced
subnormal results ($1.5 \times 10^{-310}$, $1.5 \times 10^{-40}$) and FZ on
flushed them to 0. FPCR reads 0 on both the main thread and a new pthread,
and `FE_DFL_DISABLE_DENORMS_ENV` sets exactly bit 24.

Limits: one machine, one core type not controlled, two runs, a synthetic
loop; no run of the engine itself with subnormal input was made, because the
engine analysis above shows no path that would exercise one.

## Cheapest correct mitigation if a consumer wants one

The engine needs none. A consumer that wants FZ for its own float chain, or
for parity with other platforms, sets it on the audio thread around its
callback and leaves the engine untouched:

- Portable Apple SDK call: `fesetenv(FE_DFL_DISABLE_DENORMS_ENV)` at the
  start of the callback and `fesetenv(FE_DFL_ENV)` at the end. The SDK
  header defines the macro for `__arm64__` at
  `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/fenv.h`
  lines 170 to 185 as the default environment with the FZ bit of FPCR set,
  and warns at lines 176 to 183 that the mode is not IEEE 754 compliant,
  that the math and other system libraries "are not guaranteed to do the
  right thing" in it, and that it should not be used "unless you have
  established that denormals are the source of measurable performance
  problems". The probe above shows the call sets FPCR to `0x1000000` and
  `FE_DFL_ENV` restores 0.
- Host frameworks offer the same as a scoped guard
  ([host behaviour](#host-and-framework-behaviour)).

Why not in the engine: FPCR is per thread state shared with the caller's
other code and with system libraries; the engine contract takes no lock and
owns no thread (`docs/live-engine.md`, consumer contract), so it cannot know
whether the caller's other code tolerates FZ, and the SDK comment above puts
that decision with whoever establishes a measured problem. The engine does
not depend on either mode, so either choice by the consumer is safe for it.

## Appendix: probe source

```cpp
// Subnormal probe for Apple Silicon.
// Build: clang++ -std=c++17 -O2 denorm_probe.cpp -o denorm_probe
// Reads FPCR on the main thread and a new pthread, checks what
// FE_DFL_DISABLE_DENORMS_ENV sets, then times, with FZ off and FZ on:
//   throughput: c[i] = a[i] * 0.5 + b[i] over L1-resident arrays (operands and
//               results stay subnormal every pass because nothing decays),
//   latency:    x = x * 0.5 + a, a dependent chain whose fixed point 2a is
//               subnormal when a is.
// Each is run for double, float, and explicit NEON float32x4. Best of 5.
#include <algorithm>
#include <arm_neon.h>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <fenv.h>
#include <pthread.h>
#include <vector>

static uint64_t readFpcr() { uint64_t v; __asm__ volatile("mrs %0, fpcr" : "=r"(v)); return v; }
static void* threadBody(void* out) { *static_cast<uint64_t*>(out) = readFpcr(); return nullptr; }

template <typename F> static double timeNs(std::size_t ops, F&& f) {
    auto best = 1e300;
    for (int rep = 0; rep < 5; ++rep) {
        const auto t0 = std::chrono::steady_clock::now();
        f();
        const auto t1 = std::chrono::steady_clock::now();
        best = std::min(best, std::chrono::duration<double, std::nano>(t1 - t0).count() / double(ops));
    }
    return best;
}

int main() {
    std::printf("fpcr main thread            = 0x%llx\n", (unsigned long long)readFpcr());
    uint64_t threadFpcr = ~0ull; pthread_t t;
    pthread_create(&t, nullptr, threadBody, &threadFpcr); pthread_join(t, nullptr);
    std::printf("fpcr new pthread            = 0x%llx\n", (unsigned long long)threadFpcr);
    fenv_t env; fegetenv(&env);
    std::printf("fegetenv default __fpcr     = 0x%llx\n", (unsigned long long)env.__fpcr);
    std::printf("FE_DFL_DISABLE_DENORMS_ENV  = __fpcr 0x%llx\n", (unsigned long long)(*FE_DFL_DISABLE_DENORMS_ENV).__fpcr);

    constexpr std::size_t N = 2048; constexpr int iters = 5000;   // 16 KiB double arrays
    constexpr std::size_t chain = 50'000'000;
    std::vector<double> ad(N), bd(N), cd(N);
    std::vector<float> af(N), bf(N), cf(N);
    volatile double sinkD = 0; volatile float sinkF = 0;
    auto run = [&](const char* label) {
        for (int modeSub = 0; modeSub < 2; ++modeSub) {
            const double vd = modeSub ? 1e-310 : 1e-3;   // 1e-310 is a double subnormal
            const float vf = modeSub ? 1e-40f : 1e-3f;   // 1e-40 is a float subnormal
            for (std::size_t i = 0; i < N; ++i) { ad[i] = vd; bd[i] = vd; cd[i] = 0; af[i] = vf; bf[i] = vf; cf[i] = 0; }
            auto d = timeNs(N * (std::size_t)iters, [&] {
                for (int k = 0; k < iters; ++k) for (std::size_t i = 0; i < N; ++i) cd[i] = ad[i] * 0.5 + bd[i];
                sinkD = cd[N - 1];
            });
            auto f = timeNs(N * (std::size_t)iters, [&] {
                for (int k = 0; k < iters; ++k) for (std::size_t i = 0; i < N; ++i) cf[i] = af[i] * 0.5f + bf[i];
                sinkF = cf[N - 1];
            });
            auto v = timeNs(N * (std::size_t)iters, [&] {
                const float32x4_t half = vdupq_n_f32(0.5f);
                for (int k = 0; k < iters; ++k) for (std::size_t i = 0; i < N; i += 4) {
                    vst1q_f32(&cf[i], vfmaq_f32(vld1q_f32(&bf[i]), vld1q_f32(&af[i]), half));
                }
                sinkF = cf[N - 1];
            });
            std::printf("%-5s %-9s throughput: double %.3f  float %.3f  neon-f32 %.3f ns/elem  (c = %g / %g)\n",
                        label, modeSub ? "subnormal" : "normal", d, f, v, (double)sinkD, (double)sinkF);
            auto ld = timeNs(chain, [&] {
                volatile double a0 = vd; const double a = a0; double x = 0;
                for (std::size_t i = 0; i < chain; ++i) x = x * 0.5 + a;
                sinkD = x;
            });
            auto lf = timeNs(chain, [&] {
                volatile float a0 = vf; const float a = a0; float x = 0;
                for (std::size_t i = 0; i < chain; ++i) x = x * 0.5f + a;
                sinkF = x;
            });
            auto lv = timeNs(chain, [&] {
                volatile float a0 = vf; const float32x4_t a = vdupq_n_f32(a0), half = vdupq_n_f32(0.5f);
                float32x4_t x = vdupq_n_f32(0);
                for (std::size_t i = 0; i < chain; ++i) x = vfmaq_f32(a, x, half);
                sinkF = vgetq_lane_f32(x, 0);
            });
            std::printf("%-5s %-9s latency:    double %.3f  float %.3f  neon-f32 %.3f ns/op    (x = %g / %g)\n",
                        label, modeSub ? "subnormal" : "normal", ld, lf, lv, (double)sinkD, (double)sinkF);
        }
    };
    run("FZ=0");
    fesetenv(FE_DFL_DISABLE_DENORMS_ENV);
    std::printf("fpcr after fesetenv(FE_DFL_DISABLE_DENORMS_ENV) = 0x%llx\n", (unsigned long long)readFpcr());
    run("FZ=1");
    fesetenv(FE_DFL_ENV);
    std::printf("fpcr after fesetenv(FE_DFL_ENV) = 0x%llx\n", (unsigned long long)readFpcr());
    return 0;
}
```
