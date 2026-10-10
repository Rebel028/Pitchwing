# Pitchwing development record

Record development work, decisions, findings, validation, and next steps here.
Link larger task-specific artifacts instead of duplicating them. Earlier
research history remains in [research/DECISIONS.txt](research/DECISIONS.txt) and
[research/Pitch_Research_Handoff.txt](research/Pitch_Research_Handoff.txt).

## 2026-10-08 — Project scope and working requirements

Request: make low-pitched guitars a primary requirement alongside latency;
consider bass; document all development and findings; use subagents; minimize
drive I/O; record WSL and ask before installing missing tools or dependencies.

Changes: created `PROJECT.md` as the current scope, `AGENTS.md` as instructions
for future agents, and this durable development record.

Decisions and rationale:

- Low-register guitar quality is co-primary with latency, so early evaluation
  must include low polyphonic cases and attack/settling behavior.
- Bass remains a likely extension. The user's tentative wording does not fix
  a guaranteed bass range or a lowest supported tuning.
- All project-relevant development knowledge, including subagent findings and
  failed experiments, must be saved in repository artifacts before handoff.
- Subagents should perform bounded independent work with coordinated I/O and
  file ownership. Delegation must not multiply expensive disk activity.
- WSL and the `/mnt/d` checkout require deliberate I/O planning. Prefer `/tmp`
  for disposable work and preserve compact results in the repository.
- Installation approval applies to both system and project-local dependencies,
  including implicit installation by a command.
- Keep the imported research checkpoint intact and record evolving scope at the
  project root, preserving the checkpoint's existing measurements and hashes.

Findings: the existing research already identifies low-note tuning failures and
unresolved close-tone behavior as risks. The new scope elevates low-register
guitar performance to an explicit primary requirement. No existing root project
scope or agent instructions were present.

Validation: checked the requirements mapping against all five user requests.
An independent read-only subagent review confirmed the scope distinctions and
working rules, including tentative bass coverage, an unspecified minimum tuning,
and the distinction between WSL checks and target-native validation. Its findings
are incorporated in the scope and agent instructions. No DSP experiments, builds,
or installations were run for this documentation change.

Next: apply these requirements to subsequent development. Establish the lowest
guitar tunings, representative DI corpus, and desired bass coverage during DSP
evaluation; no arbitrary range guarantee has been added.

## 2026-10-08 — Engine-only deliverable

Request: develop only the pitch-shifting engine, not a VST plug-in.

Changes: updated `PROJECT.md` to define a reusable engine as the deliverable and
exclude VST plug-in development, packaging, and integration. Added the matching
working rule to `AGENTS.md`.

Decision and rationale: the user's clarification supersedes the older VST3
delivery plans in `research/`. Preserve that checkpoint unchanged as historical
evidence. DSP validation still precedes native C++ implementation. Stereo,
parameter changes, variable processing blocks, sample rates, and callback
deadlines remain relevant to the engine; they do not require a plug-in wrapper.
Competitor plug-in references remain valid quality references.

Validation and limitations: reviewed the three edited documents for consistent
engine-only scope and removal of active VST3 delivery plans. This documentation
change required no DSP runs, builds, tests, installations, or research edits.

Next: discuss and implement the DSP validation slice within this engine-only
scope. The engine API and packaging format remain implementation decisions.

Implementation discussion in progress: the proposed first slice is a streaming
and offline evaluation harness plus minimal coherent spectral-region transport,
using the existing reconstruction scaffold. Compare with a symmetric baseline
at matched delay and test low tones, close dyads, and chord attacks before the
native engine port. These are proposals, not completed implementation or proof
of quality. The existing Ocean and WOLA material provides the starting evidence.

The user selected guitar tunings below F#1 for the first evaluation set.
`PROJECT.md` now records that requirement. The exact minimum supported tuning
is still open; bass remains exploratory. Use E1 and B0 as initial engineering
stress cases, not as an agreed or validated supported floor.

Workflow note: the discuss-phase skill was consulted, but this repository has
no GSD phase roadmap. Continue the implementation discussion against the existing
project scope and this log; no GSD phase workflow was run.

Implementation starting: build the minimal streaming research prototype and
an in-memory evaluator outside the preserved `research/` checkpoint. Compare
asymmetric and symmetric windows at matched scheduled delay. Use the existing
Python/NumPy environment if available, standard-library tests, and no automatic
installation. Save compact metrics rather than large audio corpora; no native
performance or production-quality claim follows from this initial experiment.

Environment finding: system Python is 3.8.10, with neither NumPy nor SciPy.
The user explicitly approved an isolated NumPy installation. Created
`/tmp/pitchwing-env` with `venv --without-pip` (system `ensurepip` is absent),
then used the existing pip to install the compatible binary NumPy 1.24.4 wheel
into that environment; its download cache is also under `/tmp`. No system
packages or SciPy were installed. The temporary environment is disposable and
must be recreated with user approval if missing in a later session.

Delegation: `transport_engine` owns the experimental processing module and its
design notes; `transport_evaluation` owns synthetic measurements and metric
definitions; the main agent owns interface tests, integration, and this record.
The codebase-design skill informs a small processing interface with a shared
test surface. Experimental code goes in `experiments/transport/`.

Audio evaluation discussion: real dry DI clips are useful for numeric artifact
analysis and controlled renders; those metrics cannot establish natural sound
or playing feel. Requested examples are low sustained notes, bends/vibrato,
palm mutes, attacks, close intervals, dense chords, and ringing changes, with
tuning/sample-rate metadata and silence around the performance. Preserve the
original level and avoid prior gate/compression/distortion/normalization. Human
listening and live playing remain required; no real DI clips have been supplied
in this session yet.

Initial implementation checks: the new streaming module passed all eight
interface tests under Python 3.8.10 / NumPy 1.24.4 (7.85 s wall time, not an audio
deadline measurement). Coverage includes 96 impulse phases for each window,
delayed identity on noise/DC/B0 content, shifted block-partition independence,
reset and terminal-drain behavior, invalid-input state preservation, and a
coarse resolved-tone octave sign/phase check. Mono static-ratio processing only;
low-note quality evaluation is separate and still in progress.

Completed first experiment: see
[the module guide](experiments/transport/README.md),
[transport design](experiments/transport/ENGINE_NOTES.md),
[metric definitions](experiments/transport/METRICS.md), and
[findings](experiments/transport/FINDINGS.md). The engine uses coherent analytic
region modulation with explicit phase conventions; both window configurations
have 383-sample scheduled delay. This is a research implementation, not the
native product engine.

Review and fixes: an independent subagent found public configuration could be
mutated while internal windows remained cached. Configuration properties are
now read-only, with an interface test. Review also identified that preserving
DFT bin zero does not preserve a constant input waveform under nonzero shifts.
A focused probe confirmed DC gain/modulation failures; DC cases are now part
of the evaluator and the misleading comment was corrected. The transport
algorithm itself was not tuned after seeing the first quality results.

Final verification for this slice: nine interface tests passed in 8.02 seconds;
five analytic metric tests passed in 0.42 seconds. Strengthened checks cover
invalid blocks during active processing and resolved-tone gain. Earlier metric
development used an unjustified condition-number assertion below 10 for close
chord harmonics, which failed (approximately 21–49); retained that finding and
documented the finite-window conditioning limit. The final tests check numerical
stability and accurate reconstruction without pretending to resolve those
individual harmonics.

The full evaluation ran once after interface fixes: 82 cases in 25.67 seconds,
all in memory. Saved approximately 101 kB of JSON, with engine/evaluator hashes,
to [the initial result](experiments/transport/results/2026-10-08-initial.json).
Scratch output used `/tmp`; no WAV corpus, native build, or old research output
was written. The shell sandbox rejected creating the result directory on the
mounted drive, so the normal patch tool persisted the completed small result.

Findings and decision: asymmetric analysis improves isolated B0/E1 tuning
over the matched short baseline, but close-dyad spacing remains at its original
value instead of scaling. The original research's critical counterexample is
reproduced. Chord-fit and DC results also fail. Reject this rigid regional
translation candidate for production; retain the tested scheduler, harness,
and failure data. Next work is a different treatment of unresolved mixtures,
followed by the same low-note/chord tests. Do not begin a C++ port of this failed
candidate. Human listening and real DI evaluation remain outstanding.

Final artifact review: the independent reviewer checked FINDINGS.md against
the saved numerical rows and found the claims consistent and the candidate
rejection justified. Engine/evaluator hashes in the saved JSON match the current
source files. Result counts total 82. This rejects the tested rigid transport
method as sufficient; it does not reject every spectral-region architecture.

## 2026-10-08 — User recording intake

The user supplied WAVs in `stems/` (correcting an earlier `sam/` path) and
explicitly permits cutting them into excerpts. Preserve the original files.
Initial header-only inspection with already-installed ffprobe found eight
stereo PCM24 WAVs, all at 44.1 kHz: `01.wav`–`06.wav`, `tapping1.wav`, and
`tapping2.wav`. Durations range from 7.20 to 51.51 seconds. No installations
are needed; the approved temporary NumPy environment remains available.

Plan: one combined sequential read per source for a source hash, exact PCM
decoding, channel/level statistics, and candidate excerpt references. Do not
copy the corpus or regenerate large output sets. Use a few short excerpts for
diagnostic renders under `/tmp`; persist compact audit and render metadata in
the repository. Real recordings do not undo the synthetic rejection of the
current transport method or establish objective transposition ground truth.

Delegation: the evaluation worker owns the corpus auditor and its decoding/
selection tests; an independent reviewer checks the excerpt/listening protocol
without rereading audio; the main agent owns runs, excerpt rendering, and docs.
The user has been asked for tuning/lowest note, dry-DI versus processed status,
and optional numbered-clip labels. Those details are not yet established.

User tuning information: the first four or five recordings are G#1 standard
on a seven-string guitar; the last three are Drop F#1. Using filename/BWF time
order, record `01`–`04` as G#1 standard, `06`/`tapping1`/`tapping2` as inferred
Drop F#1 assignments, and leave `05` uncertain. Asked for confirmation of `05`
and whether any processing is present. These supplied tuning labels reach F#1;
they do not establish real-input coverage below F#1. Continue the lower
synthetic stress cases and do not infer an exact minimum played note from the
open-string tuning alone.

Excerpt protocol review: use original 44.1 kHz input, up to six audition seconds
plus 0.5 seconds of source preroll, and mono channel selection stated explicitly.
The fixed 2048/384/96 sample configuration gives 383 samples = 8.6848 ms at this
rate; its time constants differ from the earlier 48 kHz synthetic run. Render
static -2 and -7 semitones, preserve full delay/tail, and compare against a dry
reference delayed by the same 383 samples. Use float32 WAV output to retain
over-range samples without implicit clipping. Do not normalize, limit, fade,
or resample. Listen for timbre and artifacts; this is not a live latency test.
The main agent implemented `experiments/corpus/render_excerpt.py` for this
bounded workflow. Real polyphonic tuning/beat error needs an appropriate
reference and must not be inferred from a spectrum peak in these recordings.

User provenance update: the stems were rendered in REAPER; the user suspects
stereo conversion and some high-quality resampling. Originals are available at
`D:\Reaper\shiftkey test\Media`, read in WSL as
`/mnt/d/Reaper/shiftkey test/Media`. Header inspection found nine current
recordings at mono PCM24/44.1 kHz and one older (2025-06-08) recording at mono
PCM24/48 kHz. Header rates alone do not prove which render operations occurred.
The exact stem-to-original edit mapping, `05` tuning, and any FX processing are
still unconfirmed. Audit the originals in one additional sequential pass
(approximately 40 MB) to distinguish source endpoint hits from export behavior;
do not copy or rerender the original corpus.

Completed intake: eight stems total 177.333 seconds / 46,927,962 bytes, all
44.1 kHz PCM24 with sample-identical L/R. Seven contain exact PCM endpoints.
The original-source audit covers ten files / 40,010,442 bytes; seven current
originals also contain endpoint samples. This is not solely an export-created
condition, but endpoint hits do not diagnose the clipping/limiting mechanism.
Saved both audits and original header metadata under `experiments/corpus/results/`.
Original/export edit mappings remain unverified; no source audio was modified.

Validation: the delegated auditor passed ten synthetic tests for PCM sign/
endpoint decoding, headers, silence, stereo statistics, and excerpt selection.
The main agent ran each corpus audit once with no errors, using the same reads
for hashing and decoding. The auditor source hash matches the recorded version.
Only about 87 MB of source data was read in these two full passes; render reads
then seek directly to three short intervals instead of rereading the corpus.

Rendered six-second intervals: `02` at 1.8 s, `06` at 9.7 s, and `tapping1` at
9.0 s, each with 0.5 s preroll and source channel zero. Three variants per
interval (delay-matched dry, -2, -7) are at
`/tmp/pitchwing-listening-20261008/`. Nine mono float32 WAVs total 10,411,398
bytes. ffprobe confirms 44.1 kHz and 289,177 frames per file. Original-rate
unity checks have maximum errors 3.33e-16 to 4.44e-16 at 383 samples of delay;
all shifted outputs are finite and have no pre-encoding full-scale exceedances.

Review: the independent reviewer found the render cut/alignment/level protocol
consistent. It noted metrics describe float64 pre-encoding samples rather than
the stored float32 values. Added that distinction to the renderer, saved render
metadata, and [corpus guide](experiments/corpus/README.md). No audio rerender was
needed for this metadata clarification. Gains are not normalized: full-stream
RMS falls by approximately 0.59–1.36 dB in the six shifted renders. This is a
level observation, not a perceptual or polyphonic pitch-accuracy result.

Listening feedback: the user says existing test prototypes "sound pretty nice."
Asked which files/folder and shift settings were heard. Until clarified, retain
this as positive informal feedback without assigning it to Ocean, the new
transport engine, or this particular render set. Preserve liked versions as
listening baselines once identified. Synthetic failures and human preference
are complementary evidence; the current transport candidate is still not
validated for the engine's low-polyphony requirement.

Remaining information is recorded in the corpus guide: `05` tuning, dry/FX
status, original/export mapping, and the exact prototype behind the listening
feedback. Lower-than-F#1 real inputs and competitor reference renders remain
future evaluation needs. Nothing was installed during this intake task.

## 2026-10-08 — First native C++ engine

User decision: all current listening comparisons are good enough; `06/minus7`
is the preferred pick-attack example, with the caveat that this may depend on
the recording. The user explicitly requested implementing the engine using
`cpp-pro` now. Preserve the accepted sound and begin the native port while
retaining unresolved low-dyad/DC defects. This supersedes the earlier sequence
requiring those defects to be solved before any C++ work. Updated active scope,
agent instructions, and experiment/corpus status without changing old evidence.

Implementation uses the local cpp-pro, CMake, C++ testing, and sanitizer skills.
GCC 9.4 is available; use portable C++17 with a small RAII-owned implementation.
CMake is missing: asked permission to install it in the existing isolated
`/tmp/pitchwing-env`; installation remains pending. No new dependencies are
downloaded as part of configuring/building. The existing MIT-licensed
Signalsmith FFT header/license were copied into `third_party/`, with provenance.

Division of work: engine worker owns `include/pitchwing/Engine.hpp`,
`src/Engine.cpp`, and `docs/native-core.md`; test/build worker owns
`CMakeLists.txt` and `tests/engine_tests.cpp`; evaluation worker owns
`tools/pitchwing_render.cpp`, `scripts/compare_native.py`, and native validation
instructions. Parent owns integration, builds/runs, dependency provenance, and
scope/development records. All agents share the workspace and avoid duplicate
builds/corpus reads. Builds and raw comparison outputs belong under `/tmp`.

Initial API: mono float/double processing, arbitrary blocks, exact in-place
support, static pitch per stream, explicit reset and terminal drain. Constructor
prepares all storage/FFT plans; processing/reset/drain must allocate nothing.
The default 2048/384/96 schedule retains 383 samples of delay. Stereo and smooth
live pitch changes remain future work. Numerical parity, lifecycle/input tests,
sanitizers, and WSL timing will validate this port separately from sound quality.

Tool approval: the user approved isolated Linux CMake installation and reported
an existing Windows installation at `C:\Program Files\CMake\bin` (WSL path
`/mnt/c/Program Files/CMake/bin`). Installed CMake 3.31.10 into the already
approved `/tmp/pitchwing-env`, with its wheel cache under `/tmp`. Use this Linux
version for WSL GCC builds; Windows CMake availability alone does not establish
a Windows compiler/SDK or target-native validation. No system installation or
project-drive package cache was created.

First integration: CMake release and ASan/UBSan configurations build without
compiler warnings. Release CTest passes all nine contract groups (3.26 s),
including every hop phase for both windows and global-new allocation checks.
The first instrumented run also passes all nine groups, but exits unsuccessfully
because LeakSanitizer cannot inspect a process under the command sandbox's
ptrace mechanism. An unsandboxed attempt consumed several minutes without
completion and was terminated; this is retained as an environment limitation,
not a successful leak check. Retry memory-access/UB checks with leak scanning
disabled explicitly. No reported memory-access/UB finding was suppressed.

The first parity invocation failed before processing because its relative
`__file__` was mixed with an absolute repository path in provenance generation.
The evaluation worker corrected that path handling. The next run completed
all 21 comparisons: six unity cases agree within 2.8e-16, but all shifted cases
fail materially, including maximum sample error 0.813 for the preferred excerpt.
Saved the complete [initial failed run](docs/results/2026-10-08-native-parity-initial.json).
Do not loosen tolerance or claim sound preservation. Engine worker is checking
FFT-rounding sensitivity in initially flat spectra and phase inheritance before
any DSP change. Initial timing overlapped the unsandboxed sanitizer attempt and
is not a clean performance measurement. No original research output changed.

Diagnosis using the diagnosing-bugs workflow: thirty small synthetic probes
confirmed flat-spectrum startup ties, rather than a transport sign/index error.
For phased A4 at -1, changing only the first input sample to zero reduces
native/Python error from 0.06579 to about 2e-15; adding 96 leading zeros retains
the failure, while 1 or 97 removes it. A single effective sample on a hop
boundary gives a flat spectrum; FFT roundoff invents different local maxima,
which seed different persistent phase histories. An independent equation review
found no mechanical transport mismatch and noted peak-cap tie ordering as
another undefined case. [Probe evidence](docs/results/2026-10-08-startup-probes.json)
and the [native-core diagnosis](docs/native-core.md) retain the reproduction.

Fix: native code uses canonical bin 1 when interior magnitude spread is at most
1e-12 of the largest magnitude; this is a selection rule, not a relaxed output
comparison tolerance. A separate `experiments/transport/stable_reference.py`
implements that rule and deterministic ordering at the 64-peak cap. The accepted
original `engine.py` and its rendered audio remain unchanged. Native parity now
targets this explicit deterministic variant, with old-baseline differences
reported separately. New native listening is required; initial user acceptance
applies to the original Python examples, not automatically to the corrected port.

Performance review: the initial preferred-excerpt runs suggest substantial
per-hop work bursts even with average throughput above real time. The reviewer
identified repeated modulation sine/cosine evaluation as a bounded optimization
opportunity: use a complex recurrence re-anchored every 64 samples and avoid
taper cosine outside its transition. First establish parity for the selection
fix; then measure any optimization separately, without changing persistent
region/phase logic. The initial timings are contaminated and cannot prove a
speedup or deadline safety.

The deterministic variant now passes all 30 native/reference comparisons at
the unchanged 1e-10 tolerance: worst sample error 1.668e-13, preferred excerpt
1.481e-13. Saved the [pre-optimization stable run](docs/results/2026-10-08-native-parity-stable.json).
The preferred excerpt differs materially in waveform from the original Python
baseline (max 1.126, RMS 0.202); this reflects different inherited phases, not a
measured perceptual judgment. Keep both for listening. The selected raw mono
input was archived under `/tmp` to reuse in subsequent runs without rereading
the stem. Clean WSL timing still shows per-hop bursts exceeding short callback
budgets: for blocks 32/64/128, p95 is 1217/1241/2451 microseconds. Proceed with
the bounded modulation/taper optimization and recheck parity.

Sanitizer follow-up: a CTest retry with leak detection disabled terminated with
exit 137 and no diagnostic, so its cause is not established. A bounded direct
test execution with ASan/UBSan, leak detection disabled, and a 16 MB quarantine
then passed all nine groups. Leak checking remains unvalidated; address/UB
checks are enabled and fatal. Preserve this environment/run distinction rather
than reporting the initial LeakSanitizer failure as an engine defect or a pass.

Completed native slice: static library, offline runner, CMake build, contract
tests, numerical harness, and documented public interface are implemented.
Final release CTest passes all nine groups (2.02 s); the final instrumented
direct executable also passes all nine groups with address/UB checks enabled.
All 30 final parity cases pass after recurrence/taper optimization, with worst
absolute sample error 1.667e-13 at tolerance 1e-10. The final real-input cases
reuse the hash-verified `/tmp` source slice; no additional stem read was needed.
The original Python engine, original listening renders, and imported research
remain intact.

Measured throughput improves 1.353–1.408x versus the unoptimized deterministic
native version. This is not sufficient for callback guarantees: final 32-sample
blocks exceed their duration in 1895/8882 measured calls; 64-sample blocks in
6/4441 (including a 9.94 ms maximum); 128-sample blocks in 0/2221. Preserve the
outlier without assuming its cause. Full commands, environment, timing limits,
and evidence links are in [native validation results](docs/native-validation-results.md).
The scheduled delay remains 383 samples, with no added engine adapter/FIFO.

Created one native listening WAV at
`/tmp/pitchwing-native-listening-20261008/06-minus7.wav`: 44.1 kHz mono float32,
289177 frames, 1156766 bytes; ffprobe confirms format/count. It preserves the
same excerpt, preroll, delay, tail, and uncompensated level. Hash and recipe are
in the final parity report. This corrected native variant needs user listening;
no claim is made that its sound is identical to the accepted original example.

Review findings persisted: build/test reviewer confirmed scope and command
consistency; README now uses the installed temporary CMake path and distinguishes
Python listening acceptance from native evidence. Engine reviewer checked
lifecycle/runner integration and independently identified phase/peak sensitivity.
The performance reviewer identified callback bursts and proposed the measured
bounded optimization. The final build has no compiler warnings or reported
address/UB errors; leak scanning and target-native Windows validation remain
unestablished. Next work: listen to the native render, reduce per-hop work,
address DC/low-dyad quality, then add stereo and smooth live pitch changes.

Final artifact audit: an independent reviewer checked the saved final/build
JSON against the validation summary and found no material errors in counts,
error maxima, timing, missed-callback counts, or throughput comparisons. It
confirmed the distinction between the deterministic reference and original
listening baseline, and the outstanding listening/leak/deadline limitations.
The edited native sources and documentation have no trailing-whitespace hits.

## 2026-10-08 — Taking Chances full-track native render

The user requested a more complicated example from
`stems/02 Taking Chances.m4a`. Header inspection reports stereo AAC at 44.1 kHz,
187.827 seconds, 3113835 source bytes, plus an embedded cover-art stream. Render
the complete audio at -7 semitones, matching the earlier preferred shift. The
engine is currently mono: use explicit `0.5L + 0.5R`, then preserve that same
decoded input for wet and 383-sample-delayed dry output. No normalization,
limiting, resampling, or core changes are planned. Output and raw scratch stay
under `/tmp`; source audio remains unchanged.

The existing native binary and header/source/runner hashes match the recorded
final validation, so no rebuild or test-suite rerun is needed. A bounded
read-only subagent reviewed the protocol without reading audio. Its findings:
decoded PCM frame count is authoritative for AAC, apply decoder priming handling
only once, retain the full 2527-sample engine drain, and pad dry to the same
length (383 leading zeros, input, 2144 trailing zeros). Stereo downmix can alter
phase-canceling material, and integrity/level statistics do not establish
perceptual quality. Validate float32 output finiteness, rate, frames, peak/RMS,
and full-scale exceedances; persist the exact commands and render metadata.

Completed: FFmpeg decoded the source once to 8283136 mono float64 frames,
using explicit equal-weight channel mixing at the original 44.1 kHz. The
existing native runner rendered the full input at -7 in 75.86 s wall time under
WSL (offline execution including I/O, not a callback-deadline measurement).
Wet and dry both contain 8285663 frames. Sample-by-sample verification proves
dry equals the float32 decode delayed by 383 samples with the documented tail.
All stored samples are finite; ffprobe confirms mono float32, 44.1 kHz, and
equal frame counts.

Level finding: unadjusted wet peaks at +3.010 dBFS (3236 samples above absolute
full scale); unadjusted decoded dry peaks at +1.752 dBFS (149 samples above
full scale). These float renders remain intact. To avoid playback clipping,
created a listening pair with the same fixed -6 dB gain on both, retaining
their relative levels. It is not independent normalization or limiting.
Listening peaks are -2.990 dBFS wet and -4.248 dBFS dry, with zero over-range
samples. Measured wet/dry full-stream RMS difference is -1.161 dB; listening
quality has not been judged.

Deliverables and reproducibility are in the
[corpus guide](experiments/corpus/README.md) and
[render record](experiments/corpus/results/2026-10-08-taking-chances-native.json).
The record includes tool versions, commands, source metadata, decoded-content
hash, native identity, WAV hashes, alignment, and level checks. Audio stays in
`/tmp/pitchwing-taking-chances-20261008-ozikic86/`: four WAVs total
132571064 bytes. Removed only the task-owned raw float64 intermediates after
verification. No original source, research measurement, or core code changed;
no tools were installed and no unrelated suites/corpus scans were run. Native
listening feedback and the existing engine quality/stereo/deadline limitations
remain outstanding.

Tool warning retained in the render record: FFmpeg reported a container stream
with an unset timescale, but decoding completed successfully. Raw-PCM encoding
also emitted duration-estimation/channel-layout notices. Explicit sample rate,
actual decoded frame counts, exact dry alignment, and final WAV checks were
used instead of inferring sample timing from those notices.

## 2026-10-08 — Readiness for a separate VST consumer

The user asked whether the engine can be used in a VST they are developing in
a separate project. Recorded that consumer context in PROJECT.md while keeping
plug-in implementation outside this repository's scope. Assessment: usable now
as an experimental mono, fixed-shift source dependency; production/live-use
readiness is not established. This is an integration assessment, not a new
listening acceptance or an instruction to build a VST here.

The main agent reviewed current scope, API/build files, and saved validation;
a bounded read-only subagent checked the consumer contract independently.
The in-tree static C++17 target is `pitchwing::pitchwing`, with bundled FFT
dependency and CMake minimum 3.20. There is no install/export package or Windows
SDK distribution. Compile sources using the consuming project's target
toolchain; the existing WSL/Linux `.a` cannot serve as a Windows library.
The current build also adds the offline runner and normally enables tests.
ELF shared-library consumers need position-independent code on the static
target; the engine CMake file does not currently enable it itself.

Wrapper responsibilities follow the existing API: prepare/destroy outside the
audio callback, give each instance exclusive access, check process status, and
use `latencySamples()` for host latency reporting (383 by default). Configure
for the actual sample rate; window sizes do not auto-scale. `flush` is a terminal
offline drain, not a call to make after every host block. Float/double buffers,
arbitrary blocks, and exact in-place processing are available without processing
allocations. Audio buffers can exceed full scale; no automatic limiter/gain
normalization is applied.

Outstanding practical limits: only mono is implemented; independent instances
do not establish coherent stereo behavior. Pitch changes after processing are
rejected with `PitchLocked` until reset; resetting discards history and is not
click-free live automation. WSL tests show missed short-block deadlines and do
not establish Windows/DAW callback performance. Known DC and close low-dyad
defects remain. Existing passing contract/parity/sanitizer checks are useful
evidence, but do not remove those limitations; leak validation remains open.
Next engine work should address callback bursts and safe live pitch changes,
then validate the intended channel layouts and target-native use. No builds,
audio runs, installations, or core/build changes were needed for this review.

## 2026-10-09 — Adapting the engine to ShiftKey

The user authorized inspecting `../ShiftKey` and updating the engine to its
requirements. Three bounded subagents reviewed the consumer, API/build needs,
and scheduling invariants; the sibling checkout is read-only and plug-in edits
remain outside this task. Requirements and rationale are persisted in
[the consumer requirements](docs/shiftkey-requirements.md) and PROJECT.md.
ShiftKey needs planar stereo, pitch updates every 1–32 samples without an added
smoothing ramp, fractional shifts through ±49 (including fine tuning), fixed
audio delay, and a separately measured curve-clock offset. Formant and quality
controls are unsupported capabilities, not implied engine features.

Implementation in progress: preserve static Engine and its evidence; add
LiveEngine with joint stereo tracking, sample-integrated pitch controls and
regional synthesis work spread across one extra hop. Geometry scales with rate
and targets about 10 ms total delay. Review found that pending frame snapshots
must remain immutable, near-cancelling stereo phase cross-products need a
coherence fallback, unity reacquisition can produce a transient phase/gain dip,
and frame-end guarding is not a dynamic anti-alias guarantee. These limits are
recorded instead of treating API coverage as sound-quality acceptance.

Build/package agent added source embedding defaults, position-independent
static library, install/export configuration and a separate shared-library
consumer smoke fixture, plus a concrete adapter example in
[ShiftKey integration](docs/shiftkey-integration.md). Core and test agents own
separate files; the main agent coordinates all builds/measurements under /tmp.
No external tools or dependencies are being installed. Validation follows
once the new core and tests are complete; no live readiness claim yet.

Completed the consumer-facing engine slice. `LiveEngine` now supplies linked
stereo float/double processing, active fractional ±49 targets, one-sample and
arbitrary blocks, exact in-place/duplicated-mono input, transactional validation,
reset/move/drain lifecycle, and fixed rate-scaled latency: 439/479/959 samples at
44.1/48/96 kHz. It integrates every accepted control sample without an added
pitch ramp, including commands shorter than a hop. The static Engine, imported
research and prior listening evidence are preserved. Formant preservation and
quality selection remain unsupported. Public contract and DSP rationale are in
[live-engine.md](docs/live-engine.md); concrete consumer adapter/CMake use is in
[shiftkey-integration.md](docs/shiftkey-integration.md).

Independent core review found that accepting 1e100 in double processing could
overflow later float callbacks through retained history. Fixed both overloads
to use a common 1e30 bound and added a mixed-precision delayed-output regression.
Reviewer confirmed buffer atomicity, crossed in-place reads, immutable pending
frames and completion before scheduled output. Existing library licensing was
not inferred from the FFT's MIT notice; that notice is included in staged files.

Optimized synthesis by preweighting shared modulation and calculating only the
real product needed by each channel. A saved comparison probe checked 144000
double samples over three rates and automated stereo tones: max difference
1.110e-16, RMS 1.792e-17, all finite. No original-engine parity or perceptual
equivalence is claimed for this new live algorithm. Timing benefit from this
small optimization is not established by the short sequential measurements.

Validation is complete for this slice: warning-enabled release builds pass
9 static and 11 live groups (3.62 s total), including allocation, all-or-nothing
failure, block partition, short-control, stereo and sustained-unity invariants.
Source embedding and staged `find_package` both build a shared consumer and pass
their smoke test. New live ASan+UBSan passes 11/11 at -O1. Static ASan+UBSan passes
9/9 with `handle_segv=0`; default-handler attempts repeatedly emitted
`DEADLYSIGNAL` without establishing a cause. Preserve this qualification and the
still-disabled leak checking. An unoptimized live sanitizer run hit its time
cap after nine groups. A stale test object from an edit/compile overlap caused
two earlier 10-group runs to assert the superseded double limit; explicitly
rebuilding that object resolved it. Full commands, failed-case evidence and
successful outputs are linked in [live validation](docs/live-validation.md).

Final diagnostic callback run uses differing-channel low chords, 0.25 s warmup
and 0.5 s measurement per case. No 32/64/128-sample budget exceedances were
observed at 44.1/48 kHz. At 96 kHz there were 1/1500 exceedances for automated
32-sample blocks and 3/750 for static 64-sample blocks. One-sample calls still
show work bursts; these internal chunks do not each receive an independent
DAW callback budget. WSL/synthetic/short-run evidence does not establish Windows
deadlines. The reviewed final timing probe excludes trailing partial blocks;
the initial report retains its older inclusion behavior explicitly.

The control probe measured 48 valid 220 Hz octave steps at 48 kHz across 12 hop
phases. Outgoing midpoint offsets after audio-delay subtraction average -0.878
and +1.232 samples; provisional ShiftKey clock compensation of zero is justified
for an initial trial. Returns to unity vary more, up to +131.625 samples
(2.742 ms), so no universal exact control alignment is claimed. The reviewer
confirmed event splitting/DFT arithmetic and required first-crossing validity
checks plus the 1024-Hann-window smearing caveat; both are recorded.

All builds, staging and generated binary/audio scratch stayed under /tmp. No
stems were reread or copied, no ShiftKey files were changed, and no external
tools were installed. A recursive sanitizer log grew to 1056285420 bytes under
/tmp; saved bounded failure excerpts/metadata and removed only that task-created
log. Future diagnostic capture must cap output as well as runtime. Compact
reports, source hashes and the arithmetic comparison source are durable under
docs/results; subagent design, review and measurement findings are persisted.

Ready for an external ShiftKey integration trial using the documented adapter.
Remaining validation: Windows/MSVC and actual host callback loads, new live-engine
listening including short curves and unity returns, more robust 96 kHz timing,
and control timing on real low guitars. Existing DC/low-dyad/alias limitations,
real recordings below F#1, and bass coverage remain unresolved; API coverage
does not close those sound-quality requirements.

Final evidence audit: an independent subagent verified the saved timing tables,
exceedance counts, step statistics, validity checks, optimization comparison,
release/sanitizer outcomes and limitations against the compact reports. Corrected
the signal description to state that the right channel is detuned by 1.003 and
uses different harmonic phases; no numerical claims changed. Scoped whitespace
checks of changed code/build/docs found no trailing whitespace.

## 2026-10-09 — Engine algorithm explanation

The user asked what kind of algorithm the engine uses. Reviewed current scope
and [the live design](docs/live-engine.md); a bounded read-only subagent checked
both native implementations. It is a custom FFT/STFT spectral-region transport
pitch shifter with phase-vocoder-like frequency and phase tracking. It selects
spectral peaks, assigns neighboring bins to regions, reconstructs each region
as a complex analytic signal, applies a phase-continuous frequency translation
of `(ratio - 1) * region_frequency`, and overlap-adds windowed contributions.
It does not use a time-stretch/resample pipeline or moving delay-line heads.
The static mono Engine and linked-stereo LiveEngine share this basic design;
LiveEngine adds shared stereo tracking and sample-integrated pitch controls.

Code review confirmed asymmetric historical analysis and a short synthesis
window: at 48 kHz, LiveEngine uses a 2048-sample analysis, 96-sample hop,
384-sample synthesis support, and 479-sample reported delay (about 9.98 ms).
Historical analysis length is not equivalent to future lookahead. Rigid region
translation preserves internal frequency spacing, explaining why unresolved
close low notes can shift incorrectly relative to one another. Known DC,
aliasing, settling and unity-transition limitations remain; this explanation
does not establish new sound-quality acceptance. No DSP changes, builds,
experiments or installations were needed; validation was documentation/source
inspection. Existing low-register and target-native validation work remains.

## 2026-10-10 — Live chord-decay clicks: diagnosis and quality programme

Request: the ShiftKey consumer makes clicking artefacts on long-decaying live
chords; `stems/chord.wav` (clean DI, mono PCM24 44.1 kHz, 21.7 s) is the
example, clicks heard after shifting about ±12 semitones. Check whether this is
an algorithm problem, then maximise quality at the fixed low latency using the
research and the current code. Work on branch `engine-quality`; use research,
prototyping and validation subagents; run core ideas through a gauntlet;
record everything here. Mono is essential, stereo desirable; Windows and macOS
(Apple Silicon) targets, macOS debugging deferred to another session.

Setup: committed the pre-existing tree as the baseline on `master`
(`stems/` added to `.gitignore`: 51 MB of user audio stays out of git) and
branched `engine-quality`. Rebuilt Release in `/tmp/pitchwing-build` with the
approved temporary CMake. Added `tools/pitchwing_live_render.cpp` (raw float64
mono through `LiveEngine`, 32-sample chunks like ShiftKey, full tail) and
`scripts/artifact_scan.py` (per-second RMS, relative/absolute step counts,
wet/dry high-frequency ratio). Diagnostic only; thresholds are heuristics.

Findings:

- The DI itself contains the clicks. Between 15.05 s and 18.9 s, during the
  chord decay at −33…−44 dBFS, there are 90 one-sample polarity flips of the
  waveform (x → −x, median step 0.039, max 0.089). They sit on a ≈6.0 ms grid
  (264.6 samples; twelve consecutive events drift < 1 sample), not on the
  engine's 88-sample hop grid. The DI's >2 kHz energy in the decay is ~1300×
  its sustain level. Positions are listed in
  [the DI scan](docs/results/2026-10-10-chord-di-scan.json).
- Rendering the DI through `LiveEngine` at +12/−12 does not amplify them:
  per-second counts of relative steps are similar (e.g. 15 s: 78 dry, 90 at
  +12, 36 at −12), high-frequency wet/dry energy in the decay is 1.23× (+12) and
  0.39× (−12), and the burst spread around a flip is unchanged (72 ms both).
  See [+12](docs/results/2026-10-10-chord-plus12-scan.json) and
  [−12](docs/results/2026-10-10-chord-minus12-scan.json) scans.
- A clean synthetic decaying five-note low chord (F#1–C#3, 12 harmonics, 10 s)
  through `LiveEngine` at −12/−7/−2/+5/+12 at 44.1 and 48 kHz shows no
  discontinuities after the attack (relative step ≤ 0.12 after 1 s; the only
  flagged samples are in the near-silent tail where the relative metric is
  meaningless).
- The attack at 8.85 s reaches 0.99999 in the DI (11 samples), i.e. the DI
  was already clipped before the engine.

Conclusion so far: the clicks in this recording are present in the input, not
created by the algorithm, so the 6 ms step source (interface/driver/DAW
resampling? the grid is not integer at 44.1 kHz) must be found on the user's
side. The user re-listened and confirmed the artefacts are in the DI. Listening excerpts (14–19 s, dry/+12/−12)
are in `/tmp/pitchwing-chord/`. This does not clear the engine of the known
defects (DC, low dyads, ungated ancestry, no transient handling); those are
now the quality programme. Two research subagents are writing
`docs/quality/2026-10-10-code-caveats.md` and
`docs/quality/2026-10-10-research-options.md`; next steps follow their lists
through a gauntlet before prototyping.

Baseline harness for the quality work (all on `engine-quality`):

- `experiments/transport/evaluate.py --native <pitchwing_live_render>` now
  drives the native `LiveEngine` through the existing synthetic matrix (tones,
  dyads, DC, gate/chord-change temporal fixtures, unity impulse) in about 4 s
  (quick) / 10 s (full) under WSL. `scripts/summarize_eval.py` prints the key
  numbers of one or more result files for before/after comparison.
- Native full baseline: [2026-10-10-live-baseline-full.json](docs/results/2026-10-10-live-baseline-full.json)
  (quick variant alongside). It reproduces the Python findings: dyad spacing
  unchanged (B0/C1 1.84 Hz at −7/+7 instead of 1.23/2.75; E1/F1 2.45 instead of
  1.64/3.67, fit share 0.002–0.038), DC 0.2 → 0.018 (−7) / 0.15 (+7), E2 ±7 st
  error +7.03/−4.71 cents with fit share 0.81/0.62, B0–F#1 gain −1.0…−1.5 dB,
  chord-crossfade late fit 0.17 (−7) / 0.04 (+7), onset difference up to
  3.3 ms, envelope NRMSE 0.15–0.40 on nonzero shifts. Unity is exact at 479.
- `tools/pitchwing_live_render` accepts an optional per-sample control file
  (semitones per input sample, applied before each block) for automation tests.

In flight at the time of writing (results land in the repository, not in
context): a code-caveat audit (`docs/quality/2026-10-10-code-caveats.md`), a
research-options synthesis (`docs/quality/2026-10-10-research-options.md`),
and a matched-delay Signalsmith Stretch baseline
(`experiments/stretch-baseline/`, `docs/quality/2026-10-10-stretch-baseline.md`,
`docs/results/2026-10-10-stretch-*.json`). Next: merge those into a ranked
improvement plan, run the core design decisions through a gauntlet (notably:
single-IFFT integer/fractional-bin region translation with per-region phase
accumulation instead of up to 64 analytic IFFTs per hop; gated peak tracking
with birth/death; past-only transient phase reset; explicit DC/sub-bin policy;
unresolved-dyad treatment), then prototype one change at a time against the
baseline JSON and the `06/minus7` listening excerpt. Session handoff is planned
once the three agents report, because the conversation context is near the
user's 250k limit.

Stretch baseline reported (see
[docs/quality/2026-10-10-stretch-baseline.md](docs/quality/2026-10-10-stretch-baseline.md),
`experiments/stretch-baseline/`, `docs/results/2026-10-10-stretch-*.json`):
Signalsmith Stretch 1.3.2 at 480/96 (10.0 ms) and 512/64 (10.667 ms), tonality
limit 0, is outside its operating range: low tones land 190–1030 cents off with
fit share ≤ 0.06, A4 off by 4–43 cents, DC AC ripple 0.09–0.18, late chord fit
0.002–0.35; the same tool at Stretch's 120 ms default transposes correctly, so
the harness is sound. Pitchwing at 479 samples is far ahead on low tones, DC and
attacks. One lead for Pitchwing: on the real DI at +12 its >2 kHz wet/dry energy
over loud seconds is median 21.8× / max 1136× versus Stretch 1.4× / 8.4×. Part of
that is legitimate upward transposition (Stretch barely transposes at 10 ms), so
treat it as a candidate upward-shift artefact (alias taper, noise-floor regions
translated into the treble) to measure against a synthetic +12 fixture, not a
confirmed defect. Stretch excerpts are in `/tmp/pitchwing-chord/`; no listening
yet. Nothing from Stretch is vendored into the engine.

Research-options synthesis reported
([docs/quality/2026-10-10-research-options.md](docs/quality/2026-10-10-research-options.md),
425 lines, sources: Laroche–Dolson 1999 full text, PVDR, Rubber Band R3 sources
read-only, Stretch design notes/tags, onset and close-sinusoid literature; no
2023–2026 guitar-specific low-latency papers beyond Polak–Erkut 2025). Notable
inference from existing numbers: the E2 errors (+7.03 cents at −7, −4.71 at
+7, ratio −1.49) match the (r−1)/r signature of a region-frequency-estimate
bias (~−14 cents, 0.03 bin), i.e. an estimator problem (parabolic fit on the
asymmetric lobe or phase-difference gate fallback), not a transport fault —
unverified against the code path. Ranked candidates, all at zero added delay:
(1) gated ancestry with birth/death hysteresis and per-region confidence;
(2) window-matched frequency estimator; (3) soft cos² region boundaries at
magnitude valleys to stop θ jumps on bin reassignment; (4) alias guard from the
control snapshot's maximum ratio plus mirroring; (5) explicit DC policy (fixed
untranslated sub-25 Hz region, or a 5 Hz high-pass with DC out of scope);
(6) past-only onset score (FFT 512 spectral flux, ~+2 % CPU) with region-local
θ re-anchor, never global or dry-mixed; (7) low-band zoom estimator (decimate by
8, 341 ms, 2.9 Hz bins) feeding parametric resynthesis of unresolved low
regions — highest potential against the dyad failure, 100–170 ms settling risk,
B0/C1 explicitly not reachable; (8) cheaper synthesis: direct oscillator
evaluation over the 384-sample support (flat in region count) or single-IFFT
Laroche–Dolson translation (~60× cheaper, loses sample-accurate control,
−51 dBc interpolation sidebands at 75 % overlap); (9) per-channel ω refinement;
(10) tonality limit as a named option. Not-to-do list with evidence: serial STN,
universal transient bypass, global/periodic phase resets, PVDR drop-in, raising
N alone, time-stretch+resampler pipelines, Ocean quantisation, envelope
time-rescaling of unresolved regions, random residual phases. All CPU figures
are flop arithmetic; all gains are hypotheses gated by the listed tests.

Code-caveat audit reported
([docs/quality/2026-10-10-code-caveats.md](docs/quality/2026-10-10-code-caveats.md),
280 lines, read-only reasoning on `src/LiveEngine.cpp`, no numeric runs).
Ranked mechanisms: (1) unresolved low regions share one ω whose estimate
wobbles with beat phase (IF gate accepts 2-bin jumps) → beat-rate warble/FM;
(2) region-boundary churn from peak births/deaths (noise above the 1e-4 floor
in decay tails, 64-cap re-ranking, merges/splits) gives bins a phase step
θ_A−θ_B → crackle at lobe-skirt level; ungated inheritance lets new noise
peaks free-run; (3) brick-wall region partitions cannot represent the
192-sample falling window edge and S=Hann/(4A) amplifies the tail (1/A up to
122×) → predicted hop-rate buzz scaling with |r−1|, consistent with the 3–4 %
non-line energy on B0/E1 (unverified, cheap fixture); (4) 64-region cap drops
partials onto neighbours' δ (≈60-cent ghosts) on dense chords; (5) nonunity →
exact-unity transition mixes rotated and unrotated copies, up to a 6 ms null
per partial when the target lands exactly on 0 for ≥ L samples; (6) DC path:
S is not a partition of unity (sum 1.10–1.15, ±2.3 % hop-rate ripple;
predicted AC RMS 0.0033 for 0.2 DC matches the measured 0.0036), sub-bin-3
fundamentals get an unshifted ghost — fix with input HPF + dc·Hann/4; (7) hard
drop of sub-zero destinations at −12 toggles a skirt bin (≈−25 dB clicks on
low E) — 1-bin low-side taper; (8) onset lag; (9) IF-gate toggles; (10) alias
taper from the newest control only. Verified consistent: hopArea,
negativeSuffix, recurrence re-anchoring, ring disjointness, scheduler
completion, region coverage; only oddity is an up-to-500-element sort per
frame on the audio thread. Top five fixtures to run first: unity-transition
dip, 3.5-bin vs 30-bin tone pair at +12/−2 for hop-rate sidebands, noisy
decaying chord for churn crackle, E2+G#2 warble, DC buzz and low-bin toggle
at −12. Fixture thresholds are reasoning-based and need tuning once rendered.

Handoff point: all three reports are in the repository. Resume by reading the
three `docs/quality/2026-10-10-*.md` files, then run the five fixtures above
through `tools/pitchwing_live_render` + `scripts/artifact_scan.py` to confirm
which mechanisms are real before any fix; gauntlet the design choices (soft
region boundaries / direct-oscillator synthesis / gated tracking / DC policy /
low-band zoom estimator); fix one mechanism at a time with before/after runs of
`evaluate.py --native` and the preserved baseline JSON; keep the `06/minus7`
excerpt as the listening reference and re-render it after each change.

## 2026-10-10 — Quality programme, session 2: confirmation, gauntlet, estimator

Continuation of the previous entry on `engine-quality` (worked in the git
worktree `worktree-engine-quality-work`, build in `/tmp/pitchwing-build-wt`;
the worktree binary reproduces the quick baseline JSON exactly).

Estimator finding (verified numerically, `experiments/quality/estimator_probe.py`
and `estimator_fit.py`, output in
[docs/results/2026-10-10-estimator-probe.txt](docs/results/2026-10-10-estimator-probe.txt)):
replicating `findRegions` on a stationary tone shows the cross-frame
instantaneous-frequency estimate (`LiveEngine.cpp` 289–307) is corrupted by the
negative-frequency image of the real input (and by DC/leakage): per-frame
estimates wobble 152 cents peak-to-peak at E2 (bin 3.5), 376–433 at F#1/E1,
681 at B0, with long-run means of −16 (E2), −5, −6, −16 cents. The E2 mean
predicts output errors of +8.0 (−7 st) / −5.3 (+7 st) cents via
`(r−1)/r`; the baseline measured +6.96 / −4.66. The parabola fallback is as
bad (29–407 c pp). So the engine's low regions carry a per-hop frequency
jitter of tens of cents times |r−1| — a steady FM source on every low note,
independent of the dyad problem. The analysis window's sidelobes are high
(−18 dB at 2 bins, −36 at 8, −47 at 12) because of its 192-sample fall.
A 3-bin complex lobe fit against the tabulated window spectrum with the image
term included (`X[k] = a·A(ω_k−ω) + ā·A(ω_k+ω)`, 1-D search over ω, linear
solve for `a`) gives |bias| ≤ 0.2 cents and ≤ 2 cents pp on all isolated
tones B0–A4; with a −6 dB second harmonic 3.5 bins away it is 30 c pp (IF:
234); on an unresolved dyad (E2+G#2) every estimator is meaningless, as
expected. This is candidate G of the research options, now with evidence; it
replaces the IF estimate rather than refining it.

Fixture confirmation run (validation subagent; `scripts/quality_fixtures.py`,
[docs/results/2026-10-10-fixtures.json](docs/results/2026-10-10-fixtures.json),
[docs/quality/2026-10-10-fixture-results.md](docs/quality/2026-10-10-fixture-results.md),
32 renders, 48 kHz, ~40 s): unity-transition dip CONFIRMED (+3→0: per-partial
dips to −15 dB at 1 kHz, −5 dB at 220 Hz, depth phase-dependent, 9/10 fail;
0→+3 has no dip); low-dyad warble/spacing CONFIRMED (E2+G#2 output spacing
stays 21.42 Hz at ±7 instead of 14.3/32.1, each line 3.5–5 Hz off, outer beat
sidebands −24…−30 dB); DC CONFIRMED (0.05 DC: hop line −60.8 dBFS, mean gain
0.725; E1 unshifted ghost −17.9 dB re the shifted line at ±12 — relevant to the
user's F#1/G#1 tunings); churn crackle REFUTED at −60/−40 dBFS noise (flux
ratio 0.87–0.96, no extra events); sub-zero toggling clicks REFUTED, gain loss
confirmed (−0.9 dB at E2 −12); hop-rate sidebands at −41…−47 dB exist for all
four tone pairs but are spacing-independent (not partition ringing); the
spacing-dependent artefact is the neighbour's skirt translated by the wrong δ:
−19 dB lines at f ± (f2−f1)(r−1) for a 3.5-bin pair, < −43 dB at 30 bins. +12
on a clean synthetic chord gives 4.5× wet/dry > 2 kHz, so ~5× of the real DI's
21.8× is unexplained (noise floor/clicks translated up).

Gauntlet (four reviewers, condensed with synthesis in
[docs/quality/2026-10-10-gauntlet.md](docs/quality/2026-10-10-gauntlet.md)):
soft cos² region masks dropped (steady |w+(1−w)e^{jΔθ}| notch, split-lobe
skirts, degenerate at 2–3.5 bin spacings); gated ancestry with θ=0 births
dropped (caveat-5 dips at beat rate) in favour of bin-ownership ancestry;
no HPF in the engine (exact unity contract); flux-onset re-anchoring deferred
(band-scoped global reset, lag is window-caused); parametric low band
re-scoped to a multi-resolution evaluation; direct-oscillator synthesis dropped
(no CPU win below ~28 regions); image-aware estimator adopted. New order:
unity-transition fix → estimator + ownership ancestry → DC gain/fold/bin-0
ghost → window-tail study → multi-resolution low band → profiling.

Unity-transition fix (commit after 293aab0): `findRegions` now inherits
rotations in unity frames too and slews them to zero (≤ 10-cent glide, 100 Hz
floor); `prepareFrame` takes the exact-unity path only when no rotation is
settling. Fixture `unity_transition` before/after: per-partial worst dips
−15.0 dB (1 kHz) / −5.0 dB (220 Hz) → +0.2…+0.7 dB; 1 ms total-RMS variation
−3.1 → −2.0 dB (same class as the previously accepted 0→+3 direction, 1.9 dB;
steady control 0.0). Quick evaluation matrix unchanged (identical numbers).
The eventual-unity test now waits 420 hops for the glide. Cost: region
rendering continues up to ~0.8 s after a return to exactly 0.

Estimator, DC and fold step (one commit, three mechanisms measured one at a
time with `evaluate.py --quick`; full run in
[docs/results/2026-10-10-live-step3-full.json](docs/results/2026-10-10-live-step3-full.json),
fixtures in [docs/results/2026-10-10-fixtures-step3.json](docs/results/2026-10-10-fixtures-step3.json)):

- Image-aware lobe fit replaces parabola + cross-frame IF (`fitOmega`,
  `lobeFitCost`, window-spectrum table built once per instance, 5 × 13 cost
  evaluations per region per hop). E2 ±7: +6.96/−4.66 cents → 0.00/0.01, fit
  0.94/0.87 → 0.999; all tone fits 0.96–0.98 → 0.98–0.99; −7 gains unchanged
  at this step, +7 gains improved 0.25–0.5 dB. The quick DC case regressed
  (ripple 0.001 → 0.098) because the DC lobe was fitted as a 0.5–1.6 bin tone.
- Bin-0 split + partition-of-unity DC term (see `docs/live-engine.md`). DC+tone
  fixture hop lines −61 → −148 dBFS, DC gain 0.725 → 1.0, E1 ghost −18 → −75 dB.
  Two defects found and fixed on the way: (a) for peak bin 1 the fit range did
  not reach 0, so pure DC was still translated; (b) a region at ω≈0 (DC lobe)
  kept the rotation inherited during the startup transient and emitted
  0.2·cos θ (−0.19 for 0.2 DC) — the unity slew is now applied to any region
  whose per-hop advance is below 1e-3 rad; (c) near ω≈0 the two-parameter
  amplitude is ill-conditioned (two huge cancelling terms) and its positive
  share blew up the temporal fixtures (envelope gain 32–57×, nrmse 23–113 at
  +7, masked at −7 by the old sub-zero drop) — bounded by falling back to the
  real-only solution when |a|·ΣA > 4·‖X‖.
- Fold instead of drop for sub-zero destinations: −7 low-tone gain −1.1…−1.37
  → −0.80/−0.84/−0.71 dB (B0/E1/F#1), E2 −0.90 → −0.23 dB. No click fixture
  change (none existed).

Full-matrix deltas vs the baseline: every tone's cents error ≤ 0.1 (was up to
7.0), fits 0.98–0.999, gain losses −0.7…−0.9 dB (was −1.0…−1.5); dyads
unchanged (expected); DC 0.2 → 0.199/0.211 mean with ripple 0.005/0.019 (was
0.018/0.146 mean); temporal mixed and small: B0 gate −7 onset diff 1.25 →
1.94 ms and late fit 0.85 → 0.77 (worse), +7 late fit 0.73 → 0.82, chord
crossfade late fit 0.17/0.04 → 0.24/0.14 (better), envelope NRMSE within
±0.03. Fixture `warble` unchanged (dyad spacing still 21.42 Hz), `hf_junk`
unchanged (4.4×). Listening renders of the new engine (not yet heard):
`/tmp/pitchwing-listening-step3/` — `06-dry.wav`, `06-step3--7.wav`,
`06-step3--2.wav` (the 2026-10-08 excerpt source, 44.1 kHz), and the chord DI
14–19 s dry/+12/−12. Tests green (ctest, 2 suites).

WSL timing probe (`pitchwing_live_probe timing`, diagnostic only, not a
target-native result), old frozen build vs new: 48 kHz block 64 mean 302 →
352 µs (p95 360 → 437), block 128 600 → 698 µs; 96 kHz block 32 mean 159 →
166 µs with 10–22 deadline misses out of 1500 (0 before, WSL jitter is of the
same order); 96 kHz block 1 misses unchanged (~4210/48000, pre-existing). The
frequency fit costs 65 cost evaluations per region per hop; if the native
budget needs it, reduce the 5 grid rounds to 4 (resolution 0.0056 bin) first.

Window-tail / hop-line / onset-lag study (subagent;
`experiments/quality/window_study.py`,
[docs/results/2026-10-10-window-study.json](docs/results/2026-10-10-window-study.json),
[docs/quality/2026-10-10-window-study.md](docs/quality/2026-10-10-window-study.md),
renders on the pre-estimator build, re-measured after): the spacing-independent
hop-rate lines (−52 dB at f−500 Hz for a lone 1 kHz tone, any shift) come from
a spurious second region on the tone's own window skirt (a −62 dB local maximum
at bin 6, above the 1e-4 floor) whose slice of the skirt is re-emitted with its
own translation; a NumPy replay with the engine's peak picking reproduces every
render to 0.5 dB, a single-region model gives −81 dB. Partition-of-unity error,
ω jitter and the Nyquist taper are refuted. Window shape is not the lever: no
tail (cos/Hann/Blackman, F = 192…384) moves the near sidelobes (−16/−18 dB at
1.75/2 bins, set by the long sine rise) by more than 1 dB; cos F = 320/384
lowers the 3.5–10 bin skirt by 4–9 dB at the cost of 1/A up to 245 and a
spurious-region-prone tail; Hann/Blackman falls are unusable (synthesis window
ends at its maximum). Onset lag: on the region path at 0.0001 st the 50 %
crossing is within 0.04 ms of the input and 90 %-energy within 0.3 ms; at +7
it is +0.73 ms / +3.1 ms with −2.7 dB first-5 ms energy — the lag is caused by
the shift (region-dependent rotation dispersing the transient), not by the
window or region bandpass.

Skirt-peak rejection (`dropSkirtPeaks`, lobe table widened to ±48 bins): a
local maximum is kept only if it exceeds twice the skirt predicted from the
nearest larger peak on each side (window table at distance − 0.5 bin, image
included). Lone 1 kHz tone at +7/+12/−2/−7: f−500 Hz line −51.7 → −81.6 dB,
non-line residual −51.5 → −73 dB (the single-region model value); the f−1000 Hz
line stays at −70 dB (unexplained, model −79); 300 Hz residual −48 dB unchanged.
Quick matrix: tones/DC/dyads unchanged; B0 gate −7 late fit 0.77 → 0.85 (back
to baseline), chord crossfade +7 late fit 0.14 → 0.11 and envelope lag 0 →
−11 ms (metric sensitive to the fitted gain; nrmse unchanged 0.31). Fixtures
`hop_sidebands` (the −19 dB skirt-slice lines of a real 3.5-bin neighbour remain
— that is brick-wall partitioning of resolved neighbours and needs a different
fix), `churn_crackle`, `hf_junk` unchanged.

Handoff point (context limit): all work is committed on the worktree branch
`worktree-engine-quality-work` (worktree `.claude/worktrees/engine-quality-work`,
build `/tmp/pitchwing-build-wt2`); `engine-quality` can be fast-forwarded to it.
Listening renders of the final build: `/tmp/pitchwing-listening-step4/`
(06 dry/−7/−2 at 44.1 kHz; chord DI 14–19 s dry/+12/−12) — not yet heard by the
user. Next: brief gauntlet (formalist + historian) of
`docs/quality/2026-10-10-multires-plan.md`, then prototype the long low-band
analysis with `N_low` as a constructor constant (4096 and 8192), measured with
`evaluate.py`, `quality_fixtures.py --only warble` (spacing must scale), a new
bend fixture and the window-study Q3 chord-onset fixture; then the resolved-
neighbour skirt-slice lines (−19 dB) — candidates: identity-locked per-bin
phase for skirt bins or boundary placement at the predicted skirt crossing;
then profiling (`line 418` clear, audio-thread sort) and stereo refinement.

Unresolved low dyads: estimation-only multi-resolution split (session 3).
Gauntlet of the multi-resolution plan (formalist + historian, condensed in
[docs/quality/2026-10-10-multires-gauntlet.md](docs/quality/2026-10-10-multires-gauntlet.md)):
both converged that the soft crossover between two transported partitions
re-creates the rejected soft-mask notch/ghost; historian recommended
multi-resolution for estimation only with a short-frame amplitude split
(Dressler; Keiler & Marchand; Virtanen & Klapuri). Probes
(`experiments/quality/twolobe_probe.py`, `split_probe.py`): the short-frame
amplitude fit is well conditioned (cond 1.8 at 0.9 bin, ≤ 4 at 0.45 bin);
frequencies from the short frame alone fail with harmonics (134 c p-p); from a
4n frame with single-lobe fits 14 c p-p, with a joint cluster fit 2–5 c p-p
(1 s decay ≤ 7 c); 2n frames fail. The transported long band was not built.

Implementation (`src/LiveEngine.cpp`, `docs/live-engine.md` "Linked stereo
analysis"): history ring 4n, long FFT per channel per non-unity hop, long peak
search below 700 Hz, region merging, gated split, joint fits, residual and
component transport entries (`Region::Kind`), mirrored image bins for
components, bin-0 shares per entry. Window lobe tables now come from a closed
form (`windowSpectrum`) instead of a direct sum (needed for the 8192-sample
window). Debugging on the way (instrumented renders): (a) the dyad shows one
or two short peaks depending on the beat phase, so the split flipped on and
off (IF p-p 1380 c) → merge neighbouring regions whose long peaks are < 3 short
bins apart; (b) components' image term translated by +δ left f−δ lines at
−31 dB (residual re ideal two-tone −30 dB) → mirrored bins, residual −51 dB;
(c) long-window skirt ripple (−60…−90 dB) inside wide regions split single
notes (E1 ghost −76 → −50 dB, single-note bend hold 5 → 11 c) → candidates must
lie within 2.5 short bins of a short peak and ≥ −40 dB re the strongest.

Results (full matrix
[docs/results/2026-10-10-live-step5-split-full.json](docs/results/2026-10-10-live-step5-split-full.json),
fixtures [docs/results/2026-10-10-fixtures-step5-split.json](docs/results/2026-10-10-fixtures-step5-split.json),
vs step3): warble −7/+7 lines 54.93/69.21 and 123.41/155.64 Hz (required
55.0/69.3, 123.48/155.57), spacing error 49.9/−33.2 % → −0.1/+0.4 %, outer beat
sidebands −26/−17 → −86/−90 dB, IF p-p 435/259 → 11/1.5 c (static two-tone
reference 18/1.4); hop_sidebands 1000+1703 Hz worst line −44 → −50 dB, non-line
residual −38/−40 → −47 dB; E1 ghost −76/−83 → −83/−84 dB; DC hop line −148 →
−166 dBFS; B0 gate late fit 0.77/0.82 → 0.87/0.84; tones, DC, informational
semitone dyads (B0/C1, E1/F1: 1.8–2.5 Hz, out of reach) and the other fixtures
unchanged. New fixture `bend` (E2 + 2nd harmonic, +2 st over 300 ms and back,
fundamental IF error): unchanged vs the old build (−7 max 4.5/10.8/2.0/14.6 c
per window); at +7 the holds show 62 c excursions in both builds — the −19 dB
skirt-slice lines of the 2nd harmonic (next defect). Tests green.

Lobe ownership (step 6). New fixture `bend_model` (`scripts/quality_fixtures.py`:
bent E2 and E2+G#2 with 2nd harmonics, per-20 ms least-squares residual of the
output against the ideally shifted partials; old build vs split build in
[docs/results/2026-10-10-bend-model-step4.json](docs/results/2026-10-10-bend-model-step4.json) /
[step5](docs/results/2026-10-10-bend-model-step5.json)) showed (a) a single E2+H2
note has a −18…−19 dB residual in every build — the skirt-slice defect is much
larger than the hop_sidebands line level suggested; (b) the split dyad's hold
after the bend was only −30/−21 dB because the merge test flipped (long-peak gap
11 vs 12 long bins), clipping components to different bins each frame and
handing their skirts to residuals with jumping `w` (103↔127 Hz). One mechanism
fixes both: every well-fitted partial owns its whole lobe (±24 bins, image on
mirrored bins), bin owners render `X − Σ lobes` (`docs/live-engine.md`).
First attempt regressed pure DC at +7 (mean 0.21 → 0.15): the DC lobe's
positive/image split is ill-defined; lobes now need centre ≥ 1 bin, and a
lobe-less lowest region keeps its bin-0 share (dropping it double-counted DC,
mean 0.30).

Results ([full matrix](docs/results/2026-10-10-live-step6-lobes-full.json),
[fixtures](docs/results/2026-10-10-fixtures-step6-lobes.json), vs step 5):
every low tone B0–E2 at ±1/±7 now gain −0.03…0.00 dB and fit 1.000 (was
−0.7…−0.9 dB, 0.984–0.99), cents ≤ 0.03; hop_sidebands worst line −45…−50 →
−58…−60 dB, non-line residual −17 → −35 dB (3.5-bin pair) and −47 → −56 dB;
bend +7 holds 62 → 3.3 c, sweeps 70/62 → 15/14 c (−7 unchanged within 1.5 c);
bend_model single E2 −19 → −23…−25 dB, dyad holds −52 → −56 dB, post-bend hold
−30/−21 → −41/−34 dB; B0 gate env gain 0.80/0.89 → 0.84/0.93; DC, dyads
(informational), churn, unity, warble unchanged or better. Regression:
hf_junk wet/dry > 2 kHz at +12 4.49 → 4.88× (+0.4 dB; unexplained). The
remaining −23 dB single-note residual is not yet analysed.

Chord onset and CPU (step 7). Window-study Q3 chord-onset fixture, old build vs
step 6 ([docs/results/2026-10-10-chord-onset-step6.json](docs/results/2026-10-10-chord-onset-step6.json)):
unchanged (+7 mean 50 % lag 0.78 ms, first-5 ms energy −2.2 dB) — the split adds
no bloom since nothing is transported from the long frame. WSL timing probe
(diagnostic): the undecimated long FFT (two complex FFT(4n) per hop) raised 48 kHz
block-64 mean 352 → 421 µs and 96 kHz block-32 misses 10–22 → 250/1500 (once
per hop). The long analysis now runs on a decimated copy (factor 8 at 48 kHz,
polyphase Kaiser FIR computed every M input samples, FFT 4n/M points, same bin
spacing): 48 kHz block 64 358 µs, 96 kHz block 32 21–28 misses
([docs/results/2026-10-10-timing-step7.txt](docs/results/2026-10-10-timing-step7.txt)).
Quality equivalent to step 6 ([matrix](docs/results/2026-10-10-live-step7-decimated-full.json),
[fixtures](docs/results/2026-10-10-fixtures-step7-decimated.json); only warble
−7 IF p-p 8.5 → 12.7 c, below its 17.8 c static two-tone reference).

Neighbour-cleaned peak fits (step 8). The −23 dB single E2+H2 residual after
step 6 was h2 content moved by the fundamental's δ (a −14 dB line at 138 Hz at
−7; h2 0.15 → 0.13): the fundamental's skirt 3.5 bins away failed h2's 2 %
lobe-quality gate, so h2 had no lobe and its skirt went with the fundamental.
Peaks are now refitted on their three bins with the credible neighbours'
first-pass lobes removed (`fitPeaks`, `docs/live-engine.md`). Attempts: removing
all neighbours broke pure DC at +7 (mean 0.15) via DC-lobe sidelobe "peaks";
removing only lobe-quality neighbours missed h2 (−40…−47 dB); a looser
credibility gate (30 %) restores −54 dB with DC intact. The doubled fits raised
96 kHz block-32 misses to 250/1500; replacing the nested 5×13 grid by a 13-point
grid + 4 parabolic steps (refit: 4 steps from 0.15 bin; 0.05 bin cost 3 dB
because it could not reach the bias) brought timing below step 3
([timing](docs/results/2026-10-10-timing-step8.txt): 48 kHz block 64 345 µs,
96 kHz block 32 26/1500 misses, WSL diagnostic).

Results vs step 7 ([matrix](docs/results/2026-10-10-live-step8-refit-full.json),
[fixtures](docs/results/2026-10-10-fixtures-step8-refit.json)): bend_model single
E2+H2 holds −23 → −54 dB, bends −22…−25 → −36…−46 dB; bend fixture max error
≤ 7 c everywhere (was 12–15 c in sweeps); hop_sidebands 3.5-bin pair non-line
residual −35 → −52 dB; tones, DC, dyads, temporal unchanged within noise.
Churn: one borderline 4×-median event appears in one variant between runs
(noisy input or noise-on-output) and does not reproduce over the full render;
flux ratios 0.87–0.98 (pass ±0.2). hf_junk +12 4.88 → 5.2× (+0.3 dB,
cumulative +0.6 dB since step 5; unexplained, open). The split dyad's bends
remain the weakest case (−17…−20 dB worst blocks): long-frame lag on moving
partials.

Listening renders of step 8 (not yet heard): `/tmp/pitchwing-listening-step8/`
— 06 excerpt dry / step4 / step8 at −7 and −2 (44.1 kHz), chord DI 14–19 s
dry / step4 / step8 at ±12. Objective check on the chord DI: wet/dry energy
> 2 kHz unchanged (1.20/1.21 at +12, 0.38/0.39 at −12), +12 level −1.8 → −0.4 dB.
The step-4 binary used for A/B is built from `git archive 84a8683` in
`/tmp/pw-old-build`.

Handoff point (session 3): work committed on `worktree-engine-quality-work`
through step 8. Open, in priority order: (1) split dyads while bending
(bend_model worst blocks −17…−20 dB; long-frame lag on moving partials);
(2) hf_junk +12 4.5 → 5.2× synthetic (+0.6 dB, unexplained; real DI unchanged);
(3) onset lag at +7 (0.78 ms, shift-caused, unchanged); (4) user listening of
step 8; (5) profiling (sort, model fill), 44.1 kHz fixture runs, stereo checks,
MSVC notes.

Dense low chords (step 9). The crossfade fixture's late fit (0.24/0.12) turned
out to be a stationary problem: through every build so far a stationary
E1+B1+E2 chord (8 harmonics each) fitted 0.22/0.12, E1+B1 0.16/0.07, B1 alone
0.84/0.87, E1 alone 0.83/0.80 (`experiments/quality/chord_fit.py`,
[docs/results/2026-10-10-chords-timing-step9.txt](docs/results/2026-10-10-chords-timing-step9.txt)).
Low harmonic series sit 1.8–2.6 short bins apart, their long peaks chain into
one group, and `maxSplit = 4` rejected every real chord. Now 32 components per
group, local two-pass long refits instead of the joint coordinate descent, and
oscillator rendering of components (the IFFT-per-component version doubled the
WSL mean cost: 48 kHz block 64 345 → 712 µs; with oscillators 389 µs).
Results ([matrix](docs/results/2026-10-10-live-step9-chords-full.json),
[fixtures](docs/results/2026-10-10-fixtures-step9-chords.json)): stationary
chords 0.94–0.98 (first chord B0+F#1+B1 0.32/0.09 → 0.90/0.88), single notes
1.0 (E1 0.95); low_chord_crossfade late fit 0.24/0.12 → 0.94/0.95, envelope
gain 0.78/0.76 → 0.96/1.0; B0 gate late fit 0.87/0.86 → 0.98/0.95; warble IF
p-p 3.8–5/2 c. Regressions/open: B0 gate −7 envelope NRMSE 0.25 → 0.32 with
best lag −12 ms (output envelope early) — hypothesis: a split group's residual,
which carries the onset's time structure, is translated with the erratic merged
short-frame ω instead of each component's; churn flux +8…+30 % on the clean and
noisy chord (flux ratios within ±0.2, one borderline event); WSL 96 kHz block
32 misses 257/1500 (once per hop: the synchronous analysis in prepareFrame;
gprof: FFT 34 %, renderRegion 15 %, splitRegion 12 %, jointFit 9 %, fitPeaks
5 %). Fix candidates: give each component the residual bins nearest to it
(IFFT only when that residual is significant), and split prepareFrame into two
phases inside the hop (no latency change).
