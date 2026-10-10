# Compose and WebCLAP: bounded binary/source forensics

Research date: 2026-10-08. This report contains observations and architectural inferences, not a reproduction of proprietary implementation. Runtime measurements are maintained separately under `benchmarks/`.

## Main result

The inspected Compose demos support a **complex subband processing architecture with per-band frequency metadata, a distinct analysis update rate, and a nonuniform nominal frequency grid**. Public materials independently describe a shared spectral analysis engine and modular peak/envelope/transient operations. This is useful evidence for an independent design. It does not establish the exact transform, estimator, refinement procedure, phase update, or synthesis algorithm.

The provided WebCLAP repository is a browser audio/plugin host. Its source explains how to execute the demonstration; it does not contain Compose's proprietary signal-processing source.

## Provenance

| Artifact | Source | Size | SHA-256 / revision |
|---|---|---:|---|
| Web demo | https://cors.signalsmith-audio.co.uk/compose/compose-2026-10-01.wclap.wasm | 1,121,191 bytes | `ffff817738e0386eb0f8dc44b331422535f4c6fe762252d99dca7be25a0f1dc1` |
| Windows demo archive | https://compose.signalsmith-audio.co.uk/demo/plugins/compose-2026-10-06-windows.zip | 1,253,719 bytes | `fa887b38f664219291fe2b6c8b27c15c93eb2d5709f6daadac314dece0a734bb` |
| CLAP within archive | `compose.clap` | 1,632,256 bytes | `08b8f079403c56d50e6bea5d89a95165b53193418e19c474e086f4f8c7feba26` |
| VST3 within archive | `compose.vst3/Contents/x86_64-win/compose.vst3` | 2,070,528 bytes | `899c6ddb5dd75191e387450e93f5873c1edc5849e3882412e5e46e40aaf23cb4` |
| Browser host | https://github.com/WebCLAP/browser-test-host | — | `b42ade615bef2c989f96400a7b0b2ef15cabd396` |
| WCLAP JS submodule | https://github.com/WebCLAP/wclap-js | — | `c9ffa8cb112b441e74e90a2d98b9d1c66d0a7619` |
| Public architecture image | https://compose.signalsmith-audio.co.uk/media/architecture.svg | 26,612 bytes | Linked from vendor product page |

The Windows link in the retrieved product HTML included an accidental leading space in its filename; removing that space resolved the vendor's public archive URL. No credentials, access checks, or demo restrictions were bypassed.

**Version boundary:** the WebAssembly and native artifacts have different date versions. Native geometry observations must not be presented as measured behavior of the October 1 WebAssembly build.

## Verified static findings

| Finding | Evidence | Interpretation limit |
|---|---|---|
| WASM version 1; 1,155 defined functions, 12 imported functions; 65 types | WABT section dump and independent Python parser | Counts include plugin wrappers, C++ runtime, UI support, and multiple effects |
| No custom/name/debug sections | Complete section inventory | Original C++ names and source lines are unavailable |
| Shared imported memory, initial 3 pages, maximum 32,768 pages | WASM import declaration | These are declared limits, not steady-state working memory or proof DSP is multithreaded |
| Exports `memory`, `_initialize`, `__indirect_function_table`, `clap_entry`, `malloc` | WASM export section | Host calls plugin functions through the CLAP table |
| WASI environment, descriptor I/O, process, scheduling, and random imports | Import section | Runtime support does not imply those calls occur in the audio path |
| Scalar floating point and `f32x4` SIMD instructions exist | Disassembled opcodes | Whole-module instruction counts do not predict CPU cost or identify an algorithm |
| Native binaries export a C analysis/synthesis API | PE export tables in both CLAP and VST3 | Exports identify interface concepts, not published API signatures or licensing rights |
| Native `inputReal`, `inputImag`, and `inputHz` getters return channel-indexed array pointers | Short exported getter bodies | Strong evidence for split complex values plus per-band frequency metadata; exact meaning of frequency requires SDK documentation |
| Native `nominalHz` returns an indexed float from a stored band-frequency array; `bands` returns its length | Exported getters | Band count and actual frequencies depend on configuration |
| Native `nominalBand` is nonlinear in its lower branch and affine above a configured threshold | Bounded inspection of this mapping getter | Nonuniform frequency grid is supported. Exact coefficients and crossover were not extracted, and this does not prove a particular filterbank family |
| Native `subRate` is input sample rate divided by the analysis period in samples | Getter plus bounded initialization inspection | Analysis/control cadence, not audio sample rate. Default period 2.5 ms corresponds to approximately 400 Hz updates |
| Native default core configuration begins with 10 ms timing and 2.5 ms period | Default configuration function, corroborated with timing initialization | Public WASM UI independently reports 10 ms latency and overlap 4; do not conflate versions |
| Native output API distinguishes split/interleaved and normal/`Moved` variants | PE export names | Exact `Moved` argument meaning was not established and should not be guessed |
| Native latency is explicitly returned in samples | Export and small getter | No end-to-end browser/interface latency can be inferred from this getter |

The native API also exposes creation/destruction, reset, callbacks, default configuration, and optional bump allocator hooks. The native core-version getter returns a development marker, so the archive date and binary hashes are the better identities.

## Public architecture and control clues

The vendor's architecture diagram separates a prebuilt analysis core from an editable C++ effects layer and lists peak grouping, spectral flux, envelopes, and a noise estimator. The product page says typical latency is 5–10 ms with a single processing layer and no adaptive switching. These are vendor descriptions, not independent measurements.

The binary contains UI/control labels and short descriptions for resolution, iterations, high-band direct copying, phase smoothing, transient phase reset, transient/detail boosting, and tonality limiting. The runtime investigator confirmed a corresponding set of controls on the pitch-shifter effect through the ordinary public parameter API.

Useful architectural hypotheses, each requiring experiments:

1. **Separate frequency resolution from immediate output delay.** Nonuniform bands and an explicit subrate are consistent with a longer-memory spectral estimator feeding a short-delay output path. Exact method remains unknown.
2. **Spend more analysis work where a short FFT is weak.** The direct-copy control's explanatory text links high-frequency bands to FFT output without additional refinement. This is consistent with selective refinement, but does not identify the refinement method or imply a second signal path.
3. **Treat phase and new energy jointly.** The transient control descriptions explicitly concern phase resets and energy arrival. An independent pitch shifter should test soft onset-dependent phase corrections, rather than assuming instantaneous-frequency accuracy alone preserves attacks.
4. **Expose analysis quality controls only during R&D.** Resolution, overlap, refinement iterations, and transient behavior are separate dimensions in the demo; there is no evidence one fixed textbook phase-vocoder setting achieves the same quality.

Avoid misleading conclusions: a nonuniform grid is not by itself proof of a constant-Q transform, wavelet transform, gammatone filterbank, recursive resonator bank, or neural network. No evidence identifies Neural DSP's Transpose engine. No listening comparison to Neural DSP was performed by this forensic work.

## False positives and limitations

- The string `Multihop attempted` belongs to a generic WASI error-message table. It is **not** evidence of multihop spectral analysis.
- MIME types, Javascript UI libraries, allocator locks, and libc++ messages account for much of the binary's text and code. A large string dump is not an algorithm description.
- The demo bundles several effects; a module-wide string cannot automatically be attributed to the pitch shifter.
- The process table entry identified by the runtime investigator is table index 21, WASM function 43. Its direct static call closure reaches 144 functions and contains many indirect call sites. This underapproximation cannot isolate the DSP core without resolving virtual calls.
- No native audio execution was attempted. No reverse-engineered implementation, patched binary, or proprietary source is included in the research deliverable.
- The public host source at the inspected root revision has no obvious root LICENSE file. Public source availability alone should not be treated as a permissive reuse license. The independently written metadata probe below has no dependency on copied host implementation.

## Reproduction

The deliverable includes `probe_wasm.py` (standard library only), `wasm-structure.json`, `wasm-metadata.json`, `opcode-summary.json`, `native-exports.json`, and provenance JSON files. Proprietary binaries, raw string dumps, decompiled listings, and downloaded third-party trees remain disposable working material and should be excluded from the shared archive.

Download the exact public binary above into an analysis directory, then:

```sh
python probe_wasm.py compose-2026-10-01.wclap.wasm --output wasm-structure.json
npm install --prefix tools --no-audit --no-fund wabt@1.0.39
tools/node_modules/.bin/wasm-objdump -h compose-2026-10-01.wclap.wasm
tools/node_modules/.bin/wasm-objdump -x compose-2026-10-01.wclap.wasm
tools/node_modules/.bin/wasm-decompile --enable-all compose-2026-10-01.wclap.wasm -o local-analysis.dcmp
tools/node_modules/.bin/wasm2wat --enable-all compose-2026-10-01.wclap.wasm -o local-analysis.wat
```

WABT 1.0.39 initially rejected shared memory without thread features enabled; `--enable-all` allowed successful parsing. The resulting WAT had 479,625 lines; decompiler pseudocode had 146,752 lines. Those outputs were used for inspection only.

On the native archive's `compose.clap`, GNU `objdump -p` reveals export names. `objdump -t` reports no ordinary symbol table. Bounded getter inspection used native virtual addresses `0x180109960`–`0x180109c30`; analysis-rate initialization was checked at `0x1800fd360`–`0x1800fd580`. These addresses are meaningful only for the recorded native hash.

## Source URLs for the parent report

- Vendor product page: https://compose.signalsmith-audio.co.uk/ .
- Vendor architecture diagram: https://compose.signalsmith-audio.co.uk/media/architecture.svg (downloaded directly; web extraction rejected SVG content type).
- Public host: https://github.com/WebCLAP/browser-test-host (``).
- WABT official documentation: https://github.com/WebAssembly/wabt (``).
- Vendor code/licensing overview: https://signalsmith-audio.com/code/ (``).
- Exact binaries: URLs and hashes above. Binary-derived findings are original observations from this investigation, not statements from vendor documentation.
