# Primary literature and implementation notes — low-latency polyphonic pitch shifting

Research date: 2026-10-08. These are intermediate technical notes, not a claim that any proposed design matches Neural DSP or Compose. Source URLs are retained for future verification.

## Main conclusion

The strongest route is a research prototype combining **past-heavy analysis, short synthesis support, coherent spectral-region remapping, and explicit onset handling**. Its quality remains unproved. Shortening a normal phase vocoder alone is a poor bet for low guitar chords. Keep an independent low-delay baseline (Ocean) and a proven higher-delay quality baseline (Signalsmith Stretch). Measure spectral settling and transient lag, not only reported plug-in latency or the first nonzero output sample.

## 1. Mauler & Martin 2007: asymmetric analysis/synthesis windows

Primary PDF: https://www.eurasip.org/Proceedings/Eusipco/Eusipco2007/Papers/A2L-D02.pdf

Web ref: . Title: *A Low Delay, Variable Resolution, Perfect Reconstruction Spectral Analysis-Synthesis System for Speech Enhancement*. EUSIPCO 2007. Alternate metadata: https://zenodo.org/records/40249 ().

Long analysis is paired with short synthesis. The samplewise product of each matched window pair is zero until the newest `2M` samples, then equals a periodic Hann window. Frame advance `R=M/2^p` gives perfect reconstruction with appropriate gain. Window pairs can switch arbitrarily **for unmodified spectra**.

Published example: `K=512, M=64, R=32, fs=16000`; OLA+processing delay `(2M+R)/fs=10 ms`, versus 34 ms for the compared symmetric long-window configuration. Spectral modifications add group delay. Long asymmetric analysis has nonlinear phase and lower sidelobe attenuation than its symmetric counterpart. Section 3.2 explicitly warns about cyclic aliasing after spectral modifications; padding may be needed.

**Application inference:** supports investigating long history at low fixed delay. It is a speech-enhancement front end, not evidence that pitch remapping preserves its quality or latency. PR at ratio 1 does not establish correctness at other ratios.

## 2. Juillerat & Hirsbrunner 2010: Ocean

Primary author paper upload: https://www.researchgate.net/publication/261078164_Low_latency_audio_pitch_shifting_in_the_frequency_domain (, , ). DOI: 10.1109/ICALIP.2010.5685027. Author portal: https://pitchtech.ch/ ().

Paper claims useful musical quality around 12 ms, comparing small-window improved phase vocoding. It avoids unstable estimation of unresolved sinusoids by coarse spectral remapping. Analysis-bin index `a` maps to `b=round(m*r*a)` in an enlarged `mN` synthesis FFT. Rotate each mapped phasor by `exp(-i*2*pi*(b-m*a)*p/(m*O))`, with FFT-convention-dependent sign. Crop synthesis to the original `N` samples. Apply synthesis window, overlap-add, and periodic amplitude demodulation.

Important limitations: bin quantization produces detuning; approximate demodulation leaves AM; sparse/pure tones expose both more than rich spectra. Increased synthesis length reduces quantization but can duplicate transients; cropping trades that for other artifacts. This is a valuable falsifiable baseline, not a demonstrated modern winner.

Author errata https://pitchtech.ch/Confs/ICALIP2010/Errata.txt (): remove erroneous extra `N` denominator in phase-rotation equation.

### Downloaded and inspected reference code

Archive: https://pitchtech.ch/Confs/ICALIP2010/PitchShiftOcean.7z

Local source root: `pitch-research/papers-sources/ocean/PitchShiftOcean/`.

- Core: `src/ch/tachyon/sonics/ocean/PitchShiftOcean.java`.
- Core license: `src/LICENSE.txt`, MIT, copyright 2018 Nicolas Juillerat.
- Bundled `Tachyon-Tunnel.jar` and `tritonus-sampled` are separate dependencies; core algorithm can be ported without copying those frameworks.
- Code's actual expected delay is `N-H`; `getLatency()` intentionally returns zero so exported files retain visible delay. It is **not zero-latency DSP**.
- With `N512, H64`, expected core delay is 448 samples (9.33 ms at 48 kHz), before external buffering. Verify using the prototype rather than treating formula as measurement.
- Initial `processHopIndex=-(O-1)` and `outputHopIndex` equal it. Crop the **first N** samples of the enlarged IFFT; do not silently fftshift.
- Demodulation cycles over `mO` frames; denominator is clamped to 0.1. It can be precomputed for fixed ratios. Author flags `m>1,O=2` as problematic.
- Source warning: residual modulation is especially audible at small blocks, large padding factors, and low frequencies. Pure-tone quality is explicitly poor.
- Pitch-ratio automation is not implemented; correct extension needs history of ratios for all overlapping frames plus phase-continuity handling. Stereo source advice is one instance per channel; shared mapping must be maintained.

## 3. Laroche & Dolson 1999: spectral peak-region shifting

Primary PDF: https://www.ee.columbia.edu/~dpwe/papers/LaroD99-pvoc.pdf ().

Title: *New Phase-Vocoder Techniques for Pitch-Shifting, Harmonizing and Other Exotic Effects*. WASPAA 1999.

Important idea: detect spectral peaks, define their regions of influence, and translate each region coherently instead of treating every leakage bin as an unrelated sinusoid. Direct frequency-domain pitch changes avoid requiring a global time-stretch plus resampler. Paper distinguishes integer-bin shifts with 50% overlap and a more flexible fractional approach requiring 75% overlap.

**Application inference:** preserve the width and phase structure of each window lobe when moving a partial. Multiplying every frequency coordinate by the pitch ratio stretches lobes, encourages subband aliasing, and destabilizes short-window processing. Peak-region methods still depend on resolving nearby partials; dense low chords require longer historical analysis or a robust unresolved-region fallback.

## 4. Průša & Holighaus: Phase Vocoder Done Right

Primary PDF: https://arxiv.org/pdf/2202.07382 (). Landing: https://arxiv.org/abs/2202.07382 (). Related RTPGHI DAFx2016 paper: https://dafx16.vutbr.cz/dafxpapers/03-DAFx-16_paper_02-PN.pdf ().

Integrate both time and frequency phase gradients. Traditional PV keeps horizontal coherence, but ignores vertical phase structure important for transients and nonstationary components. A max-heap propagates phase from strong coefficients to weaker neighbors in time or frequency; explicit peak picking and transient classification are unnecessary.

Standard time-gradient estimate is `omega_k + princarg(phi[m,k]-phi[m-1,k]-omega_k*H)/H`. Frequency gradients come from neighboring-bin wrapped phase differences. Centered differences use a future frame; the paper permits backward differences but favors centered ones. A causal variant therefore changes the approximation, while retaining centered differences costs one hop of lookahead.

Reproducible implementation: https://github.com/ltfat/phaseret/blob/main/sigproc/phasevocoder.m (); https://ltfat.org/phaseret/doc/gabor/rtpghi_code.html (). Confirm code licensing before reuse. The paper does not prove a complete sub-10-ms pitch-shift engine.

## 5. Luff 2023: Signalsmith Stretch design

Primary author explanation: https://signalsmith-audio.co.uk/writing/2023/stretch-design/ ().

The author describes amplitude mapping plus complex phase predictions from horizontal and vertical observations. Complex products encode phase differences and automatically weight stronger components. A first horizontal prediction pass feeds a second pass that propagates vertical relationships. Stereo uses the loudest channel for the phase prediction and copies interchannel phase differences.

Strong spectral peaks induce a nonlinear frequency map locally close to translation (slope 1), preventing stretched lobes from aliasing in downsampled subbands. The author explicitly discusses aliasing and current compromises. Optional tonality limiting reduces high-frequency remapping; it changes the transformation and should be a named option rather than assumed transparent transposition.

**Application inference:** this is a more appropriate phase engine reference than independent-bin Bernsee PV. Stretch design must not be attributed to proprietary Compose without evidence.

## 6. Polak & Erkut 2025: negative evidence for naïve STN hybrid

Primary PDF: https://pub.dega-akustik.de/DAS-DAGA_2025/files/upload/paper/635.pdf ().

Title: *Low-Latency Pitch-Shifting with STN Decomposition*. Despite the title, highest-quality configuration reports 7325 samples / **166.1 ms at 44.1 kHz**, comparing commercial baselines at approximately 158–163 ms. Sines use Signalsmith Stretch, transients bypass shifting, noise uses noise morphing plus resampling. Time-axis median filters become past-only for streaming.

Eight-person listening study rated the hybrid below commercial alternatives and even below its underlying Signalsmith library. Paper acknowledges normalization faults, possible loudness bias, and decomposition limitations. Useful research direction, but no evidence for live-guitar target latency. Independent FFT pipelines add cost/delay and mismatched component processing can break reconstruction.

**Application inference:** if decomposition is used, integrate masks into one shared analysis/synthesis pipeline; verify gain/phase and ablate every component. Unshifted transients are an approximation: guitar attacks can contain pitched energy, so universal transient bypass is risky.

## 7. Kraft, Holters, von dem Knesebeck & Zölzer 2012: improved PVSOLA

Primary PDF: https://www.dafx.de/paper-archive/2012/papers/dafx12_submission_26.pdf ().

Periodic phase resets can restore vertical coherence, but global time-domain correlation reset causes AM on polyphony/noise. This paper confines resets to detected sinusoidal components; noisy components continue through normal phase vocoding. It moves correlation to already available spectra, avoiding additional temporary future frames and drift. Transient handling and resampling complete the framework.

**Application inference:** global waveform alignment can be dominated by loudest partials; do not use one pitch-synchronous reset for arbitrary chords. Use selective per-region coherence decisions and a distinct treatment of noise rather than resetting every bin. Paper's reduced latency does not establish a 5–10-ms design.

## 8. Juillerat et al. 2008: Rollers subband frequency shifting

Author companion page: https://pitchtech.ch/Confs/ICALIP2008/Rollers.html ().

Uses multiple frequency shifts in separate bands to approximate pitch scaling; companion gives theoretical latency below 10 ms for a +30% example. The latency number must be read carefully because causal IIR filters have frequency-dependent delay.

Independent implementation/evaluation: Patrick Nolte 2021 master's thesis, *Latenzoptimierte Tonhöhenverschiebung polyphoner Gitarrensignale*; primary PDF https://reposit.haw-hamburg.de/bitstream/20.500.12738/15713/1/MA_Latenzoptimierte%20Tonh%C3%B6henverschiebung.pdf (, ). Its own Roller configuration reacts at high frequency around 1 ms but reaches about 62.5 ms group delay in low bands, with chirped/smeared impulses. Its assessment favors only modest shifts; block WSOLA fails dense chords and short PV windows lose spectral separation. These are results of that thesis's implementations, not universal impossibility proofs.

**Application inference:** measure frequency-dependent envelope delay and pitch settling. An early broadband impulse edge can hide late low fundamentals.

## 9. stftPitchShift: an existing permissive asymmetric-window reference

Primary repo: https://github.com/jurihock/stftPitchShift (), MIT.

C++ and Python implementation; spectral instantaneous-frequency encoding, magnitude/frequency remapping, cepstral formant processing, and asymmetric-window references. Useful for testing front-end geometry independently of a novel phase engine. Its phrase "poly pitch shifting" refers to mixing several shifted voices in one spectral frame, not a quality validation for arbitrary dense input polyphony. Its README warns formant preservation is problematic with that multi-voice mode and smaller pitch factors.

## 10. Further primary sources for scope and rejected shortcuts

- Driedger & Müller 2016 review, https://www.mdpi.com/2076-3417/6/2/57 (); author code toolbox https://github.com/groupmm/libtsm (). Harmonic/percussive handling is complementary; an offline time-stretcher's listening quality does not establish interactive delay.
- Thuillier 2016, *Real-time polyphonic octave doubling for the guitar*, https://aaltodoc.aalto.fi/items/6fd2cfc9-db61-4b0a-b11f-ea8c2925509f (). Constant-ERB non-decimated IIR subbands with phase doubling is relevant to octave-up effects but does not directly solve continuous ±12-semitone transposition. Full PDF fetch returned 403; abstract only inspected.
- PESTO2025 is a low-latency **single-pitch estimator**, not a polyphonic pitch-shifting engine. Avoid treating modern low-latency F0 papers as evidence of arbitrary chord reconstruction.

## Proposed experiments, not established results

1. First isolate window feasibility: identical scheduler, long past-heavy analysis, 256/384/480-sample synthesis supports, ratio1 null plus ±2/±7/±12 shifts. Compare against a matched-delay short symmetric STFT. A no-op null alone is insufficient.
2. Compare phase choices: independent-bin baseline, coherent peak-region translation, backward-gradient RTPGHI-style propagation, Signalsmith-style complex neighbor predictions. Change one module at a time.
3. Add a short analysis view solely for onset confidence and fresh envelopes; keep shared output scheduling. Track per-partial frequency/amplitude slope with bounded prediction from past frames. Do not use a single monophonic F0 assumption.
4. Design unresolved-region fallback: broad translated lobe/group with low confidence rather than unstable peak hopping. Score beating dyads, seconds, low drop tunings, and vibrato; pure-tone error is a useful early falsifier.
5. Evaluate attacks separately from stationary tails. Report first significant onset, 50% energy-envelope onset, low-band settling, steady cents error, unwanted modulation/sideband energy, and blind ratings against actual current Neural DSP and Compose renders.
6. Automation requires phase-continuous frequency integration and coefficient/mask smoothing with fixed reported latency; an output crossfade alone may produce beating. Count all scheduling hops, optional lookahead, resamplers, and host buffering explicitly.

No reviewed source proves Neural DSP parity. No novel architecture should be presented as production-ready before matched-delay listening tests and real-time deadline measurements.

## Addendum: Eventide filterbank technical disclosure

Earlier application US20250193632A1: https://patents.google.com/patent/US20250193632A1/en ().

Primary document PDF: https://patentimages.storage.googleapis.com/6c/23/10/dc031f9154f859/US20250193632A1.pdf (; PDF returned no extracted text).

Readable later-family transcription: https://patents.justia.com/patent/20260292437 (/); issued counterpart https://patents.justia.com/patent/12689866 (). Technical discussion only; no legal/FTO analysis.

Eventide disclosure by Corey Kereliuk, Woodrow Q. Herman and Russell Wedelich describes IIR Hilbert analytic signals, nonuniform narrow IIR bands, instantaneous magnitude/frequency estimation, frequency scaling, and oscillator-bank synthesis. Short moving averages smooth phase-increment frequency estimates. Higher bands receive tunable extra delay to reduce dispersive chirps. It discusses a below-15-ms design goal, not an independent quality benchmark. Adjacent-band IF agreement groups leaked peaks; changes in magnitude and IF inform transient classification. HTML equations contain apparent transcription errors and require checking before implementation. None of this establishes that Compose uses the method.

**Independent technical inference:** for two unresolved equal sinusoids, `z(t)=2*cos(pi*(f2-f1)*t)*exp(j*2*pi*(f1+f2)/2*t)`. A design that only scales instantaneous phase/frequency while retaining instantaneous amplitude does not automatically scale the beating envelope from `|f2-f1|` to `r*|f2-f1|`, as literal transposition would. Envelope zeros also destabilize IF. This gives a focused adversarial test for any one-frequency-per-subband candidate, irrespective of provenance.
