# Low-delay polyphonic pitch shifting: architecture proposal

Research date: 2026-10-08. Status: design hypotheses plus a verified unity reconstruction scaffold. No competitive-quality implementation or listening result is claimed. Scope: live VST3, primarily guitar lead/chords, general audio supported, ±12 semitones initially; engine delay preference 5–10 ms, maximum research target 15 ms.

## Recommendation

Investigate **complex spectral/subband transport with short, fixed synthesis support**, rather than reducing a conventional phase vocoder's FFT until it happens to meet a latency number. Two public-literature routes deserve separate prototypes:

1. A small-transform spectral remapper such as Ocean, as a reference baseline whose shortcomings are measurable.
2. A longer-history, asymmetric analysis/synthesis framework, with phase-coherent spectral atom transport and confidence-limited onset handling. This is the main proposed research direction, but its pitch-shifted quality remains unproven.

Do not begin with full polyphonic note transcription, a monophonic PSOLA tracker, a neural waveform generator, or a three-way STN pipeline. Those introduce additional failure modes or scope before the central question—preserving low-frequency mixtures at a short fixed delay—has been answered.

Signalsmith Compose advertises fixed 5–10 ms typical latency, spectral processing, chords, and transients [S1]. This is a competitive target, not a disclosure of its implementation and not an independent benchmark. Official-demo exported symbols reported by the forensic team (`inputReal`, `inputImag`, `inputHz`, `nominalBand`, `nominalHz`, `subRate`, and moved-output functions) are consistent with complex subband/frequency reassignment interfaces. They do not identify filter design, reconstruction mathematics, or pitch-shifting policy. The proposal here follows public DSP principles independently; it is not a claim to reproduce Compose.

## What the latency requirement actually means

At 48 kHz, 5/8/10/15 ms are 240/384/480/720 samples. Define and record separately:

* **Scheduled engine delay:** fixed sample offset declared to the host and used by a parallel dry path.
* **Effective response:** time until a shifted tone's envelope, pitch, and harmonic balance stabilize after a new note or chord change.
* **Frequency-dependent delay:** relative displacement of low/high-band envelopes.
* **Audio-system round trip:** engine plus interface, driver, host, device buffering, and any resampler/filter delays.

A quick impulse response does not establish fast bass response. A sample-by-sample recursive filter can emit immediately yet take tens of milliseconds to settle at low frequency. Conversely, a 2048-sample historical analysis does not necessarily require 2048 samples of future lookahead.

Useful physical scales, calculated from equal temperament A4=440 Hz:

| Note | Fundamental | Period |
|---|---:|---:|
| E2, standard guitar low E | 82.407 Hz | 12.135 ms |
| B1, common seven-string low B | 61.735 Hz | 16.198 ms |
| F#1, common eight-string low F# | 46.249 Hz | 21.622 ms |
| E1, bass low E | 41.203 Hz | 24.270 ms |

The E2–F2 separation is only about 4.9 Hz. An isolated 8 ms observation cannot robustly resolve arbitrary simultaneous low tones at that spacing under realistic noise. This is **not** a claim that one full period is always required for pitch estimation, nor a universal impossibility proof for perceptually good 8 ms shifting. Harmonics, history, and signal assumptions help. They do not reveal an unforeseen onset's future waveform. The hardest condition is a new low chord after silence or a dissonant chord transition.

## Evidence that changes the design

* **Peak-region transport:** Laroche and Dolson [S2] shift regions around spectral peaks together and accumulate the required frequency-change phase. This preserves local relative phases. Fractional-bin interpolation can create amplitude modulation; their demonstrated linear interpolator needs more overlap than integer-bin shifting. Treat interpolator sidelobes and overlap as quality parameters, not implementation details.
* **Asymmetric analysis/synthesis:** Mauler and Martin [S3] show long analysis with short synthesis, with perfect reconstruction when spectra are unmodified. They explicitly warn that spectral edits can break alias cancellation; their block-system delay includes synthesis support, processing buffers, and modification group delay. Therefore a unity null test proves the framework only. The present scaffold generalizes the product-window condition to four overlaps; it does not validate arbitrary pitch remapping.
* **Modern asymmetric-window example:** Wang et al. [S4] demonstrate an 8 ms setting in speech separation. The relevance is the analysis/synthesis technique. Their results do not establish instrument pitch-shifting quality or equivalence to a real-time transposer.
* **Phase relationships:** Signalsmith's public Stretch design [S5] emphasizes phase information across both time and frequency and preserves channel relationships. Its local frequency map avoids widening strong spectral lobes. These are useful public design ideas, while Stretch and proprietary Compose must remain distinct.
* **Misleading use of “low latency”:** Polak and Erkut's 2025 STN paper [S6] reports up to 166.1 ms, and lower ratings than its commercial comparators. It is useful evidence about decomposition and reconstruction risks, not a 5–10 ms solution. Its simplified premise that transients contain no pitch should not become a rule for guitar: a pick attack can include pitched string/body resonances.
* **Guitar-specific warning:** Nolte's 2021 thesis [S7] found major low-delay artifacts in the configurations tested. Its Roller implementation reacted rapidly at high frequencies while low-frequency delay reached roughly 62.5 ms. These are implementation-specific findings, not proof that all later algorithms must fail. They justify band-specific onset tests and subjective evaluation.
* **Small-transform baseline:** Juillerat and Hirsbrunner's Ocean work [S8] is a relevant public reference for avoiding unreliable instantaneous-frequency estimates in very short spectra. The paper/source agent has retained its reference source and errata. Its startup delay and tonal errors must be measured independently of the publication's quality claims.

## Proposed core: spectral transport at fixed output timing

Everything in this section is a **proposed implementation**, not a measured result unless explicitly identified.

Let semitone control be s(t), and pitch ratio r(t)=2^(s(t)/12). The processor accepts arbitrary host block sizes; its internal hop is independent of the host block. All memory, FFT plans, interpolation tables, and ring buffers are allocated in preparation, never in the audio callback.

### A. Analysis and reconstruction scaffold

Initial 48 kHz configuration:

| Parameter | Proposed value | Purpose |
|---|---:|---|
| Analysis/FFT length N | 2048 samples, 42.667 ms | Past context for stable partials |
| Recent synthesis support L | 384 samples, 8 ms | Bound scheduled output delay |
| Hop H | 96 samples, 2 ms | Four-way synthesis overlap |
| Frame rate | 500 Hz | Control and spectral update rate |
| Declared core delay D | 383 samples, 7.979 ms | Sample-indexed schedule, no extra FIFO |
| Optional diagnostic short analysis | 512 samples | Detect unreliable new attacks |

For indices 0≤n<N, put P=N−L/2. Define the analysis window:

```
A[n] = sin(pi*n/(2*P))                       for n < P
A[n] = cos(pi*(n-P)/(2*(N-P)))               for n >= P
```

For q=n−(N−L) in the newest L samples, set

```
g[q] = (1 - cos(2*pi*q/L)) / (L/H)
S[n] = g[q]/A[n]                            for N-L <= n < N
S[n] = 0                                   otherwise
```

This gives sum_m A[n−mH]S[n−mH]=1. The current scaffold uses double precision and does not energy-normalize analysis; any later normalization must be canceled consistently in synthesis.

**Exact scheduling:** A frame available at input index t analyzes x[t−N+1 … t]. Its synthesis support corresponds to original indices t−L+1 … t. Add each output contribution into the output ring at that original index plus D=L−1. The earliest scheduled position is t, so the frame needs no future input. Compute the frame before emitting the associated output sample. A separate block-output FIFO may add H or a host block; measure and declare that if used. This convention differs by buffer scheduling and endpoint convention from papers that count an additional processing block.

The saved experiment verifies delayed identity at all 96 hop phases. It does **not** move frequency bins. Results:

* Impulse delay: 383 samples at every tested phase.
* Worst impulse absolute reconstruction error: 3.33×10^-16.
* Maximum COLA deviation: 2.22×10^-16.
* Maximum synthesis coefficient: 0.5.
* Analysis energy centroid: 685.8 samples / 14.29 ms before the frame end.

That centroid is not an audio-output delay. It demonstrates why old spectral evidence may dominate after an onset even when the scheduled delay is 8 ms.

Files: `architecture-experiment/architecture-experiment.py` and `architecture-experiment/results.json`.

### B. Represent the spectrum as transportable complex regions

Use one shared energy map across channels to locate peaks and regions of influence. Start with simple local maxima plus parabolic interpolation, then add temporally linked regions. For well-resolved, stable peaks, estimate frequency from the unwrapped phase increment:

```
omega_hat[k,m] = omega_k
  + principal_arg(X[k,m] * conj(X[k,m-1]) * exp(-j*omega_k*H)) / H
```

Angles are radians per sample. Under noise, colliding partials, or onsets, this estimator can be misleading. Attach confidence from local peak isolation, amplitude stability, phase-increment consistency, and agreement with nearby bins. Do not force a single fundamental on a chord. Use the analysis window's known complex frequency response when testing any magnitude peak estimator: symmetric-window assumptions do not automatically hold for an asymmetric window.

For a region p centered at omega_p, target r*omega_p; translate its lobe locally by delta_p=(r−1)*omega_p rather than stretching every lobe's width by r. Maintain a continuous regional phase rotation. With all spectra expressed relative to the same advancing frame reference:

```
theta[p,m] = theta[p,m-1]
             + H * (delta[p,m-1] + delta[p,m]) / 2
```

Use the same rotation across each region's bins. Fractionally move complex coefficients through a calibrated interpolation kernel and sum overlaps. Resolve sign conventions against a single analytic sinusoid before processing real audio. Add Hermitian symmetry only after the positive-frequency transport; handle DC/Nyquist explicitly.

When regions appear/disappear or peaks merge, a phase state must transfer continuously rather than reset arbitrarily. Retain identity state across a ratio crossing of 1.0. This tracking problem is likely a larger quality lever than adding FFT bins.

**Residual bins:** The first prototype should transport them using the same continuous complex mapping. Add stochastic/noise-specific processing only after a demonstrated failure, because randomized residual phases can smear pick attacks, hiss modulation, and stereo information.

### C. Alternative formulation: a complex modulated filterbank

An STFT can be viewed as downsampled complex subbands. A custom oversampled analysis/synthesis bank could expose each band's complex value, nominal frequency, and estimated instantaneous frequency. Move its energy to output bands and integrate phase at the desired frequency, using neighboring bands to recover coherent envelopes. This is an independently plausible research route; exported API names alone do not establish that any vendor uses this particular algorithm. The forensic team's later observation of a nonlinear low-frequency `nominalBand` branch and an affine high-frequency branch makes nonuniform low-band spacing a useful additional experiment. It does not prove a constant-Q transform. Its observed default 2.5 ms update period is likewise a cadence, not a measurement of total latency.

Advantages to investigate: control analysis memory separately from synthesis support; frequency-dependent analysis bandwidth; phase rotation at a subband rate; possible pruned transforms. Risks: alias-cancellation failure when bands are moved, amplitude ripple, band-crossing artifacts, and unequal group delay. A sliding DFT or IIR bank does not remove these risks merely because it updates each sample. Keep this as a second reconstruction design after the WOLA prototype demonstrates the exact failure to fix.

**Adversarial unresolved-dyad example (mathematical inference):**

```
z(t) = exp(j*2*pi*f1*t) + exp(j*2*pi*f2*t)
     = 2*cos(pi*(f2-f1)*t)*exp(j*2*pi*((f1+f2)/2)*t)
```

If both tones occupy one region, scaling only its carrier/instantaneous frequency while keeping its amplitude envelope retains the old beat spacing. A true pitch transposition needs that spacing multiplied by r. Instantaneous frequency is also ill-conditioned near amplitude nulls. Rigidly translating one unresolved region has the same limitation: it preserves f2−f1 instead of r(f2−f1). Longer context, more separation, or an explicitly modeled within-band evolution is needed; an oscillator bank cannot eliminate this uncertainty by itself. Include this example before accepting a bank-based design on isolated-tone results.

### D. Onsets and changes: preserve confidence, not a universal dry transient

Use recent amplitude growth and a short-window spectral flux measure to mark unreliable regions. Initially, compare three explicit ablations:

1. Long-window transport only.
2. Short-history transport at onsets with the same declared synthesis delay.
3. Continuous confidence blending between the two, with common phase anchors and gain normalization.

Do not mix an unshifted full-band attack into every shifted chord: it can produce two pitches, especially when the attack lasts several cycles. If a later noise/transient residual is preserved, bound it spectrally and measure residual original-pitch energy. A sample-aligned dry path can still comb with a processed path because their phases differ.

### E. Automation, stereo, and bandwidth

Interpolate semitone control at sample resolution; use integrated frequency changes in phase evolution, not independent phase resets at parameter events. Test both a short optional smoothing ramp and immediate sample-stamped events. Shifting-control latency is a distinct measurement from signal latency. Keep the declared delay fixed across all ratios, and timestamp control against the input event whose output emerges D samples later.

Stereo channels share region boundaries, destination mappings, confidence, and onset decisions. Carry original channel phase differences through the same transform. Choose a reference from channel power with hysteresis rather than relying only on L+R, which cancels antiphase signals. Check mono compatibility and decorrelation explicitly.

For r>1, taper source content approaching the new Nyquist limit; measure aliases instead of assuming discarded FFT bins suffice. For r<1, manage overlap density and coherent region collisions without arbitrary automatic gain pumping. Keep formant preservation optional and off in the first guitar prototype. An envelope suitable for vocals is not necessarily the desired guitar pickup/body response.

At 96 kHz, scale time constants and sample counts; do not retain the same N and silently halve the analysis history. An internal 48 kHz path could reduce cost, but its resampler delay and passband must fit the 15 ms limit. First implement native-rate processing to keep that tradeoff visible.

## Candidate experiments and acceptance gates

| Experiment | Conditions | Question / rejection signal |
|---|---|---|
| Delayed wire | Every hop phase, noise/DC/tones, reset/tail | PR and exact schedule; already passed in NumPy |
| Single-tone transport | 20 Hz–20 kHz, off-bin frequencies, ±1/2/5/7/12 st | Pitch error, AM sidebands, gain ripple; no instrument masking |
| Two close sinusoids | Low semitone/detuned pairs, unequal amplitudes | Regional merging and estimator failure |
| Known synthetic onset | Harmonic stack with specified envelope; new chord after silence | Envelope 10/50/90% timing, false precursor, original-pitch residue |
| Overlapping note change | Sustain one chord, introduce another; vibrato/bends | Stale-history blending and tracking reassignment |
| Guitar DI | Open/dense chords, palm mutes, low tuning, leads | Blind listening against exact Neural version and Compose build |
| General audio | Bass, piano, acoustic guitar, vocal, drums, full mix | Whether guitar tuning breaks generality |
| Automation | Static steps, sweeps, ratio=1 crossings | Clicks, state discontinuities, control delay |
| Stereo | L=R, L=−R, single-sided, moving pan, diffuse reverb | Shared state, balance, mono compatibility |
| Callback stress | 16/32/64/128 sample host blocks, 44.1/48/96 kHz | Worst-case deadline, independent of average CPU |

The synthetic reference is only a ground truth for the defined mathematical input. A real played transposed guitar is not a bit-exact target because the instrument's physical response changes. Do not use PESQ or an unqualified waveform SNR as the primary musical-quality score. Include level-matched blind preference/quality ratings and live playing. Compare at measured equivalent delay where possible, and report native competitor configurations separately.

**Suggested pass targets, not measurements:** stable isolated-tone error below 1 cent; unintentional tonal sidebands below −60 dBc in the central range; no frequency band with additional onset displacement above 2 ms relative to the declared delay on the synthetic benchmark; callback p99.99 below 25% of the block deadline on a named desktop CPU. These targets can change after correlating measurements with audibility. A single FFT operation count cannot validate real-time safety.

For stereo N=2048/H=96, two forward and two inverse transforms imply roughly 45 million `N log2 N` transform-size units per second, before spectral work. This is a scaling estimate, not FLOP accounting or a measured CPU load. At 32-sample blocks, a transform burst has a 0.667 ms callback window at 48 kHz; optimize the worst burst, not just the 2 ms average frame period. Avoid audio-thread allocation, locks, file access, and uncontrolled worker synchronization.

## Decision rule

Continue the asymmetric route only if shifted pure tones and synthetic onsets simultaneously improve over the small-transform baseline at the same declared delay. If spectrum modifications produce irreducible circular/time aliasing or historical smearing, retain the verified scheduler and replace the analysis/synthesis transport with a more oversampled bank or shorter/multiple causal observations. Do not call the framework competitive until the actual guitar benchmark and player tests support that conclusion.

## Primary sources

All accessed 2026-10-08. Links are retained so future sessions need not rely on temporary citation IDs.

* **S1:** Signalsmith Audio, *Signalsmith Compose*, vendor claims. https://compose.signalsmith-audio.co.uk/ — web ref ``.
* **S2:** J. Laroche and M. Dolson, *New Phase-Vocoder Techniques for Pitch-Shifting, Harmonizing and Other Exotic Effects*, WASPAA 1999. https://www.ee.columbia.edu/~dpwe/papers/LaroD99-pvoc.pdf — web ref ``.
* **S3:** D. Mauler and R. Martin, *A Low Delay, Variable Resolution, Perfect Reconstruction Spectral Analysis-Synthesis System for Speech Enhancement*, EUSIPCO 2007. https://www.eurasip.org/Proceedings/Eusipco/Eusipco2007/Papers/A2L-D02.pdf — web ref ``.
* **S4:** S. Wang et al., *Deep Neural Network Based Low-Latency Speech Separation with Asymmetric Analysis-Synthesis Window Pair*, 2021. https://arxiv.org/abs/2106.11794 — HTML https://arxiv.org/html/2106.11794v1 — web refs ``, ``.
* **S5:** G. Luff, *The Design of Signalsmith Stretch*, 2023. https://signalsmith-audio.co.uk/writing/2023/stretch-design/ — web ref ``.
* **S6:** M. Polak and C. Erkut, *Low-Latency Pitch-Shifting with STN Decomposition*, DAS-DAGA 2025, pp. 476–479, DOI 10.71568/dasdaga2025.635. https://pub.dega-akustik.de/DAS-DAGA_2025/files/upload/paper/635.pdf — web ref ``.
* **S7:** P. Nolte, *Latenzoptimierte Tonhöhenverschiebung polyphoner Gitarrensignale*, master's thesis, 2021. https://reposit.haw-hamburg.de/handle/20.500.12738/15713 — web refs ``, ``.
* **S8:** N. Juillerat and B. Hirsbrunner, *Low Latency Audio Pitch Shifting in the Frequency Domain*, ICALIP 2010, DOI 10.1109/ICALIP.2010.5685027. Author publication/source index: https://pitchtech.ch/ — errata: https://pitchtech.ch/Confs/ICALIP2010/Errata.txt — web refs ``, ``.
