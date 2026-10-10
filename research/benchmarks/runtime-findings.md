# Signalsmith Compose public demo: reproducible runtime observations

Measured 2026-10-08 against the exact public `compose-2026-10-01.wclap.wasm` supplied by the user. SHA-256: `ffff817738e0386eb0f8dc44b331422535f4c6fe762252d99dca7be25a0f1dc1`.

## Scope and result

A headless Node.js host successfully executes the unmodified binary using its ordinary wasm32 CLAP entry/factory, plug-in, audio-ports, parameters, and latency APIs. No license/demo control was removed or bypassed. The host uses the public WebCLAP WASI implementation and typed JavaScript callback bridge; it does not need the demo's web UI.

The selected plug-in is `uk.co.signalsmith.compose.pitch-shifter-layer1` / `Compose: Pitch Shifter`, descriptor version 1.0.0. There are ten effect descriptors in this binary; these measurements concern only the first. It exposes two input and two output channels. Mono-generated input is duplicated into both input channels; output channel 0 is analyzed.

**Default configuration reports 480 samples (10 ms) at 48 kHz, and every tested impulse's maximum occurs exactly 480 samples after the input impulse.** Very small output precedes that maximum: the first sample exceeding -60 dB relative to the output peak is about 121 samples after excitation. That early energy must not be advertised as 2.5 ms effective latency. The signal is spread in time, and different definitions measure different properties.

No Neural DSP comparison or listening evaluation was performed. These synthetic probes establish functional behavior and a useful latency baseline, not audible quality parity, source-code recovery, or suitability for production.

## Fixed configuration

- Sample rate: 48,000 Hz; block size: 128 frames; output length: 2 seconds per case.
- Input begins at sample 8,192 after silence. Impulse amplitude is 0.5. Gated sine is 110 Hz at amplitude 0.4, starting with phase zero.
- Chord fundamentals: 82.406889, 123.470825, 164.813778, 207.652349, 246.941651, and 329.627557 Hz. Each has six harmonics with amplitude `1/(24*h)`. This is a stationary synthetic E-major-like voicing, not a recorded guitar.
- Initial semitone value is set through the standard CLAP parameter-flush API before activation. Shifts: -12, -7, -2, 0, +7, +12. Every case gets a fresh instance.
- Automation case starts at zero shift and changes to -7 at sample 48,000 (a block boundary).
- All other parameters remain at their public defaults. Default text labels: latency 10ms; overlap 4; resolution 20; iterations 4; direct on; channels full; first smoothing 1%; phase 1%; detail 0.8; transient reset 2; transient boost 0; tonality limit 8000Hz; second smoothing 1; timbre 0.
- Exact parameter IDs, normalized defaults, flags, and text labels are recorded in `results/metadata.json`. Two parameters share the name `smoothing`; use their IDs to disambiguate.

The latency parameter advertises normalized endpoints 0 -> 2ms and 1 -> 15ms, with 0.3 -> 5.5ms. Those endpoint text labels are not measurements of sound quality or actual configured latency at those settings; this first benchmark measures the default 10ms configuration only.

## Impulse measurements

All offsets below are relative to input sample 8,192. `Onset` is first absolute output amplitude >= 0.001 times that case's maximum amplitude (-60 dB). `Centroid` is the energy-weighted mean sample over the complete 2-second output. `90%` is cumulative-energy 90th percentile, not settling time.

| Semitones | Reported samples | Onset samples | Peak samples | Centroid samples | 90% energy samples |
|---:|---:|---:|---:|---:|---:|
| -12 | 480 | 121 | 480 | 517.61 | 604 |
| -7 | 480 | 121 | 480 | 497.26 | 542 |
| -2 | 480 | 121 | 480 | 485.91 | 496 |
| 0 | 480 | 122 | 480 | 480.00 | 480 |
| +7 | 480 | 121 | 480 | 479.20 | 493 |
| +12 | 480 | 121 | 480 | 483.64 | 485 |

The shifted transient energy distribution changes with shift direction. This observation alone does not identify the internal algorithm.

## Gated 110 Hz sine measurements

Frequency uses a Hann-windowed final 1-second segment, FFT zero-padded to 2^20, followed by a log-parabolic peak estimate. Zero padding improves peak interpolation; it does not create additional physical frequency resolution. Target-band energy is spectral power within +/-3 Hz of the ideal shifted tone divided by total spectral power. It is a descriptive spectral concentration measure, **not a perceptual quality score**.

| Semitones | Peak Hz | Peak error cents | Target-band energy | -20 dB onset samples |
|---:|---:|---:|---:|---:|
| -12 | 54.9975 | -0.080 | 99.506% | 542 |
| -7 | 73.4145 | -0.039 | 99.523% | 535 |
| -2 | 97.9977 | -0.021 | 99.458% | 503 |
| 0 | 110.0000 | approximately 0 | 99.979% | 488 |
| +7 | 164.8163 | +0.027 | 99.394% | 454 |
| +12 | 220.0052 | +0.041 | 99.378% | 419 |

The onset threshold here is 10% of that case's output peak (-20 dB). The source begins at a sine zero crossing, so these onset numbers also contain the waveform's amplitude rise. Do not compare them directly with an impulse's peak delay or host-reported latency.

## Chord and automation checks

For the harmonic chord, energy within the union of +/-3 Hz around every expected shifted partial is 98.922%, 97.560%, 97.455%, 99.990%, 97.040%, and 95.461% for the six shifts respectively. This confirms concentration around the intended partial set. It neither measures chord intelligibility nor proves freedom from modulation artifacts, attack smearing, or unpleasant distortion. Finite windows, spectral leakage, and the choice of +/-3 Hz bands affect this metric.

The automation case's dominant tone moves from approximately 110.001 Hz in seconds 0.6–0.9 to approximately 73.425 Hz in seconds 1.6–1.9, consistent with the requested -7 semitone endpoint. No claim of click-free transitions follows from this endpoint check. All 19 outputs were finite.

## Reproduction

Requirements: Node.js 24 (tested with 24.19.0), Python 3 with NumPy, the publicly available demo binary downloaded separately, and the public WebCLAP repository with the indicated nested submodules. The binary is not redistributed by these scripts.

Pinned source dependencies:

- https://github.com/WebCLAP/browser-test-host — `b42ade615bef2c989f96400a7b0b2ef15cabd396`
- `clap-audionode/wclap-js` — `c9ffa8cb112b441e74e90a2d98b9d1c66d0a7619`
- `clap-audionode/wclap-js/es6/wasi` — `bf488c52cd35010f928cd24b79aac2a73b0e575c`

Set `WEBCLAP_HOST` to your local browser-test-host checkout. Run:

```bash
WEBCLAP_HOST=/absolute/path/browser-test-host node benchmarks/run-compose.mjs /absolute/path/compose-2026-10-01.wclap.wasm
python benchmarks/analyze-compose.py
```

The default result directory is beside the scripts, `benchmarks/results`. Raw outputs are little-endian float32, one channel, 48 kHz, exactly 96,000 samples each. `metadata.json` records provenance, configuration and timing; `analysis.json` records the analysis. The scripts are original host/benchmark code. They use public interfaces, not reconstructed DSP code.

## Limitations and next useful tests

The host is deliberately minimal: it supplies no optional host extensions, only a transport object with no valid-info flags, and does not implement runtime restart requests. Initial configuration is completed before activation; the tested semitone change did not require a restart. A general-purpose host needs these facilities. The layout is wasm32 CLAP, not the native 64-bit ABI.

The demo emits per-block transport debug messages. The runner suppresses only those two known diagnostic line types; the unmodified binary still performs their formatting. Wall times in `metadata.json` include JavaScript copying, WASM/JS boundaries, allocation, diagnostic formatting, JIT, and shared execution-host scheduling. They should not be used as native SDK CPU specifications or as cross-engine comparisons.

The useful next experiment is the same exact corpus at the advertised 5–6 ms configuration, followed by real dry guitar recordings and a matched Neural DSP version. Add low seven/eight-string fundamentals, rapid lead articulation, string attacks, palm mutes, stereo decorrelation, changing chords, and shifted output through a fixed high-gain amp/cab chain. Measure pitch settling after actual note changes, and report both perceptual tests and latency distributions.
