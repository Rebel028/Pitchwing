# Improvement options for the fixed-delay region-transport engine

Date: 2026-10-10. Desk research only: no build, no audio run. Sources are the
seven repository documents listed at the end plus targeted web reads made
today. Every "expected" statement below is a hypothesis; the only measurements
are those in `experiments/transport/FINDINGS.md` and the cited papers.

Fixed constraints (not negotiable here): $N=2048$ past-heavy analysis, $L=384$
synthesis support, $H=96$, $D=479$ samples at 48 kHz, frame work finished inside
the hop. Every candidate adds 0 samples of scheduled delay unless stated.
CPU baseline per 96-sample hop: ~2 FFT(2048) analysis + up to 64 region
IFFT(2048) per channel (stereo: separate region IFFTs per channel). A radix-2
complex FFT(2048) is roughly $5 \cdot N \cdot \log_2(N)$ ~ 1.1e5 flop, so the region IFFTs
dominate at ~7e6 flop/hop/channel when 64 regions are live.

## One new diagnosis from existing data

FINDINGS reports isolated E2 errors of +7.03 cents at -7 st and -4.71 cents at
+7 st. If the transport is exact and only the region frequency estimate
$\hat{\omega}$ is biased, the output lands at $\omega + (r-1)\hat{\omega}$, so the
cents error scales as $(r-1)/r$: -0.5 for $r=2^{-7/12}$ and +0.333 for
$r=2^{7/12}$, ratio -1.5. Measured ratio $7.03/-4.71 = -1.49$. So the E2 defect is a
frequency-estimate bias of about -14 cents (0.03 bin at bin 3.5), not a
transport fault. Candidate 2 targets exactly this; its test is cheap.

## Ranked candidates

Ranking = expected quality gain per unit of risk and effort, given the fixed
delay. Items 1-5 are low-risk corrections; 6-7 are the real quality levers
and carry the most risk; 8 is an enabler; 9-10 are options.

### 1. Gated ancestry with birth/death and hysteresis

- Defect: nearest-ancestor inheritance has no distance gate (FINDINGS, live-engine.md);
  new notes inherit an unrelated region's rotation theta, and flickering peaks
  (sidelobes near the 1e-4 floor) create one-frame regions that steal/lose state.
- Mechanism, per frame after peak picking:
  ```
  for each new region p:   ancestor = argmin_q |omega_p - omega_q(prev)|
      accept only if |omega_p - omega_q| < g_bins*dOmega  (g_bins ~ 1.0 at N=2048)
                 and |log(A_p/A_q)| < 12 dB
      else: birth -> theta_p = 0 (identity phase at frame end), age_p = 0
  region q with no child: keep as zombie for K_dead frames (K=3) so a 1-frame
      dropout re-links instead of re-birthing; emit nothing for zombies.
  peak admission hysteresis: enter at floor*2, leave at floor/2 (per-region).
  confidence c_p = min(1, age_p/4) * phase_consistency_p   (feeds 6, 7)
  ```
  Birth with $\theta=0$ is the correct default for this engine: the synthesis
  support is the newest windowed input, so zero rotation reproduces the fresh
  waveform at the translated frequency with no history assumption.
- Evidence: architecture.md B and D08 call this "likely a larger quality lever
  than adding FFT bins" (design claim). Rubber Band R3 `PhaseAdvance.h` keys the
  locked-bin phase on previous-peak identity (`m_prevPeaks`) and only channel-
  locks when both channels map to the same previous peak (source, GPL, read
  only). McAulay-Quatieri/PARSHL birth-death matching is the classical form
  (https://ccrma.stanford.edu/~jos/parshl/parshl.pdf). No source measures the
  audible effect in a fixed-delay shifter; the FINDINGS defect is observational.
- Latency: 0. CPU: negligible (<=64 regions, $O(R)$ matching).
- Risks: a gate that is too tight re-births vibrato/bends every frame (phase
  restart = click-like AM); too loose keeps today's behaviour. Zombie frames can
  mis-link a genuinely new note to a just-died one at the same bin.
- Test: 4 s A3 (220 Hz, 8 harmonics) + at t=2 s C#4 (277 Hz, -6 dB) + at
  t=3 s a 0.5 Hz, $\pm 12$ dB tremolo on C#4. Shift +7. Metric: NumPy STFT (4096,
  hop 256) of output; track peak-bin phase of $r \cdot 220$ Hz;
  $\max|\mathrm{unwrap}(\text{phase}) - \text{linear fit}|$ over 1.8-3.8 s. Pass < 0.15 rad (no phase kick on neighbour
  birth/death). Second metric: output energy at $r \cdot 277$ Hz in the 20 ms before
  t=2 s < -60 dB re its steady level (no pre-echo from stolen ancestry).

### 2. Window-matched / phase-based region frequency estimate

- Defect: E2 bias ~-14 cents (diagnosis above); B0/E1 are <1 cent, so the bias
  is position-dependent, consistent with a parabolic fit applied to the
  asymmetric window's non-parabolic, non-symmetric main lobe at a fractional
  bin offset, or with the phase-difference "sanity gate" rejecting the phase
  estimate and falling back to the biased magnitude fit.
- Mechanism:
  ```
  (a) tabulate |A(omega)| of the actual analysis window at 1/64-bin steps once;
      estimate omega_p by least squares of the 3-5 peak bins against the table
      (replaces the log-parabola, which assumes a Gaussian lobe).
  (b) prefer the phase-increment estimate when consistent across the lobe:
      w_k = omega_k + princarg(X[k,m]conj(X[k,m-1])e^{-j omega_k H})/H
      accept if std(w_k over 3 lobe bins) < 0.1 bin and age_p >= 2.
  (c) smooth per region: omega_p <- omega_p + 0.5*(w - omega_p)  (1 frame lag).
  ```
- Evidence: Laroche-Dolson 1999 state the parabola is exact only for a Gaussian
  window in dB (paper text, Sect. 3.3). Betser-Collen-Richard EUSIPCO 2006
  derive adjacent-bin estimators for non-rectangular windows
  (https://new.eurasip.org/Proceedings/Eusipco/Eusipco2006/papers/1568981578.pdf,
  not re-read today). architecture.md B already warns that symmetric-window
  assumptions do not hold. The -1.5 ratio is a measurement from FINDINGS.
- Latency: 0. CPU: negligible.
- Risks: phase estimate is wrong during onsets and in unresolved regions
  (ill-conditioned near beat nulls, D07); keep the gate and the age criterion.
- Test: 10 s mono, 20 tones of 0.5 s each, frequencies at bins 2.0, 2.3, ...,
  9.7 (47-227 Hz), shifts -7 and +7. Metric: zero-padded FFT (2^18) on the
  middle 0.3 s of each tone, parabolic peak, cents vs $r \cdot f$. Pass: $|\text{error}| < 1$
  cent for all 40 cases (today's E2 point fails at 7 cents).

### 3. Soft region boundaries at magnitude valleys (within-region phase locking)

- Defect: regions are partitioned at midpoints; a bin that changes region
  between frames jumps from rotation $\theta_A$ to $\theta_B$, an abrupt phase step on
  that bin's leakage energy (hop-rate AM/clicks). Not yet measured here.
- Mechanism (no extra transforms: masks overlap, IFFT count unchanged):
  ```
  boundary b between peaks p,q := argmin |X[k]| for k in (k_p, k_q)   (valley)
  mask_p[k] = 1 for k <= b-w, cos^2 ramp over (b-w, b+w), 0 beyond; w = 1 bin
  mask_q = 1 - mask_p on the ramp.  Each boundary bin contributes to both
  region IFFTs with weights summing to 1, so a boundary move changes a bin's
  rotation gradually over the ramp instead of stepping.
  ```
  This is the identity-phase-locking property of Laroche-Dolson applied with a
  soft partition. Rubber Band's `beta` partial locking (`ph = peakNew +
  beta*diff`) is the time-stretch analogue and does not transfer directly.
- Evidence: Laroche-Dolson 1999 offer midpoint or lowest-magnitude boundaries
  (paper text, Sect. 3.2) and state identity locking "dramatically" reduces
  phasiness (their 1999 TSAP paper; claim restated, no numbers here). Soft
  masks are an inference, unmeasured.
- Latency: 0. CPU: +2 bins per boundary per IFFT input, negligible.
- Risks: the valley wanders by several bins when partials beat, so the ramp
  moves anyway; $w>2$ blurs the translation of close partials.
- Test: 8 s mono: 300 Hz + 345 Hz (2 bins apart), 345 Hz with 0.5 Hz, $\pm 10$ dB
  tremolo; shift +7. Metric: output STFT (8192, hop 96); energy outside
  $\pm 4$ Hz of $r \cdot 300$ and $r \cdot 345$ (excluding tremolo sidebands at $\pm 0.5$ Hz)
  relative to total, and spectrum of the $r \cdot 300$ envelope at 500 Hz (hop rate).
  Pass: sideband energy < -50 dBc and hop-rate envelope line < -50 dB re DC.
  Measure the current engine first; if it already passes, drop this item.

### 4. Alias guard using the support's maximum ratio and a source low-pass

- Defect: the 2-bin taper uses the frame-end ratio only; a short upward
  excursion inside the saved L-sample control history can push a region above
  the new Nyquist, where the analytic modulation folds into negative frequency
  and the real part aliases (live-engine.md states no dynamic alias proof).
- Mechanism:
  ```
  r_max = max over the frame's control snapshot u[t-L+1..t] of (1+u)
  for region p with top bin k_top: dest_top = k_top + (r_max-1)*omega_p/dOmega
  gain_p = 1 if dest_top < K_ny - 4; cos^2 taper to 0 over 4 bins; 0 beyond
  drop source bins k > K_ny / r_max - 2 before region formation
  downward: regions whose dest bottom < 0 are mirrored with conjugation
  (Laroche-Dolson) rather than left to fold at |omega+delta|.
  ```
- Evidence: Laroche-Dolson 1999 reflect negative-frequency spill with
  conjugation (paper text, Sect. 3.4). The rest is bookkeeping; no measurement.
- Latency: 0. CPU: negligible.
- Risks: at +12 st everything above 12 kHz is dropped: audible on bright DI only.
- Test: 6 s mono bandlimited sawtooth at 1 kHz (partials to 23.9 kHz); shift
  +12 steady, then a 50 ms ramp from 0 to +12 at t=3 s. Metric: STFT (8192);
  energy at bins farther than $\pm 6$ Hz from any multiple of $r(t) \cdot 1$ kHz relative
  to total, in the 4-24 kHz band. Pass: < -60 dB both during and after the ramp.

### 5. Explicit DC / sub-bin policy

- Defect (measured): constant 0.2 -> mean 0.023 (+7) / 0.279 (-7) with AC
  residue (FINDINGS). Cause: the windowed constant occupies bins 0..~2; the peak
  picker puts a region on the leakage, translates it by $(r-1)\omega_{\mathrm{region}}$, and
  the analytic (positive-frequency-only) reconstruction of a DC-centred lobe is
  not Hermitian-correct.
- Mechanism (two policies; pick one and write it into PROJECT.md):
  ```
  Policy A (preserve): bins with omega < omega_dc (25 Hz, ~1.07 bins) form a
    fixed untranslated "DC region" reconstructed with the real spectrum
    (bin 0 once, bins 1.. with Hermitian pair), delta = 0, theta = 0.
    Peak picking starts at bin 2. Content 25-47 Hz stays translatable.
  Policy B (reject): 1st-order high-pass at 5 Hz on the input; declare DC
    out of scope; still exclude bin 0 from regions.
  ```
  Policy B is cheaper and matches guitar/bass pickups (no DC); its cost is a
  phase lead of ~3.5 degrees at 82 Hz and ~7 degrees at 41 Hz, not a delay.
- Evidence: FINDINGS numbers; architecture.md B ("handle DC/Nyquist
  explicitly"). No external source measures DC in shifters; it is a design gap.
- Latency: 0. CPU: negligible.
- Risks: Policy A's fixed region can capture the lower lobe of B0/E1 fundamentals
  (bins 1.3 and 1.76) if $\omega_{\mathrm{dc}}$ is set above ~25 Hz; bass extension (E1 =
  41 Hz) bounds $\omega_{\mathrm{dc}}$ from above.
- Test: 6 s mono: 0.2 DC + E2 (82.4 Hz) at 0.1 + E1 (41.2 Hz) at 0.1, shifts
  $\pm 7$. Policy A pass: mean over 1-5 s within $0.2 \pm 0.002$ and shifted E2/E1
  line levels within 0.2 dB of the no-DC run. Policy B pass: $|\text{mean}| < 10^{-3}$ and
  E2/E1 line levels within 0.2 dB of the no-DC run, AC residue < 1e-3 RMS.

### 6. Past-only onset score with region-local phase re-anchor and region widening

- Defect: no transient handling; +7 low-chord onset crosses the envelope
  threshold ~3.27 ms late (FINDINGS, 20 ms RMS diagnostic). Mechanism of the
  lag: a region mask of $B$ bins is a bandpass with a ~$N/B$-sample kernel; narrow
  regions smear a fresh attack over hundreds of samples before translation.
  Stale ancestry rotation on the attack adds phase inconsistency.
- Mechanism:
  ```
  detection (causal, per hop): FFT(512) of the newest 512 input samples
     (shared across channels via hypot); per band b (e.g. 8 bands):
     flux_b = sum_k max(0, |S_b[k,m]| - |S_b[k,m-1]|)
     onset_b = flux_b / (median of flux_b over last 16 frames + eps)
     region p is "onset" if onset_b(omega_p) > T (T ~ 3) and the region is
     young (age_p <= 2) or its magnitude rose > 6 dB in one hop.
  action per onset region (region-local, never global):
     theta_p := 0 (re-anchor to the input's own phase at the frame end);
     widen: merge onset regions with adjacent onset regions in the same band
     into one region translated by the band's energy-weighted omega
     (shorter mask kernel, sharper attack, pitch error only during 2-3 frames);
     c_p := 0 for 4 frames (blocks 7's long-history model).
  ```
  The dry/unshifted transient path is deliberately absent (see Not-to-do).
- Evidence: Rubber Band R3 resets phase (copies input phase) only inside
  guided frequency ranges derived from per-bin harmonic/percussive/residual
  classes with a modal filter, and single-window live mode keeps the reset and
  "high unlocked" logic (`Guide.h`, `BinSegmenter.h`, `PhaseAdvance.h`, GPL,
  read only; its classification uses one frame of readahead in the offline
  path, which we cannot use). Kraft et al. 2012 show global resets cause AM on
  polyphony and confine resets to sinusoidal components (papers.md 7, paper
  measured). Röbel DAFx 2003 detects/resets per bin and reports better
  detection than a prior method on a labelled set (abstract only,
  https://hal.archives-ouvertes.fr/hal-01161124). Dixon DAFx 2006 reports
  spectral flux, weighted phase deviation and complex difference all perform
  well as causal functions (search summary, not re-read). Signalsmith Stretch
  has no transient handling through tag 1.4.0 (design note + tags page).
  The widening step is an inference from the mask-kernel argument; unmeasured.
- Latency: 0 (uses only past samples). CPU: +1 FFT(512) per hop (~+2% of the
  64-region baseline) plus $O(R)$.
- Risks: false onsets on bends/vibrato (2024 paper on ornamentation false
  positives, https://arxiv.org/html/2408.13734v1, abstract) re-anchor sustained
  notes and produce AM; widening detunes partials near the widened band for a
  few frames; picks with pitched content get the band's omega, not their own.
- Test: 8 s mono: silence 0.5 s, then every 1 s an alternating synthetic chord
  (E2-B2-E3-G#3 / D2-A2-D3-F#3, 10 harmonics each, 1 ms attack, 0.5 s decay)
  on top of a continuous A4 at -20 dB; shifts $\pm 7$. Metrics after D alignment:
  (a) 50% RMS-envelope (5 ms window) crossing delay vs the $r$-scaled reference
  chord; pass < 1.5 ms (re-measure today's engine with this exact fixture
  first). (b) energy in the 10 ms before each onset < -60 dB re peak. (c) phase
  of $r \cdot \text{A4}$ (STFT 4096 peak-bin, unwrapped) deviation from linear < 0.15 rad
  across all onsets (region-locality). (d) chord pitch lines at 100-300 ms
  after onset within 3 cents of $r \cdot f$.

### 7. Low-band long-history estimator with parametric transport for unresolved partials

- Defect (measured, the central failure): unresolved dyads keep original beat
  spacing (B0/C1, E1/F1 at both shifts; FINDINGS table). At N=2048 the bin
  spacing is 23.4 Hz, so E2+G2 (15.6 Hz), E2+A2 (27.6 Hz), D2+A2 (36.6 Hz) are
  also one lobe. Rigid translation cannot fix this (D07); nor can better
  single-frequency estimates (FINDINGS decision).
- Mechanism (low band only, e.g. regions with $\omega_p < 350$ Hz):
  ```
  (a) zoom analysis: decimate input by 8 (halfband chain, past-only), keep a
      16384-sample history at 6 kHz (2.7 s) but use FFT(2048) over the newest
      2048 decimated samples = 341 ms, bin spacing 2.93 Hz; one FFT per hop.
      Resolves E2/G2, E2/A2, D2/A2, E2/F2 (4.9 Hz) in magnitude.
  (b) for each 2048-bin low region p: list zoom peaks inside its band:
      {(f_i, a_i, phi_i)}; if >= 2 peaks with a_i > 0.1*max and c_p > 0.5:
      synthesize the region parametrically over the support instead of
      translating it:
        y_p[n] = sum_i a_i(n) cos(r*2*pi*f_i*(n - t)/fs + psi_i)
        psi_i integrated per component like theta_p (sample-accurate control),
        a_i(n) = a_i * |z_p[n]| / |z_p|_rms   (reuse the region's own short-
        support envelope so attacks still come from the 8 ms path).
      else: rigid translation as today.
  (c) optional sub-Rayleigh refinement: order-2 matrix pencil on the zoom peak
      bin's complex sequence over the last 64-128 hop-rate samples for pairs
      with |f1-f2| < 2 zoom bins.
  ```
  (a)+(b) is what architecture.md C/D proposed ("explicitly modeled
  within-band evolution"); the zoom path adds 0 scheduled delay because it only
  reads history, but its estimates lag by up to half its window (~170 ms
  energy centroid), hence the confidence gate from items 1 and 6.
- Evidence: the FINDINGS dyad table; the two-tone identity in papers.md
  (addendum); Laroche ASA 1994 used matrix pencil on closely spaced piano
  partials at "high computational cost" (abstract,
  https://auditory.org/asamtgs/asa94mit/4aMU/4aMU4.html); Das-Abel-Smith
  DAFx-18 fast MUSIC on close piano partials
  (https://ccrma.stanford.edu/~orchi/Documents/DAFx18_fast_music.pdf); Halder-
  Kailath 1997 report MUSIC/ESPRIT degrade for closely spaced frequencies.
  Eventide's filterbank disclosure groups bands by instantaneous-frequency
  agreement (papers.md addendum; patent text, no measurement). The Compose
  forensics show a nonuniform low-band grid and a 2.5 ms sub-rate (observed,
  not an algorithm). None of these measure a fixed-delay shifter.
- Latency: 0 scheduled. Settling: components appear in the zoom analysis
  ~100-170 ms after onset; until then rigid translation (today's behaviour).
  CPU: decimation chain + 1 FFT(2048) per hop on the decimated stream (~+1.5%)
  + per-component oscillators over 384 samples (~1e3 flop per component per
  hop, trivial); matrix pencil on 128 samples ~1e6 flop per update, run every
  8 hops for <= 8 regions: ~+15% worst case.
- Risks: wrong model during chord changes for ~0.2 s (two notes overlapping in
  the zoom window = four components); amplitude seam between parametric and
  translated regions; beat-null phase instability (D07) in step (c); a
  B0/C1-type pair (1.8 Hz) needs > 0.5 s of stable history and will not be
  met by this candidate (say so in the acceptance). Decimation filter group
  delay only affects the estimator, not output timing.
- Test: 9 s mono: E2+F2 (4.9 Hz) 0-3 s, E2+A2 (27.6 Hz) 3-6 s, E1+F1 (2.45 Hz)
  6-9 s, equal amplitudes; shifts $\pm 7$. Metric (existing FINDINGS method):
  $2^{17}$-point FFT of the last 1.5 s of each segment; spacing of the two
  strongest lines; pass $|\text{spacing} - r \cdot df|/(r \cdot df) < 5\%$ and >= 80% of AC energy
  within $\pm 1$ Hz of the two expected lines for E2+F2 and E2+A2; report E1+F1
  as informational (expected to need longer history). Baseline: 0.2-3.8%.

### 8. Cheaper synthesis: direct support evaluation (per-bin modulation at fixed cost)

- Defect: cost scales with region count (64 IFFT(2048) per channel per hop for
  384 used samples each: >80% of every IFFT is discarded), and the per-region
  structure forbids per-bin frequency maps (needed by 3's soft ramps, 9, 10).
- Mechanism:
  ```
  y[n] = Re( sum_k X[k] * e^{j( (omega_k + delta(k)) * n + theta(k) )} ),
         n in the 384-sample support, k over positive bins (<= 1024 live);
  delta(k) = (r-1)*omega_{region(k)} today; any per-bin map later.
  Implement as complex recurrences per bin (rotate by e^{j(omega_k+delta_k)}
  per sample), re-anchored exactly every 64 samples as the current modulator is.
  Cost ~ 1024 bins * 384 samples = 3.9e5 complex MAC ~ 2.4e6 flop per channel
  per hop versus ~7.2e6 for 64 IFFT(2048); break-even near 20 live regions.
  Skip bins below the floor (sparse spectra are cheaper still).
  Alternative 8b (Laroche-Dolson): translate regions in the frequency domain
  by integer bins (+ interpolation for the fraction) and run ONE IFFT(2048)
  per channel. Cost ~1.1e5 flop. Loses sample-accurate pitch control (shift
  constant within a frame, so automation becomes hop-rate with phase
  continuity) and adds interpolation AM: Laroche-Dolson measured -21 dB worst-
  case sidebands at 50% overlap and -51 dB at 75% for linear interpolation
  (paper text, Fig. 1); our 4x synthesis overlap is comparable to 75%.
  ```
- Evidence: Laroche-Dolson 1999 numbers above (measured on a Hann window; our
  asymmetric window differs). 8a's cost is arithmetic, not a benchmark.
- Latency: 0. CPU: 8a ~3x cheaper than the 64-region worst case and flat in
  region count; 8b ~60x cheaper but changes behaviour.
- Risks: 8a recurrence drift (mitigated by re-anchoring); SIMD layout work;
  8b breaks the per-sample control contract in live-engine.md.
- Test: 8a must be a null test: tone and dyad fixtures from FINDINGS, shift
  $\pm 7$, $\max|y_{8a} - y_{\mathrm{current}}| < 10^{-6}$ (double) or < 1e-4 (float). 8b: pure
  1 kHz tone at +7 (fractional-bin shift), sideband level via STFT(8192) at
  $\pm 500$ Hz (hop rate) multiples; pass < -50 dBc. WSL wall-time ratio is a
  diagnostic only, not a callback bound.

### 9. Stereo: per-channel frequency refinement when channels disagree

- Defect: shared $\omega_p$ is right only if both channels carry the same partial.
  With independent material (double-tracked guitars, wide stereo synth), a
  partial at $\omega' \neq \omega_p$ in channel R lands at $\omega' + (r-1)\omega_p$,
  error $(r-1)(\omega' - \omega_p)$: small for detunes under a bin, so this is a
  low-priority refinement. The current design already preserves inter-channel
  phase (same rotation on both channels) and uses the cross-product sum, which
  does not cancel anti-phase channels.
- Mechanism: compute per-channel phase-increment estimates $w_L, w_R$ for stable
  regions; if $|w_L - w_R| > 0.25$ bin and both channel magnitudes $> 0.25 \cdot \max$,
  use per-channel $\delta_p$ and $\theta_p$ for that region (the IFFTs are already
  per channel). Otherwise keep the shared estimate.
- Evidence: Signalsmith Stretch predicts phase from the loudest channel and
  copies inter-channel phase differences (design note, claim); Rubber Band
  channel-locks only when both channels map to the same previous peak
  (source). Neither measures the independent-material case.
- Latency: 0. CPU: negligible.
- Risks: breaks exact inter-channel phase preservation for that region (that is
  the point); mono-compatibility of such regions must be checked.
- Test: 6 s stereo: L = 1000 Hz, R = 1010 Hz (same region), equal levels,
  shift +7: per-channel peak cents error < 2. Plus $L = -R$ 300 Hz: $|L+R|$ output
  < -60 dB re L (anti-phase preserved).

### 10. Tonality limit (option, off by default)

- What: above a corner frequency $f_c$, use translation ($\delta = (r-1) \cdot 2\pi f_c$)
  instead of scaling; keeps high partials' spacing and reduces upper-band
  remapping artifacts at the cost of inharmonic high partials.
- Evidence: Signalsmith Stretch design note: $\text{corner} = \text{limit} \cdot \sqrt{F}$; benefits
  supported by audio examples only (vendor/author claim, no measurement).
  papers.md 5 already says it must be a named option.
- Latency 0, CPU negligible. Risk: not a transposition above $f_c$; must never be
  on in a tuning-accuracy test.
- Test: harmonic 1 kHz sawtooth, +7; with limit 8 kHz, partials below 8 kHz
  within 1 cent of $r \cdot f$, partials above within 1 cent of $f + (r-1) \cdot 8$ kHz.

## What NOT to do (negative evidence)

- Serial STN decomposition then per-component shifting: Polak-Erkut 2025 is
  166 ms and was rated below its own Signalsmith component by 8 listeners
  (paper, measured); the public prototype is ~103 ms (open-source.md). D05.
- Universal transient bypass / dry-attack mix: original-pitch energy in the
  output (two pitches) for pitched picks; a sample-aligned dry path still combs
  (architecture.md D; open-source.md STN notes). Reset per region only (item 6).
- Global phase reset at onsets or periodic global resets: AM on polyphony
  (Kraft et al. 2012, measured); Stretch's randomised vertical scaling is
  described by its author as "a juddery smudge" (design note).
- "Phase Vocoder Done Right" as a drop-in: its preferred centered time
  difference needs frame n+1 (one hop of lookahead); the backward variant is
  permitted but unevaluated; it still stretches transients and its listening
  test (6 subjects, time-stretch alpha 1.5/2 only) says nothing about pitch
  shifting at 10 ms (ar5iv text). Its heap integration is a useful idea for
  item 3 only if measured here.
- Raising N (or the zoom FFT) to resolve E2/F2 or B0/C1 by magnitude alone:
  4.9 Hz needs > 200 ms, 1.8 Hz > 0.5 s of stationary history; use it as an
  estimator with confidence (item 7), never as the output path.
- Time-stretch + resampler pipelines (Rubber Band live API: >= 50 ms
  documented; ratio-dependent resampler delay) and Ocean-style integer-bin
  remapping (measured detuning/AM, D04).
- Envelope time-rescaling of unresolved regions (compress $|z_p[n]|$ by $r$): each
  frame would re-anchor the envelope, successive frames disagree by $(r-1)H$ per
  hop, and the OLA does not scale the beat. Rejected by construction.
- Randomised residual/noise phases (architecture.md B): smears picks and
  stereo; keep residual bins on the same continuous transport.
- Formant preservation on by default for guitar (architecture.md E).
- PESQ or raw waveform SNR as the quality score (architecture.md gates).

## Sources

Repository (read once today): `research/architecture.md`, `research/papers.md`,
`research/open-source.md`, `research/forensics/forensic-findings.md`,
`research/DECISIONS.txt`, `experiments/transport/FINDINGS.md`,
`docs/live-engine.md`.

Web (accessed 2026-10-10):
- Laroche & Dolson 1999, full text via pdftotext:
  https://www.ee.columbia.edu/~dpwe/papers/LaroD99-pvoc.pdf
- Průša & Holighaus, Phase Vocoder Done Right: https://ar5iv.labs.arxiv.org/html/2202.07382
- Luff 2023, Signalsmith Stretch design: https://signalsmith-audio.co.uk/writing/2023/stretch-design/
- Signalsmith Stretch tags (1.0.0 2024-12 to 1.4.0 2026-09, no transient notes):
  https://github.com/Signalsmith-Audio/signalsmith-stretch/tags
- Rubber Band R3 (GPL; read, not reused): Guide.h, PhaseAdvance.h, BinSegmenter.h at
  https://github.com/breakfastquay/rubberband/tree/default/src/finer
- Röbel 2003 transient processing (abstract): https://hal.archives-ouvertes.fr/hal-01161124
- Dixon 2006 onset detection revisited (search summary): https://dafx.de/paper-archive/details/_kscRgr98aSFW4l-j1YJuA
- Ornamentation false positives 2024 (abstract): https://arxiv.org/html/2408.13734v1
- Das, Abel, Smith DAFx-18 fast MUSIC: https://ccrma.stanford.edu/~orchi/Documents/DAFx18_fast_music.pdf
- Laroche 1994 matrix pencil piano beats (abstract): https://auditory.org/asamtgs/asa94mit/4aMU/4aMU4.html
- Betser et al. EUSIPCO 2006 (not re-read): https://new.eurasip.org/Proceedings/Eusipco/Eusipco2006/papers/1568981578.pdf
- NSGT phase vocoder (abstract only; offline, no causality claim): https://arxiv.org/abs/1612.05156
- PARSHL peak tracking: https://ccrma.stanford.edu/~jos/parshl/parshl.pdf

Searches for 2023-2026 low-latency polyphonic guitar pitch-shifting papers
returned nothing beyond Polak-Erkut 2025; neural vocoder results were off-topic.
