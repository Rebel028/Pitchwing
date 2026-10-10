# Pitchwing working instructions

Read [PROJECT.md](PROJECT.md) and the relevant recent entries in
[DEVELOPMENT.md](DEVELOPMENT.md) before starting work. Read research documents
selectively as needed. Current user instructions and recorded scope additions
take precedence over older research plans.

- Treat low-register polyphonic guitar performance as a primary requirement
  alongside the 8–10 ms DSP latency target. Bass is a likely extension under
  investigation, not an established supported range.
- Develop only the reusable pitch-shifting engine. VST plug-in development,
  packaging, and integration are out of scope, superseding older VST3 plans in
  `research/`. The user has requested native C++ implementation now; preserve
  the accepted listening baseline and track unresolved DSP defects alongside
  the port. Earlier instructions to defer all native work are superseded.
- Document every development task, including documentation-only changes. Update
  `DEVELOPMENT.md` as work proceeds with the purpose, changes, decisions and
  rationale, findings (including negative results), validation and limitations,
  and remaining work. Link detailed evidence. Before a handoff or final reply,
  persist relevant findings from the main agent and subagents; nothing needed
  to resume the project may exist only in context or temporary storage.
- Use subagents when useful independent work can run in parallel. Assign bounded
  tasks and explicit file ownership for edits. Tell editing agents they share
  the workspace and must accommodate others' changes. Avoid redundant reads,
  experiments, and builds across agents.
- Minimize I/O on `/mnt/d`. Scope searches and checks to the task, batch relevant
  reads, and reuse existing results. Avoid broad recursive scans, full corpus
  copies, repeated hashing, unnecessary report rebuilds, and large generated
  outputs unless the task requires them. Consider expected I/O before launching
  experiments or parallel workers.
- This environment is WSL. Prefer Linux-side scratch/build locations such as
  `/tmp` where practical; save compact durable evidence in the repository. Do
  not treat a WSL benchmark as a target-native real-time performance result.
- Ask the user first if a required tool is missing or an installation is needed.
  Explain the need and obtain approval before installing system tools, SDKs,
  dependencies, or project-local packages. This includes implicit downloads or
  installs by runners and package managers. Use available tools for independent
  work while awaiting an answer.
- Preserve the imported `research/` measurements and provenance. Put new runs
  in separate output locations and document their configuration and results.
  Do not overwrite evidence or rerun scripts that write into the checkpoint
  without first arranging separate outputs. Preserve failed cases as evidence.

- For any technical prose in `docs/` or `README.md`, load the technical-writing
  skill first: `npx skills use "https://github.com/riekelt/technical-writer"
  --skill "technical-writing"` and follow its hard rules (conclusion first, no
  em or en dashes, one fact one home, every claim traceable, sentence-case
  headings). Dated notes in `docs/quality/` are historical records: do not
  rewrite their wording. Formulas use GitHub LaTeX (`$...$`, `$$...$$`).

Scope changes belong in `PROJECT.md`; the development record belongs in
`DEVELOPMENT.md` or linked task-specific artifacts. Update this file when working
rules change.
