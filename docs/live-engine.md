# Linked stereo engine with live pitch control

`LiveEngine` is a linked-stereo pitch shifter whose target can change on any
input sample. It is a separate class from the mono, fixed-ratio `Engine` and
shares only the `Status` enum with it. The public interface is
[`LiveEngine.hpp`](../include/pitchwing/LiveEngine.hpp); the implementation is
[`LiveEngine.cpp`](../src/LiveEngine.cpp); the contract tests are
[`live_engine_tests.cpp`](../tests/live_engine_tests.cpp). Construction uses
C++17 RAII and the bundled MIT Signalsmith FFT; no other dependency exists.

The first section is the contract a consumer may rely on. The later sections
describe the implementation and cite the code lines and result files behind
each number. Measured results and how to rerun them are in
[live validation](live-validation.md).

## Consumer contract

`LiveConfig` accepts finite sample rates from 8000 through 192000 Hz and finite
pitch targets from -49 through +49 semitones, including fractional values
(`LiveEngine.cpp:36-48`). The range defines accepted controls, not musical
quality across it. Construction validates the configuration before allocating
and may throw `std::invalid_argument` or an allocation exception. Instances are
movable and noncopyable; move, destroy, and construct outside the audio
callback.

The caller serializes all access to an instance, including the pitch setter;
the class holds no locks or atomics. Pass parameter events on the processing
thread and split a block at their sample offsets when needed. The setter
changes the raw target for the next accepted input sample, during an active
stream, without resetting audio history and without a hidden ramp. Setter
calls with no input between them have no duration; only the last target
applies.

| Operation | Contract |
|---|---|
| `process(left, right, outLeft, outRight, frames)` | Planar float or double stereo; exactly `frames` samples are returned. Arbitrary block lengths, exact in-place buffers, crossed exact in-place buffers, and identical mono input pointers are supported. |
| Buffer overlap | Output channels must be disjoint. Every other pair must be disjoint or exactly equal; partial overlap returns `InvalidBuffer` (`LiveEngine.cpp:98-119`). Arrays must contain `frames` accessible elements. |
| Zero frames | Returns `Ok` without reading pointers or advancing state while open. A closed stream returns `StreamClosed` first (`LiveEngine.cpp:703-708`). |
| Sample validation | The whole block must be finite with absolute values at most $10^{30}$ in both precisions. A failure returns `InvalidSample` before any output or state change (`LiveEngine.cpp:714-722`). |
| Invalid buffers | Return `InvalidBuffer` before reading samples or changing state. Address-range checks cannot prove that a nonnull pointer owns accessible storage. |
| `setPitchSemitones` | Finite values in $[-49, 49]$ return `Ok` while open; other values return `InvalidPitch`. After closure a changed valid value returns `StreamClosed`; an identical value still returns `Ok` (`LiveEngine.cpp:1292-1307`). |
| `reset()` | Clears histories, pending work, and output without allocating; keeps the sample rate and current target; reopens a closed stream. It discards sound and is not a bypass switch. |
| First `flush` | Offline terminal drain into two disjoint arrays with capacity at least `tailSamples()`. Feeds that many zero samples at the last target, writes the full tail, and closes the stream, also when nothing was processed. |
| Failed `flush` | Writes `written = 0` and leaves output and stream state untouched. Capacity is checked first and returns `BufferTooSmall`; bad addresses then return `InvalidBuffer` (`LiveEngine.cpp:737-748`). |
| Repeated `flush` | Returns `Ok` with `written = 0`; null buffers and zero capacity are accepted. |
| Moved-from instance | Status operations return `NotPrepared`, `flush` sets `written = 0`, size queries return 0, and `config()` returns default settings. |

`Status` is shared with the static engine (`Engine.hpp:20-29`). `LiveEngine`
returns `Ok`, `InvalidBuffer`, `InvalidSample`, `InvalidPitch`,
`StreamClosed`, `BufferTooSmall`, and `NotPrepared`; it never returns
`PitchLocked`.

Every allocation, container size, FFT plan, and window is prepared in the
constructor. `process`, the setter, `reset`, and `flush` allocate nothing,
take no lock, do no I/O, plan no transform, and grow no container; the
allocation checks are in `testNoRealtimeAllocations`
(`live_engine_tests.cpp:661`). Input validation costs linear time in the block
size. The shared $10^{30}$ input bound keeps delayed history representable
when a caller switches from double input to float processing or flushing;
`testPrecisionChangesAtCommonBound` (`live_engine_tests.cpp:506`) checks
that case. There is no limiter, gain compensation, or normalization, and no
promise that ordinary audio stays below full scale.

## Rate-dependent geometry and scheduling

For sample rate $f_s$ the constructor chooses (`LiveEngine.cpp:144-149`)

$$
H = \lfloor 0.002\, f_s \rfloor,\qquad
L = 4H,\qquad
N = \operatorname{fastSizeAbove}\!\left(\left\lceil f_s \cdot \tfrac{2048}{48000} \right\rceil\right),
$$

$$
D = L - 1 + H,\qquad
\text{tail} = N + D + H .
$$

The geometry queries return these prepared sizes, which stay fixed for the
instance; a sample-rate change needs a new instance. $D$ is 439 samples at
44.1 kHz, 479 at 48 kHz, and 959 at 96 kHz, below 10 ms at every accepted
rate. The extra hop is scheduling delay and is included in the reported
latency; no adapter, FIFO, or resampler sits outside that count. The reported
delay says nothing about pitch settling or host buffering.

A frame is analysed after the input samples $t = 0, H, 2H, \ldots$ and writes
one length-$L$ contribution starting at $t + H$ into an output ring of length
$L + H$. Its spectra, entries, control snapshot, and destination are fixed
until it finishes. The frame's work is $T = R + 8$ tasks: one spectral
accumulation per entry ($R$ entries) and one inverse transform per Taylor
term and channel (see "Shared synthesis"). During hop phase $p$ the scheduler
completes $\lfloor (p+1)\,T / H \rfloor$ tasks (`LiveEngine.cpp:788-797`), so
every task finishes at $t + H - 1$, before the first sample of that frame is
emitted. Input history advances independently. The engine holds at most 64
regions and 160 entries (`maxRegions`, `maxEntries`, `LiveEngine.cpp:19-26`);
with $H \ge 16$ the scheduler may run several tasks per input sample at low
rates. FFT analysis and peak selection still run as a burst at the frame
boundary, so this spreads one source of bursts, not all of them, and proves
no deadline on WSL or on the consumer's Windows machine.

## Linked stereo analysis

Peak picking uses the shared magnitude
$\sqrt{|X_L[k]|^2 + |X_R[k]|^2}$ (`LiveEngine.cpp:816`): local maxima at
least $10^{-4}$ of the largest bin, skirt peaks dropped, the 64 strongest kept
(`LiveEngine.cpp:830-851`). A flat spectrum (largest minus smallest at most
$10^{-12}$ of the largest) yields one peak at bin 1. A skirt peak is a local
maximum below twice the window skirt predicted from the nearest larger peak on
each side; such peaks sliced a partial's own skirt and re-emitted it with
another translation (hop-rate combs near -52 dB, `LiveEngine.cpp:316-323`).
Both channels keep their own complex spectra.

### Frequency fit

The region frequency is a least-squares fit of the three peak bins of both
channels to

$$
X[k] = a\,A(\omega_k - \omega) + \bar{a}\,A(\omega_k + \omega),
$$

where $A$ is the tabulated analysis-window spectrum at $1/64$ bin over
$\pm 48$ bins (`lobeOversample`, `lobeRange`, `LiveEngine.cpp:20-21`) and $a$
is solved per channel. The image term matters below bin 4: the log-parabola
and cross-frame phase-difference estimators wobbled 150 to 680 cents
peak-to-peak frame to frame and carried a -16 cent bias at E2, while the
lobe fit stays within 2 cents
([estimator probe](results/2026-10-10-estimator-probe.txt)). The fit is a
single-sinusoid model and does nothing for an unresolved dyad (E2 plus G#2 in
the same probe).

The fit runs in two passes (`fitPeak`, `fitPeaks`, `LiveEngine.cpp:401-480`).
Pass 1: a 13-point grid over the peak bin $\pm 0.6$ (from 0 for a peak at
bin 1, so a DC lobe fits as an untranslated $\omega = 0$ tone), then four
parabolic steps of spacing 0.1 bin shrinking fourfold each step. Pass 2, for a
peak with a credible neighbour (3-bin residual at most 30 %, centre at least
1 bin) within 24 bins: the neighbours' pass-1 lobes are subtracted from the
peak's three bins and four parabolic steps of spacing 0.15 bin restart from
the pass-1 centre. Subtracting non-credible fits (DC-lobe sidelobes) broke pure
DC at +7. Near $\omega = 0$ only $\operatorname{Re}(a)$ is determined; when
the $2 \times 2$ determinant is at most $10^{-12}$ of its diagonal product, or
the fitted amplitude exceeds four times the data, the fit falls back to that
real-only solution (`LiveEngine.cpp:296-307`).

### Lobe ownership and the DC term

A partial whose pass-2 fit leaves at most 2 % residual and whose centre is at
least 1 bin owns its fitted lobe over $\pm 24$ bins (`lobeSpan`,
`lobeQuality`, `LiveEngine.cpp:28-29`), window skirts included, transported
with its own $\omega$; its image term $\bar{a}\,A(k + \omega)$ is placed
conjugated on the mirrored bins $N - k$, so the modulator moves it by
$-\delta$ with its partial. Every bin-owning entry renders $X - \text{model}$
in its bins, where the model is the sum of all transported lobes
(`LiveEngine.cpp:950-968`); the sum over entries is still exactly $X$. Without
lobe ownership a partial's skirt outside its own region moved with the
neighbour's translation (-19 dB lines at $f \pm (f_2 - f_1)(r - 1)$ for a
3.5-bin pair) and its image term moved by $+\delta$ (low-tone gain -0.7 to
-0.9 dB), see [fixture results](quality/2026-10-10-fixture-results.md) and
[lobe fixtures](results/2026-10-10-fixtures-step6-lobes.json).

Bin 0 belongs to the lowest entry. The bin-0 remainder
$X[0] - \text{model}[0]$, divided by the window sum, is the true DC and is
rendered untranslated with the exact partition-of-unity window
$\text{analysis} \cdot \text{synthesis} = (1 - \cos)/4$ (`dcWindow`,
`LiveEngine.cpp:234`, `:1049`). A lobe-less lowest region (a DC lobe) keeps
its fitted bin-0 share $2a\,A(-\omega)$ instead (`LiveEngine.cpp:970-977`);
rendering a lobe there made pure DC at +7 lose 25 %. Before this term, 0.05 DC
with 220 Hz at +7 showed hop lines at -61 dBFS with DC gain 0.725, and the
unshifted 41 Hz ghost of E1 sat at -18 dB; with it the hop lines are at
-148 dBFS, the DC gain 1.00, and the ghost -75 dB
([DC fixtures](results/2026-10-10-fixtures-step3.json)). Destinations below
zero are folded to $|\text{destination}|$ through the real part, the
conjugate reflection of a real signal's lobe (`LiveEngine.cpp:1088-1091`);
the low-tone gain loss at -7 is -0.23 dB at E2.

### Multi-resolution split of unresolved low partials

Unresolved low partials are split, not re-analysed
([multires gauntlet](quality/2026-10-10-multires-gauntlet.md)). A second,
past-heavy analysis spanning $4N$ samples supplies frequencies only and runs
whenever the frame is not exact unity (`LiveEngine.cpp:1021-1030`). It works
on a decimated copy of the input: $M$ is the largest divisor of $4N$ that
keeps $f_s / M \ge 6$ kHz (8 at 48 kHz, `chooseDecimation`,
`LiveEngine.cpp:60-66`), the anti-alias FIR is a Kaiser design near 90 dB with
its transition from 750 Hz to $f_s/M - 750$ Hz, since only aliases below the
700 Hz search limit matter (`LiveEngine.cpp:196-215`). The long FFT has
$4N/M$ points and the bin spacing of a full $4N$ frame; its window has the
same construction with a fall of $L/(2M)$ samples and its own lobe table. The
long frame is never transported, so latency, bloom, and the short frame's
time resolution are unchanged.

Long peaks below 700 Hz (`longLimitHz`), above $10^{-4}$ of the short
maximum scaled by the window sums, with skirt peaks dropped, are counted per
short region (`findLongPeaks`, `LiveEngine.cpp:571-589`). Neighbouring short
regions whose long peaks are less than 3 short bins apart are merged first,
because an unresolved pair shows one or two short peaks depending on the beat
phase (`LiveEngine.cpp:909-918`). A group is split when it holds 2 to 32 long
peaks (`maxSplit`) within 2.5 short bins of its short peaks and at least
-40 dB of the strongest of them; weaker long peaks are long-window skirt
ripple (`LiveEngine.cpp:596-625`). A group with more than 32 candidates is
not split. Components closer than 0.35 short bin (`minSplitBins`) make the
solve ill-conditioned and are rejected. The long-frame frequencies use a
single fit per component plus two local refits on bins cleaned of the other
components' lobes (`LiveEngine.cpp:630-660`); single-lobe fits are biased
about 14 cents peak-to-peak by a neighbour, and a joint coordinate descent
cost $O(m^3)$ per sweep. The short frame then fits only the complex
amplitudes of all component lobes over the group's bins (`jointFit`,
Cholesky with the ridge of "Amplitude ridge").

Each component is one entry with its fitted lobe, its own $\omega$, and an
inherited rotation. It also owns the group's bins nearest to it (midpoints
between component centres, `LiveEngine.cpp:936-946`) and renders their
residual $X - \text{model}$ with its own $\omega$ when that residual exceeds
$10^{-3}$ (-30 dB) of the cell's energy (`residualFloor`,
`LiveEngine.cpp:1116-1129`); below the floor the residual is dropped, which
is a documented shortcut, not exact reconstruction. For a split lowest
group the components carry $2a\,A(-\omega)$ at bin 0 and the DC term is
$X[0]$ minus all component shares. Measured on E2 plus G#2 at $\pm 7$: lines
within 0.1 % of the required spacing (50 % and -33 % before the split), outer
beat sidebands at -86 and -90 dB (-26 and -17 dB before), output residual
against an ideal two-tone -51 dB
([split fixtures](results/2026-10-10-fixtures-step5-split.json), [cell
fixtures](results/2026-10-10-fixtures-step10-cells.json)).

### Amplitude ridge

On real guitar attacks a group holds 21 to 32 components 0.35 to 0.5 short
bin apart across 0 to 1.5 kHz. The plain short-frame solve then returned
cancelling amplitudes up to 7000 times the group's largest bin, and the
components' different shifts undid the cancellation (peaks 359 times full
scale). `jointFit` adds 1 % of the mean Gram diagonal to the diagonal
(`LiveEngine.cpp:518-529`), which bounds $|a|\,|A(0)|$ to about five times
the data; the shrunk remainder stays in the residual cells. The real-material
gate [`real_material_gate.py`](../scripts/real_material_gate.py) checks peak
and attack-envelope ratios on the user's guitar excerpts; results are in
[the ridge gate run](results/2026-10-10-real-gate-step11.json).

### Shared synthesis

Every entry adds into four shared spectra per channel instead of owning an
inverse transform. The frame uses the mean control $c$ (see "Pitch control
integration"), and each entry's translation $\delta = \omega c$ is split into
the nearest whole-bin shift $s = \operatorname{round}(\delta N / 2\pi)$, an
exact circular shift of its bins, and a remainder

$$
\varepsilon = \delta - \frac{2\pi s}{N},\qquad |\varepsilon| \le \frac{\pi}{N}.
$$

The remainder $e^{j\varepsilon (m - m_c)}$ around the output centre $m_c$ is
expanded in four Taylor terms (`taylorTerms`, `LiveEngine.cpp:30`,
`:1066-1110`); $|\varepsilon x| \le 0.27$ over the synthesis length, so the
truncation error is at most $0.27^4/4!$, about -73 dB. A frame therefore costs
8 inverse transforms (`renderTerm`, `LiveEngine.cpp:1164-1183`), and
components render through their $\pm 24$-bin lobe like plain entries. The
intra-frame control shape is linear: a sub-frame step is spread over the frame
instead of placed at its sample. Real guitar gives about 62 entries per 2 ms
hop; with one transform pair per entry the engine used 80 to 95 % of one core
and ShiftKey crackled at any shift. The 6.5 s guitar excerpt renders in 1.80 s
of CPU against 6.2 s before sharing
([timing](results/2026-10-10-timing-step12.txt)), and the real-material gate
reports 0.32 to 0.33 CPU seconds per audio second against 1.06 to 1.08
([gate run](results/2026-10-10-real-gate-step12.json)).

Region ancestry, transport rotation, and modulation are shared between the
channels; the inverse transforms stay separate per channel, so signed
proportional channel relations survive without mixing samples. A silent
channel stays silent. Independent material in both channels can still compete
for shared peaks, so linked analysis claims no perfect imaging on every stereo
recording.

## Pitch control integration

For every accepted input sample the engine stores
$u[t] = 2^{\,\text{semitones}[t]/12} - 1$ in a length-$L$ control history and
adds it to the running hop area (`LiveEngine.cpp:780-784`). The pre-stream
history is zero. At frame time $t$ the frame snapshots that history. The
rotation of a tracked region is inherited from the previous frame's region
nearest in frequency (`LiveEngine.cpp:852-883`):

$$
\theta_t = \operatorname{principal}\!\left(\theta_{t-H} + \tfrac{1}{2}\,(\omega_{t-H} + \omega_t) \sum_{k = t-H+1}^{t} u[k]\right).
$$

The first frame has no ancestor and starts at zero rotation. The frame's
translation uses the mean of the $L - 1$ newest controls in the support
(`frameRatioMinusOne`, `LiveEngine.cpp:1004-1012`):

$$
c = \frac{1}{L-1} \sum_{q=1}^{L-1} u_q ,
$$

with $u_0$ the oldest control in the support. Commands shorter than one hop
still contribute phase area through the hop sum and translation through
$c$, even when neither surrounding frame-end target shows them. A scheduled
frame keeps its snapshot, so a later setter call cannot change a pending
contribution. For constant controls this is the linear phase function of the
static design; with changing targets, linked stereo, and the scheduler it is a
new behaviour, and no literal parity with the mono engine is claimed.

### Unity reacquisition

When all $L$ saved controls are exactly zero and every inherited rotation is
exactly zero, the frame adds the windowed recent time-domain samples directly
and needs no inverse transform (`LiveEngine.cpp:1038-1049`). After a nonunity
run the rotations are not reset: a reset mixed rotated and unrotated copies
of each partial in the overlap ring and measured dips to -15 dB per partial
([fixture results](quality/2026-10-10-fixture-results.md), section 1).
Instead, unity frames keep rendering entries with zero translation while each
rotation with a per-hop advance below $10^{-3}$ rad is slewed towards zero by
at most

$$
\max\!\left(\omega,\ \frac{2\pi \cdot 100\ \text{Hz}}{f_s}\right) \cdot H \cdot 0.006
$$

per hop (`LiveEngine.cpp:871-881`), a glide of at most 10 cents (33 cents
below 100 Hz), so the worst case settles within about 420 hops (an estimate
from the slew rate). Sustained unity then becomes exact delayed reconstruction
without clearing audio history. On the 220 Hz plus 1 kHz fixture the
per-partial dips are within 0.3 dB and the 1 ms total-RMS dip is -1.9 dB
([unity fixture](results/2026-10-10-fixtures-step12-shared.json),
`scripts/quality_fixtures.py --only unity`).

## Preserved limitations

The implementation keeps rigid translation within an entry, ungated
nearest-frequency ancestry, Nyquist omission outside exact unity, and the
two-bin high-frequency taper (`LiveEngine.cpp:1081-1092`). It does not solve
unresolved low-dyad spacing below the split's limits, low-note settling, or
spectral collisions; a DC offset at a nonzero shift keeps a small ripple
(0.2 DC: 0.005 RMS at -7, 0.019 at +7). The alias guard uses the frame-end
ratio only, so a short high-ratio excursion inside the saved support can
exceed the guard's assumed destination range; there is no proof of dynamic
alias suppression. Extreme targets are accepted without a promise of useful
bandwidth or timbre. Compilation, warnings, sanitizer runs, contract tests,
timing, and listening are recorded in [live validation](live-validation.md);
the historical listening renders of the static engine are unchanged.
