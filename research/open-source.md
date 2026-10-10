# Public-source implementation research

Research date: 2026-10-08. Scope: guitar-first, polyphonic, real-time pitch shifting suitable for an eventual VST3 processor. This is source inspection and one compiled latency-API probe, not a listening comparison and not a claim of Neural DSP parity.

## Findings that change the implementation decision

1. **Signalsmith Stretch's current default is 120 ms algorithmic latency; the cheaper preset defaults to 140 ms.** This was derived from current source and confirmed by compiling its API. The earlier description of 100–120 ms windows was insufficiently specific: at unity time ratio, the symmetric analysis and synthesis latencies sum to the full block length. The cheaper preset also defaults to one hop of split-computation buffering.
2. **Low-delay, asymmetric STFT infrastructure is already available under MIT.** Signalsmith Linear permits separately offset analysis/synthesis windows. With 2048 samples of history at 48 kHz, hop 128, an asymmetry of 0.75 reports 511 samples / 10.646 ms; 0.9 reports 203 samples / 4.229 ms. These numbers establish scheduling feasibility only. They do not establish pitch-shift fidelity or effective low-frequency resolution.
3. **The public STN prototype is not a sub-10 ms implementation.** Its current default contains two decomposition windows plus a 50 ms tonal-shifting stage. The source-reported total at 48 kHz is approximately 103.33 ms. Treat its component-specific processing as a research idea, not a low-latency product base.
4. **Transient/coherence handling and latency accounting deserve equal attention.** The better-developed implementations invest in spectral neighborhood phase relationships, shared channel decisions, dynamic timing, and silence/startup behavior. A basic bin-resampling phase vocoder omits much of this work.

## Reproducible source snapshots

The following public repository heads were observed during retrieval. Local file SHA-256 and Git blob hashes are recorded in `open-source/source-manifest.json`; source files were fetched from the indicated repository branches on this research date. The three Signalsmith headers used by the probe were subsequently re-fetched at the exact commit URLs and verified byte-for-byte. Other observed revision IDs and content hashes support later comparisons; their initial fetches used branch URLs.

| Repository | Observed head/tree revision | Use and license evidence |
|---|---|---|
| [Signalsmith Stretch](https://github.com/Signalsmith-Audio/signalsmith-stretch) | `a670068d9aeb64913331d5cc29337b19a457a7df` | Current header identifies version 1.3.2; MIT license retained locally |
| [Signalsmith Linear](https://github.com/Signalsmith-Audio/linear) | `146b26f91b48835d665fa0498d64d9617818d27a` | FFT/STFT infrastructure; MIT license retained |
| [Rubber Band](https://github.com/breakfastquay/rubberband) | `e4296ac80b1170018a110bc326fd0d45a0eb27d6` | GPL-2.0-or-later / separate commercial license; source file headers state these options |
| [STN-based-Pitch-Shifting](https://github.com/mariapolak/STN-based-Pitch-Shifting) | `e5b1f499449bb079d34f5cd75fe03c44ee6ec150` | Public research code; recursive repository tree has no top-level license file; do not assume permission to incorporate it into a distributed product |
| [stftPitchShift](https://github.com/jurihock/stftPitchShift) | `1a4f21f6c300a785cce860e374fd63cb5e9ba154` | MIT; license retained |

Downloaded source subsets are research references, not complete vendored dependency releases. In particular, Rubber Band and STN subsets are not linked into the probe. The compiled probe uses only the MIT Signalsmith headers. There is no proprietary algorithm implementation in this folder.

## Signalsmith Stretch and Linear

Primary source: [Stretch header](https://github.com/Signalsmith-Audio/signalsmith-stretch/blob/main/signalsmith-stretch.h), [Linear STFT](https://github.com/Signalsmith-Audio/linear/blob/main/stft.h), [Linear documentation](https://github.com/Signalsmith-Audio/linear).

### Architecture observed in code

`processSpectrum()` performs a spectral mapping and phase reconstruction. It accumulates energy across channels, smooths spectral energy, identifies peaks, and builds an output-to-input frequency map between peak locations. That mapping preserves local peak shape more carefully than simply moving every bin by the same scale and rounding its destination.

The phase stage first computes a time-direction prediction from the relationship between current and previous input spectra and previous output. It then re-predicts using nearby-frequency relationships, including short and longer vertical steps. The dominant-energy channel at each output bin guides the remaining channels through their input phase relationships. This is direct evidence of inter-bin and inter-channel coherence logic. It does not establish the exact perceptual contribution of each mechanism without ablation testing.

Energy is scaled by the local frequency-map gradient. Formant handling is optional. High-frequency tonality limiting changes the frequency mapping from multiplicative to additive above a chosen boundary; it is a timbral/artifact tradeoff and should not be silently enabled in a test claiming strict uniform transposition.

The main source does not reveal a separate STN decomposition path. Avoid describing Stretch as STN-based just because an external STN project uses it.

### Latency, verified

For the normal symmetric setup and equal input/output counts:

`L = analysisLatency + synthesisLatency + splitComputation * hop = blockSamples + splitComputation * hop`.

The default block is `int(fs*0.12)`, hop `int(fs*0.03)`, split computation false. The cheaper preset uses block `int(fs*0.1)`, hop `int(fs*0.04)`, split computation true. The source probe at 44.1, 48 and 96 kHz verified 120 and 140 ms respectively.

| API probe at 48 kHz | Block/history | Hop | Input latency | Output latency | Total |
|---|---:|---:|---:|---:|---:|
| Stretch default | 5760 | 1440 | 2880 | 2880 | 120 ms |
| Stretch cheaper | 4800 | 1920 | 2400 | 4320 | 140 ms |
| Stretch custom | 512 | 64 | 256 | 256 | 10.667 ms |
| Linear STFT, asymmetry 0 | 2048 | 128 | 1025 | 1023 | 42.667 ms |
| Linear STFT, asymmetry 0.75 | 2048 | 128 | 256 | 255 | 10.646 ms |
| Linear STFT, asymmetry 0.9 | 2048 | 128 | 102 | 101 | 4.229 ms |

These are API-reported algorithmic delays, not loopback measurements. They exclude audio-interface buffers, host scheduling and any external adapter. The Linear cases are an analysis/synthesis helper, not a complete pitch shifter.

In Linear's general configuration, with analysis offset `a`, synthesis offset `s`, and block `B`, `L = B - a + s`. Positive window asymmetry moves the analysis peak later and synthesis peak earlier. It retains history while reducing forward dependence. However, increased asymmetry changes window bandwidth/leakage and can amplify errors during spectral modification. The FFT length alone is not a guarantee of long-window frequency discrimination.

**Reusable direction:** keep this MIT helper as one candidate for original long-history/short-synthesis experiments. Stretch's public configuration does not expose this asymmetry directly; simply passing 2048 to Stretch does not enable the low-delay case. A source modification requires verifying every timing and phase-reference assumption, along with overlap-add reconstruction.

Reproduce the probe from the project root:

```sh
g++ -std=c++17 -O2 open-source/latency_probe.cpp -o open-source/latency_probe
./open-source/latency_probe
```

The output CSV has `stretch,fs,preset,block,hop,inputLatency,outputLatency,totalMs` rows and `linear-asym,asymmetry,analysisOffset,synthesisOffset,analysisLatency,synthesisLatency,totalMs` rows. Preset 0=default, 1=cheaper, 2=512/64 custom. Exact output is retained.

## Rubber Band: distinguish R2, general R3, and the live API

Primary sources: [R2 technical notes](https://breakfastquay.com/rubberband/technical.html), [Live API documentation](https://www.breakfastquay.com/rubberband/code-doc/classRubberBand_1_1RubberBandLiveShifter.html), [R3LiveShifter.cpp](https://github.com/breakfastquay/rubberband/blob/default/src/finer/R3LiveShifter.cpp), [R3LiveShifter.h](https://github.com/breakfastquay/rubberband/blob/default/src/finer/R3LiveShifter.h), [Guide.h](https://github.com/breakfastquay/rubberband/blob/default/src/finer/Guide.h), [PhaseAdvance.h](https://github.com/breakfastquay/rubberband/blob/default/src/finer/PhaseAdvance.h).

The R2 documentation describes transient phase resets, adaptive stretch ratio between reset points, and vertical phase lamination. It explicitly says that R3 differs. Do not transfer every R2 detail to R3.

The inspected R3 infrastructure classifies bins with time/frequency median filters, guides phase-lock/reset bands, and adjusts phase around spectral peaks. `PhaseAdvance.h` explicitly considers cross-channel locking and previous peak identity. General `Guide` infrastructure supports three FFT scales; **the inspected LiveShifter forces `isSingleWindowed()` to true** and constructs its guide in single-window mode. Calling the current live API a three-resolution algorithm would be incorrect.

Pitch shifts combine time processing and resampling. Input resampling is used for upward shifting, output resampling for downward shifting. The live source explicitly measures initial resampler buffering. Start-delay accounting includes window source size, resampler delays, pitch-dependent output scaling, and block-size corrections. Thus `FFT size / fs` alone is not its total delay. The public live API documents delays of 50 ms or more depending on configuration.

**Reusable concepts, not a source transplant:** region-specific resets, phase coherence over peak neighborhoods, linked-channel decisions, explicit resampler-delay measurement, and robust stream startup. For a proprietary engine, incorporating GPL source requires a compatible licensing decision or a commercial agreement; an independent implementation can instead be grounded in separately documented techniques.

## STN research implementation: useful ideas, unsuitable baseline timing

Primary source: [repository](https://github.com/mariapolak/STN-based-Pitch-Shifting), current `Pitch Shifter/Source/PluginProcessor.cpp`, `DSP/STN/decomposeSTN.{h,cpp}`, `DSP/NM/NoiseMorphing.{h,cpp}`. Local copies and recursive tree are retained for analysis.

The processor splits input into sines, transients and noise. Sines go through Signalsmith shifting; transients are delayed but otherwise passed through; noise receives spectral-envelope interpolation, regenerated-noise phase structure, overlap-add, and sinc resampling. All branches are delayed to align before summation.

The decomposition is two serial STFT stages: default sizes 2048 and 512, eightfold overlap. It uses causal/history-only horizontal median filtering over roughly 50 ms and a vertical frequency filter around 500 Hz. Its returned decomposition delay is `N_sines + N_transient_noise`; the median history is not additional future lookahead, but its causal decisions can lag changes in content.

The main processor hardcodes a 50 ms tonal block. Total reported latency is:

`L_total = N_sines + N_transient_noise + max(L_stretch, L_noise)`.

At 48 kHz the default gives 2560+2400=4960 samples, approximately 103.33 ms, assuming the reported noise delay remains below 2400. The noise header returns 2048 plus the JUCE sinc interpolator's base latency. The smallest offered decomposition size is 512+128; with the unchanged tonal branch that is approximately 63.33 ms.

Additional production gaps visible without running it:

- Only channel 0 is processed; stereo output copies mono into channel 1.
- FFT size setters reachable from `processBlock()` call `prepare()`, rebuilding FFTs and resizing vectors. That needs relocation away from the audio callback.
- The horizontal median implementation pops and pushes vector-backed deque entries each analysis call, creating allocation/copy pressure in the callback.
- The transient branch contains original pitch content. That is benign only where content is sufficiently noise-like/brief; tonal leakage is a measurable failure mode for guitar picks and overlapping notes.

This is an explicit research prototype. No finding here contradicts its value as a study; the timing and structure simply do not satisfy the target live-guitar budget unchanged.

## Other public alternatives

### stftPitchShift

[Repository](https://github.com/jurihock/stftPitchShift), [STFT.h](https://github.com/jurihock/stftPitchShift/blob/main/cpp/StftPitchShift/STFT.h), [Vocoder.h](https://github.com/jurihock/stftPitchShift/blob/main/cpp/StftPitchShift/Vocoder.h).

This MIT C++/Python implementation provides instantaneous-frequency encoding, spectral resampling, phase integration, and optional cepstral formant processing. Its phrase “poly pitch shifting” describes producing multiple shifted voices in one spectral pipeline, not an evaluated claim about complex chord fidelity.

Its STFT supports a longer analysis window and shorter synthesis window; the vocoder applies a compensating phase offset. This is another accessible low-delay implementation reference. However, the maintainer's [open issue #44](https://github.com/jurihock/stftPitchShift/issues/44) reports artifacts at a synthesis length one quarter of analysis length, independent of hop. Do not infer that swapping in asymmetric windows solves fidelity automatically.

The inspected vocoder maintains phase per bin; it does not contain the richer cross-bin/channel guidance seen in the other inspected implementations. It is useful as an ablation/baseline rather than presumed commercial-quality end state.

### SoundTouch

The [official README](https://soundtouch.surina.net/README.html) documents roughly 100 ms input/output latency when its time-stretch processing is used. It is a useful time-domain benchmark and a contrast to spectral approaches, but it is not the first candidate for the requested budget. Its official licensing page states LGPL v2.1, with a separate non-LGPL option available. No SoundTouch source audit or benchmark was performed here.

## Implementation experiment priorities

1. Build a genuinely streaming harness, including variable host block sizes, sample-rate changes, silence/restarts, ratio automation, and explicit declared versus measured delay.
2. Compare a conventional symmetric STFT baseline against a dual/asymmetric-window engine at the same measured output latency. Use identical peak mapping and phase guidance so the window effect is isolated.
3. Evaluate short-analysis and long-history estimators separately: long history can assist frequency/phase estimates, while a short synthesis stage determines responsiveness. Avoid two serial STFT synthesis/re-analysis stages when the latency budget can be served by operating on one shared spectral representation.
4. Use soft, causal transient/noise confidence to select phase behavior before implementing a full three-way waveform decomposition. This reduces the initial latency and reconstruction-complexity burden, but is a proposal, not a proven substitute for STN.
5. Test low guitar fundamentals and close partial collisions. Short windows cannot reliably isolate all simultaneous partials; estimator confidence and graceful fallback matter as much as steady-state sinusoid accuracy.
6. Preserve stereo decisions where appropriate and test mono compatibility. Never treat independently satisfactory mono channels as proof of correct stereo processing.
7. Measure callback-time tails and allocations, not only average CPU. Spread work within existing delay where possible; adding an entire hop to smooth load changes the live playing experience.

None of these source analyses proves the eventual engine competitive. The next evidence gate is a blinded comparison using dry guitar lead/chord fixtures, bass, piano, acoustic transients and mixed content, against the exact Neural DSP version and the Compose demo at matched shifts and measured delays.

## Confidence and limitations

High confidence: direct source structures, present constants, license files, and compiled latency API outputs. Medium confidence: source-derived artifact mechanisms and product integration risks. Unverified: subjective quality, CPU performance on target hardware, measured end-to-end delay, exact behavior of the unbuilt STN plug-in, and comparative quality against Neural/Compose. No proprietary binary was used in this subtask.
