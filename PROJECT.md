# Pitchwing project scope

Updated: 2026-10-09.

This is the current project scope. The documents in `research/` preserve the
initial research checkpoint; later requirements and decisions are recorded here
and in [DEVELOPMENT.md](DEVELOPMENT.md). Agent working instructions live in
[AGENTS.md](AGENTS.md).

## Product goal

Build a high-quality, low-latency polyphonic pitch-shifting engine for guitar
leads and chords. The deliverable is a reusable engine; VST plug-in development,
packaging, and integration are out of scope. This supersedes the VST3 delivery
plans in the preserved research checkpoint. The quality reference is the user's
Neural DSP Transpose experience; parity has not been established.

The user is developing a VST in a separate project and intends to consume this
engine there. Keep this repository focused on the reusable engine and its
consumer contract; the external plug-in remains outside this project's scope.
The consumer is the sibling `../ShiftKey` project. Its requirements now inform
the engine API and build packaging; changes to the plug-in itself remain in
that separate project. The engine is licensed MIT (2026-10-10, relicensed from GPL-3.0 the same day); ShiftKey
consumes it as an optional, auto-detected dependency and default engine.

Low-register guitar performance and latency are co-primary requirements.
Low-tuned and extended-range guitars must be part of algorithm development and
evaluation from the beginning. A low reported delay or good performance on
standard-register isolated tones is insufficient to meet the project goal.
The first evaluation set must include guitar tunings below F#1, as requested
by the user. The exact minimum supported input frequency is still open.

Bass guitar is a likely additional target and must be considered during
research. Guaranteed bass support and the exact lowest supported tuning remain
open scope decisions; they must follow evidence and agreement with the user.
Retain the broader instrument-support direction from the research checkpoint.

## DSP requirements and evaluation

- Target 8–10 ms added DSP latency initially. Count adapters, lookahead,
  resamplers, and other engine buffering in that budget.
- Preserve polyphonic behavior for low notes, close dyads, dense chords,
  overlapping notes, and changing chords. Evaluate attacks, sustained notes,
  palm mutes, bends, and vibrato in the low register.
- Measure low-band envelope timing and pitch settling alongside declared delay,
  impulse peak/centroid, tuning error, beat spacing, modulation, and gain.
  An early first output sample does not establish acceptable playing response.
- Include low-tuned guitar cases in early synthetic tests and real DI evaluation.
  Use exploratory bass cases to assess feasibility before promising support.
- Treat the existing ±12-semitone research range as the initial investigation
  range. Establish usable range and quality through measurements and listening.
- The live consumer interface must accept fractional shifts through ±49
  semitones: ShiftKey combines ±24 base, ±1 fine, and ±24 curve modulation.
  This control envelope is not a claim of uniform sound quality at its extremes.
- Provide linked stereo planar processing, duplicated-mono input, arbitrary
  block lengths (including one sample), and pitch updates every 1–32 samples.
  Apply controls without an extra smoothing ramp; preserve short authored
  curves rather than sampling only their final value at an analysis boundary.
- Keep declared audio latency constant during pitch changes and within the
  8–10 ms budget at ordinary audio rates. Measure pitch-control response timing
  separately for ShiftKey's curve-clock compensation. Constructors may allocate;
  processing, pitch updates, reset and drain must not allocate or lock.
- Support source embedding and installed CMake consumption with C++17, without
  bringing a VST SDK or downloading dependencies. ShiftKey's target toolchain is
  Windows x64 MSVC 14.29; WSL validation does not validate that target.
- Formant preservation and selectable quality modes are not implemented engine
  capabilities. Consumer controls must not imply otherwise.
- Implement a native C++ baseline now, following the user's acceptance of the
  listening examples and explicit request to begin the engine. Preserve its
  sound for regression comparisons while continuing DSP quality work; this
  supersedes the earlier requirement to resolve every DSP failure before porting.
  Stereo, parameter changes, variable processing blocks, sample rates, and
  callback deadlines remain engine requirements; they do not imply a plug-in
  wrapper or host integration deliverable.

## Development requirements

1. Document all development work in repository files. Record decisions,
   rationale, findings, failed approaches, validation, limitations, and next
   steps as work proceeds. No project-relevant knowledge may remain only in
   conversation context, agent memory, or temporary files. Keep entries concise
   and link to detailed artifacts rather than duplicating them.
2. Use subagents for useful independent research, implementation, and review
   tasks. Give them bounded responsibilities, coordinate file ownership, and
   persist their relevant findings in the repository.
3. Minimize I/O on the project drive. Plan the reads and writes needed before
   running commands; use scoped searches, reuse results, and avoid repeated full
   scans, bulk copies, redundant experiment runs, and unnecessary generated
   artifacts. Coordinate agents so they do not duplicate expensive work.
4. The development environment is WSL, with this checkout on the Windows-mounted
   drive at `/mnt/d/repos/Cpp/Pitchwing`. Prefer Linux-side temporary storage
   such as `/tmp` for disposable builds and scratch outputs when practical.
   Persist useful results and reproducibility information back to the repository
   in a compact form before concluding the work.
5. If a required tool is missing or anything needs installation, ask the user
   first, explaining what is needed and why. Obtain approval before installing
   tools, SDKs, dependencies, or project-local packages, including commands that
   download/install them implicitly. Continue independent work that can use
   already available tools while waiting.

## Current evidence and next work

The project contains research, reproducible baselines, and the first native
engine implementation. The
383-sample reconstruction scaffold proves unity reconstruction and scheduling,
not pitch-shift quality. Ocean is a measured baseline with low-note failures.
There is no validated competitive engine yet.

The first coherent spectral-region transport experiment is implemented in
`experiments/transport/` and compared with a symmetric baseline at matched
scheduled delay. It passes streaming/interface checks but fails low-dyad beat
scaling and shifted DC preservation; see
[the findings](experiments/transport/FINDINGS.md). Retain it as a diagnostic
baseline. The user found all supplied listening comparisons good enough and
preferred `06/minus7` for pick attack, possibly because of the source recording.
The first native milestone implements this baseline's transport design with
an explicit deterministic startup/peak-tie policy, needed because FFT rounding
otherwise changes persistent phase history. Original Python outputs remain
the listening reference; the corrected native output requires new listening.
It does not declare the measured low-dyad/DC failures solved. Its initial scope
is a mono, static-ratio, allocation-free processing core with arbitrary block
sizes, an offline runner, numerical parity checks, and diagnostic WSL timing.
The separate `LiveEngine` milestone adds linked stereo and authored live pitch
changes while preserving this static reference. See
[the ShiftKey requirements](docs/shiftkey-requirements.md).
The implementation and Linux source/installed consumer checks now pass;
[live validation](docs/live-validation.md) records the API, sanitizer caveats,
step-response timing and occasional 96 kHz callback-budget exceedances. Use it
for integration trials; Windows/DAW deadlines and new listening remain open.
Eight user recordings are now catalogued in
[the corpus guide](experiments/corpus/README.md), with reported G#1/F#1 tunings
and separately audited originals. Processing status and real-input coverage
below F#1 remain unconfirmed. The exact Neural DSP plug-in/version and bass
coverage expectations also remain to be established.

See [the research handoff](research/Pitch_Research_Handoff.txt) and
[the original decisions](research/DECISIONS.txt) for the starting evidence.
