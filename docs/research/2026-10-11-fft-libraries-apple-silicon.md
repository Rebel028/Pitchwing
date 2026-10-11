# FFT backends for the engine on Apple Silicon

Date: 2026-10-11. Scope: ticket 03 of the Apple Silicon charting session.
Input to ticket 10 (callback budget verdict).

## Conclusion

Accelerate is not the only usable FFT, but it is the cheapest one to try if
ticket 10 finds the callback budget missed. Two candidates offer a
double-precision, vectorised AArch64 transform at the engine's sizes under an
MIT-compatible licence: Apple Accelerate through the Signalsmith platform
header, and the marton78 fork of pffft with its double NEON backend. No
primary source publishes a timing for either at the engine's sizes (complex
2048 and 1024, double) on an M-series chip, so their order is a judgment,
not a measurement. Every other surveyed library is excluded by precision
(muFFT, Ne10), by licence (FFTW, KFR), or by having no vectorised double
path and therefore no expected speed-up over the shipped scalar code
(pocketfft, KissFFT, Ooura). Swapping any backend, Accelerate included,
changes the output at rounding level and reopens the parity run.

Recommendation for ticket 10:

1. If the budget is met on the M4 Pro, record Accelerate and every other
   backend as out of scope, as the user's rule requires.
2. If it is missed, first measure what share of a callback the transforms
   take; a backend swap only helps that share.
3. If the share justifies it, prototype Accelerate first: vendor the 340 line
   `platform/fft-accelerate.h`, add an Apple-only CMake option that defines
   `SIGNALSMITH_USE_ACCELERATE` and links `-framework Accelerate`, rerun
   `pitchwing_live_probe timing` and the parity harness. Keep pffft double as
   the portable second candidate if a cross-platform gain is wanted.

## What the engine asks of its FFT

Every fact in this section comes from the repository at the commit this note
was written against.

- Precision is double. Both engines alias `Complex` to
  `std::complex<double>` and instantiate
  `signalsmith::linear::SplitFFT<double>`
  (`src/Engine.cpp:23`, `src/Engine.cpp:391`, `src/LiveEngine.cpp:33-34`).
  The float `process` overloads convert at the boundary
  (`include/pitchwing/Engine.hpp:46-47`, `include/pitchwing/LiveEngine.hpp:32-35`).
- The transforms are complex to complex on interleaved `std::complex<double>`
  buffers of length `n`, out of place: `src/Engine.cpp:316` (forward),
  `src/Engine.cpp:328` and `src/Engine.cpp:365` (inverse);
  `src/LiveEngine.cpp:1021` (forward, per channel), `src/LiveEngine.cpp:1032`
  (long forward, per channel when needed), `src/LiveEngine.cpp:1169`
  (inverse, one per Taylor term and channel). The step 12 timing record
  describes the synthesis as 2x4 Taylor-term IFFTs per hop
  (`docs/results/2026-10-10-timing-step12.txt:1`).
- Offline engine sizes: defaults `analysisSize = 2048`, `synthesisSize = 384`,
  `hop = 96` (`include/pitchwing/Engine.hpp:13-15`); validation allows any
  even `N` with `65536 >= N >= L >= 8` and `hop` dividing `L` with at least two
  overlaps (`src/Engine.cpp:35-45`).
- Live engine sizes are derived from the sample rate
  (`src/LiveEngine.cpp:144-153`): `hop = floor(rate * 0.002)`,
  `length = 4 * hop`, `n = fastSizeAbove(ceil(rate * 2048 / 48000))`,
  `nLong = 4 * n`, `nDecimated = nLong / decimation` where `decimation` is the
  largest factor with `factor * 6000 <= rate` that divides `nLong`
  (`src/LiveEngine.cpp:59-66`). Evaluating `fastSizeAbove`
  (`third_party/signalsmith-linear/fft.h:333-340`) gives:

  | Rate | hop | n | nLong | decimation | nDecimated |
  |---|---|---|---|---|---|
  | 44100 | 88 | 2048 | 8192 | 4 | 2048 |
  | 48000 | 96 | 2048 | 8192 | 8 | 1024 |
  | 96000 | 192 | 4096 | 16384 | 16 | 1024 |

  All live and default offline sizes are powers of two.
- The shipped `SplitFFT` folds every factor of two into its inner
  power-of-two FFT (`third_party/signalsmith-linear/fft.h:346-357`:
  `maxSplit` is 1 and `minInnerSize` is 32 (`fft.h:330-331`) for the engine's
  `splitComputation = false` instantiation), so for a power of two the plan
  is a single `passthrough` step (`fft.h:396-397`) and the whole transform is
  `Pow2FFT<double>`, which forwards to `SimpleFFT<double>`
  (`fft.h:289-323`, `fft.h:105-161`). A replacement therefore only needs to
  specialise `Pow2FFT<double>`, which is exactly what the Signalsmith
  platform headers do (`fft.h:1367-1384`).
- The shipped header contains no SIMD intrinsics: a search for
  `__ARM_NEON`, `SSE`, `AVX` and `xsimd` hits only the `SIGNALSMITH_USE_XSIMD`
  include guard at `fft.h:1381`; the complex multiply and interleave helpers
  are plain loops (`fft.h:21-60`). Vectorisation is whatever the compiler
  auto-vectorises. The header refuses `-ffast-math` on Apple Clang
  16.0.0.x because of mis-generated ARM SIMD (`fft.h:9-10`).
- Real-time safety of the shipped path: all buffers are sized in `resize`
  (`fft.h:112-118`, `fft.h:346-365`) and the transform steps operate on those
  members (`fft.h:481-560`). No allocation happens in `fft` or `ifft`.
- Parity contract: the native engine is compared with the Python reference at
  an absolute float64 tolerance of $10^{-10}$ per output sample
  (`docs/native-validation.md:103`) and "the harness never widens its
  tolerance for FFT or peak-choice differences"
  (`docs/native-validation.md:115`). The offline engine guards one known
  rounding hazard explicitly: a flat spectrum is detected with a $10^{-12}$
  relative tolerance so FFT rounding cannot "invent dozens of peaks"
  (`src/Engine.cpp:239-243`).
- The vendored header is byte-identical to upstream `main` as of this note:
  `cmp` of `third_party/signalsmith-linear/fft.h` against
  `https://raw.githubusercontent.com/Signalsmith-Audio/linear/main/fft.h`
  reported no difference on 2026-10-11, and the GitHub API reports the
  repository's last push as 2026-10-04 (`https://api.github.com/repos/Signalsmith-Audio/linear`).
  The pinned commit is `146b26f91b48835d665fa0498d64d9617818d27a`
  (`third_party/README.md:8-9`).
- Existing timing evidence is WSL x86-64 only: 48 kHz block 64 mean 345 us
  per callback, 96 kHz block 32 with 223 of 1500 callbacks over budget
  (`docs/results/2026-10-10-timing-step12.txt:6-8`). It says nothing about
  the FFT share of a callback.

## Ranked table

Ranking order follows the user's rule: expected speed-up at the engine's
sizes first, then licence, then footprint. "Bitwise" says whether the output
would match the shipped FFT exactly; "no" means the parity harness must be
rerun. Sources for each row are in the per-candidate sections below.

| Rank | Candidate | Licence | Double | AArch64 NEON | Sizes 1024/2048/4096 | No allocation in transform | Vendoring footprint | Bitwise | Expected speed-up |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Accelerate vDSP via Signalsmith `platform/fft-accelerate.h` | MIT header; Accelerate is a macOS system framework | Yes (`vDSP_fft_zipD`) | Apple internal; not documented | Yes (powers of two) | Wrapper: yes. vDSP execute: not documented to allocate | 340 line header plus link flag; Apple only | No | Unknown; no public number |
| 2 | pffft, marton78 fork, double build | BSD-like (NCAR/UCAR) | Yes (`pffftd_*`) | Yes, native `float64x2_t` pairs | Yes (`2^a 3^b 5^c`, `a >= 5`) | Yes (caller or stack work area) | About 110 KB of C: `pffft_double.c`, `pffft_common.c`, `pffft_priv_impl.h`, SIMD headers; Signalsmith wrapper exists | No | Unknown; no double number |
| 3 | Signalsmith portable FFT as shipped | MIT | Yes | No intrinsics; compiler auto-vectorisation | Yes | Yes | Already vendored | Yes (baseline) | None (baseline) |
| 4 | pocketfft C++ (`pocketfft_hdronly.h`) | BSD-3-Clause | Yes | Vector code only for 2D and higher; 1D scalar | Yes | No: allocates a work array in every pass and a plan per call unless cached behind a mutex | One 3853 line header | No | None expected (scalar 1D) |
| 5 | KissFFT | BSD-3-Clause | Yes (`kiss_fft_scalar=double`) | No; SIMD build is SSE only | Yes | Yes for out-of-place power-of-two transforms | Small C: `kiss_fft.c` 424 lines plus two headers | No | None expected (scalar) |
| 6 | Ooura fft4g/fftsg | Permissive custom notice | Yes (plain C, double arrays) | No | Powers of two only | Not verified | Single C file | No | None expected (scalar) |
| x | muFFT | MIT | No, single precision only | No; x86 only, NEON "expected soon", last push 2019 | n/a | n/a | n/a | n/a | Excluded: precision |
| x | Ne10 | BSD-3-Clause (ARM) | No, float32/int32/int16 only | Yes | n/a | n/a | n/a | n/a | Excluded: precision |
| x | FFTW 3 | GPL v2 or later; commercial from MIT TLO | Yes | Yes (`--enable-neon`, double on aarch64) | Yes | Yes with plans | Large | No | Excluded: licence |
| x | KFR | GPL v2 or later; commercial | Yes | Yes | Yes | Not checked | Large | No | Excluded: licence |

The order of ranks 1 and 2 cannot be settled from primary sources. Rank 1
goes to Accelerate because it adds the least code and the Signalsmith author
already ships and maintains the wrapper; rank 2 goes to pffft because it is
the only vectorised double option that also runs on the WSL and MSVC builds
the project already uses, which would keep one FFT everywhere and one
parity rerun.

## Accelerate through the Signalsmith platform header

What the path needs, from the pinned upstream commit:

- File: `platform/fft-accelerate.h` from
  `https://raw.githubusercontent.com/Signalsmith-Audio/linear/146b26f91b48835d665fa0498d64d9617818d27a/platform/fft-accelerate.h`
  (340 lines). It includes `<vecLib/vecLib.h>` when available, else
  `<Accelerate/Accelerate.h>` (lines 2-6). The vendored `fft.h` includes it as
  `./platform/fft-accelerate.h` (`third_party/signalsmith-linear/fft.h:1376`),
  so it must land at `third_party/signalsmith-linear/platform/fft-accelerate.h`.
- Licence: the same MIT notice as `fft.h`
  (`third_party/signalsmith-linear/LICENSE.txt`), already installed by
  `CMakeLists.txt:114`.
- Build flags, from the upstream README at the pinned commit
  (`https://raw.githubusercontent.com/Signalsmith-Audio/linear/146b26f91b48835d665fa0498d64d9617818d27a/README.md`,
  lines 91-94): link the framework and define the macro, which the README
  gives as `g++ -framework Accelerate -DSIGNALSMITH_USE_ACCELERATE`. The
  upstream CMake target links Accelerate on Mac by default through the
  option `SIGNALSMITH_USE_ACCELERATE` (README line 83); Pitchwing does not
  use that CMake file, so it would add the define and
  `target_link_libraries(pitchwing PRIVATE "-framework Accelerate")`
  itself, guarded by `APPLE`.
- What the header does for the engine's instantiation: it specialises
  `Pow2FFT<double>` so `resize` calls `vDSP_create_fftsetupD(log2, FFT_RADIX2)`
  and sizes two split buffers, and the interleaved `fft` and `ifft` the
  engine calls run `vDSP_ctozD`, `vDSP_fft_zipD`, `vDSP_ztocD` in sequence
  (header lines 212-271). Each transform therefore pays two layout
  conversions on top of the FFT; the split-complex overloads call
  `vDSP_fft_zopD` with no conversion but the engine does not use them. It
  also replaces `_impl::complexMul<double>` with `vDSP_zvmulD` (header lines
  42-69), which the power-of-two passthrough plan never reaches.
- Hazard: the `Pow2FFT<double>` specialisation declares neither a deleted
  copy nor a move constructor (header lines 212-225), so a compiler-generated
  copy would share one `FFTSetupD` and destroy it twice. The engine
  constructs its transforms in place and never copies them
  (`src/Engine.cpp:106`, `src/LiveEngine.cpp:156`), so this is a prototype
  review item, not a blocker.
- vDSP facts from the SDK header on this machine (SDK 26.5,
  `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/System/Library/Frameworks/Accelerate.framework/Frameworks/vecLib.framework/Headers/vDSP.h`):
  `vDSP_create_fftsetupD` "allocate[s] memory and prepare[s] constants used
  by ... double-precision FFT routines" (lines 361-365); `vDSP_fft_zipD` is
  declared at line 692 and requires a setup created beforehand (lines
  741-743); the header says of the `vDSP_fft_z*` family "We suggest you use
  the DFT routines instead of these" (lines 755-756); the DFT setup family
  implements lengths `2**n` and `f * 2**n` with `f` in 3, 5, 15 (lines
  6971-6973); execution routines need only read access to a setup, so
  concurrent execution on shared setups is safe (lines 6871-6886). Apple does
  not document whether an execute routine allocates; the header attributes
  allocation to the setup routines only. Apple's web documentation pages for
  these symbols returned 404 or no body text to the fetch tool on
  2026-10-11, so the SDK header is the primary source used here.
- Parity consequence: a different butterfly order changes rounding, so
  output is not bitwise identical. The $10^{-10}$ tolerance is far above
  double rounding, but discrete decisions (peak picking, region matching)
  can flip on a rounding change, which the harness would report as a
  failure needing explanation (`docs/native-validation.md:115`). Enabling
  Accelerate also means macOS and other platforms run different FFTs, so
  parity evidence becomes per platform.

## pffft (marton78 fork)

- Repository: `https://github.com/marton78/pffft`, head commit
  `aa16fd3db58de4ba5dae8b0438440bb9da46b6fa` dated 2026-09-29 (GitHub API).
  The fork of Julien Pommier's original adds double support and CMake
  (README "double support" entry, line 329).
- Licence: `LICENSE.txt` is the NCAR/UCAR BSD-like notice with copyright
  lines for Mambro, Ayguen, Pommier and UCAR; the README states it "is
  compatible with proprietary projects" (line 90). It is not SPDX-listed
  (GitHub reports `NOASSERTION`), so the notice text must be vendored
  verbatim.
- Precision: `PFFFT_USE_TYPE_DOUBLE` builds the `pffftd_*` API (README line
  139); the Signalsmith README notes that "Not all PFFFT versions support
  double-precision", hence its separate `SIGNALSMITH_USE_PFFFT_DOUBLE` flag
  (upstream README line 99).
- NEON: README lines 30-31 list "NEON on ARM cpus (including Apple
  Silicon)"; `src/simd/pf_neon_double.h` is a native AArch64 backend holding
  four doubles as two `float64x2_t` registers, guarded by `PFFFT_ENABLE_NEON`
  and `__aarch64__`/`__arm64__`/`_M_ARM64`.
- Sizes: `include/pffft/pffft_double.h` documents `N = (2^a)(3^b)(5^c)` with
  `a >= 5` and "Performance is best for 128<=N<=8192"; buffers need 32-byte
  alignment.
- Real-time: "the fft functions do not perform any memory allocation" and
  take a `work` array (README lines 357-359); `pffft_double.h` says a null
  `work` uses the stack.
- Footprint from the GitHub contents API: `src/pffft_double.c` 5979 bytes,
  `src/pffft_common.c` 1808 bytes, `src/pffft_priv_impl.h` 91390 bytes, plus
  `src/simd/pf_neon_double.h` 6529 bytes and `pf_scalar_double.h` 5050 bytes;
  `src/sse2neon.h` (228617 bytes) is not needed for the native NEON double
  path. Signalsmith already ships `platform/fft-pffft-double.h` (221 lines
  at the pinned commit), which copies through an aligned temporary when the
  caller's buffers are not 32-byte aligned (lines 84-95) and allocates its
  work and temporary arrays in `resize` (lines 38-60).
- Benchmarks: the maintainer's results repository
  (`https://github.com/hayguen/pffft_benchmarks`) has no Apple M-series
  entry. Its only 64-bit ARM file,
  `ARM-RPi4B_gcc-9.3.0_aarch64_Ubuntu-20.04.3LTS.md`, is single precision:
  complex 2048, MFLOPS, FFTPack 2235, FFTW estimate 3621, pffft ordered 3464.
  That is a Cortex-A72 float number and does not transfer to double on an
  M4 Pro.

## pocketfft C++

- Repository `https://github.com/mreineck/pocketfft`, branch `cpp`, head
  `c90e55b3d529f8efa40ed01a20de22405f45fc65` dated 2026-06-30 (GitHub API).
  Licence BSD-3-Clause (`LICENSE.md`, Max-Planck-Society).
- Precision: float, double and long double (README).
- NEON: the README says vector instructions are used "when performing 2D and
  higher-dimensional transforms"; the NEON detection at
  `pocketfft_hdronly.h:158` feeds that multi-dimensional path, so a 1D
  transform is scalar.
- Real-time: the public `c2c` entry (`pocketfft_hdronly.h:3614`) goes through
  `general_nd`, which fetches a plan with `get_plan` (line 3322): with the
  default `POCKETFFT_CACHE_SIZE 0` that is `std::make_shared` on every call
  (lines 2955-2958), and the optional cache takes a `std::mutex` (lines
  2963-2995); it also allocates a temporary per call (`alloc_tmp`, lines
  3233-3252 and 3327). Even the internal plan class allocates: `cfftp::pass_all`
  creates `arr<T> ch(length)` on each execution (lines 1606-1610). The header
  pulls in `<thread>` and a thread pool unless `POCKETFFT_NO_MULTITHREADING`
  is defined (lines 80-83, 701-760).
- Footprint: one header of 3853 lines.

## KissFFT

- Repository `https://github.com/mborgerding/kissfft`, latest tag `131.2.0`,
  last push 2026-08-12 (GitHub API). Licence BSD-3-Clause (`COPYING`).
- Precision: "float, double, Q15 short or Q31 samples. The default is float"
  (README lines 44-45); double is selected by defining
  `kiss_fft_scalar` as `double`.
- NEON: the SIMD build "requires SSE instruction set support" (README line
  79); `kiss_fft.h` defines vector scalars only for AVX, SSE and LoongArch
  LSX (lines 53-75). There is no NEON path.
- Real-time: out-of-place power-of-two transforms allocate nothing; the only
  transform-time allocations are the generic-radix scratch for factors other
  than 2, 3, 4, 5 (`kiss_fft.c:205`) and the in-place temporary
  (`kiss_fft.c:385`). `KISSFFT_USE_ALLOCA` moves those to the stack (README
  line 97).
- Footprint: `kiss_fft.c` (424 lines), `kiss_fft.h` (184 lines) and
  `_kiss_fft_guts.h`.

## Ooura fft4g and fftsg

- Source `https://www.kurims.kyoto-u.ac.jp/~ooura/fft.html`: "You may use,
  copy, modify and distribute this code for any purpose (include commercial
  use) and without fee. Please refer to this package when you modify this
  code." Lengths are powers of two; `fftsg.c` is the split-radix C version.
- The page was read only for the licence and size facts above; work-array
  handling and precision were not verified from the source files in this
  survey, so the table marks allocation as not verified. Being plain C
  without intrinsics it offers no vectorised double path, so no speed-up over
  the shipped code is expected.

## Excluded candidates

- muFFT (`https://github.com/Themaister/muFFT`): MIT (`COPYING`), but the
  README calls it "a moderately featured single-precision FFT library" and
  says ARM NEON optimisations "are expected to be implemented soon"; the
  repository tree has only an `x86` SIMD directory and its last push was
  2019-02-15 (GitHub API). Excluded on precision.
- Ne10 (`https://github.com/projectNe10/Ne10`): BSD-3-Clause (ARM Limited,
  `LICENSE`); `inc/NE10_dsp.h` declares only `float32`, `int32` and `int16`
  1D FFTs, no float64; last push 2022-12-09 (GitHub API). Excluded on
  precision.
- FFTW 3 (`https://www.fftw.org/doc/License-and-Copyright.html`): GPL
  "either version 2 of the License, or (at your option) any later version";
  "Non-free versions of FFTW are available under terms different from those
  of the General Public License" from MIT's Technology Licensing Office.
  `--enable-neon` supports "single, double on aarch64"
  (`https://www.fftw.org/fftw3_doc/Installation-on-Unix.html`). Excluded
  because linking it would place the MIT engine's distribution under the
  GPL.
- KFR (`https://github.com/kfrlib/kfr`): "dual-licensed, available under
  both commercial and open-source GPLv2+ license"; optimised for "ARM,
  AArch64 (NEON)". Excluded on licence for the same reason as FFTW.

## What is not known

- No primary source gives a time for a complex double transform of 1024,
  2048 or 4096 points on any Apple M-series chip for Accelerate, pffft,
  pocketfft, KissFFT or the shipped Signalsmith code. The only AArch64
  number found is the Raspberry Pi 4 single-precision pffft result above.
- The share of a Pitchwing callback spent inside `fft` and `ifft` has not
  been measured on any platform. Until it is, no backend can be credited
  with a callback saving.
- Whether `vDSP_fft_zipD` allocates internally is not documented by Apple.

## Method

Repository facts were read from `CMakeLists.txt`, `third_party/README.md`,
`third_party/signalsmith-linear/fft.h`, `src/Engine.cpp`, `src/LiveEngine.cpp`,
`include/pitchwing/*.hpp`, `docs/native-validation.md`, `docs/apple-silicon.md`
and `docs/results/2026-10-10-timing-step12.txt`. Upstream files were fetched
raw from the repositories named above on 2026-10-11 and read with grep; the
GitHub REST API supplied push dates, licence ids and file sizes. Apple's vDSP
facts come from the local SDK header because the developer.apple.com pages
did not render for the fetch tool. No benchmark was run.
