PITCH - LOW-LATENCY POLYPHONIC PITCH-SHIFT RESEARCH
2026-10-08

This is an executable research checkpoint, not a competitive VST3.
Read Pitch_Shifting_Research.pdf and Pitch_Research_Handoff.txt first.

CONTENTS
papers.md / papers-bibliography.json: primary literature analysis.
open-source.md: source audit and source-based findings.
architecture.md: original proposed design and equations.
forensics/: derived binary metadata, hashes and probe.
benchmarks/: original Compose normal-API benchmark.
prototype/: MIT Ocean NumPy port, tests and synthetic WAVs.
architecture-experiment/: original unity/WOLA delay experiment.
sources.csv: compact source register.
manifest.json: SHA256 of included files, excluding itself.
DECISIONS.txt: durable decisions and evidence boundaries.

REPRODUCE OPEN EXPERIMENTS
Python3 with NumPy/SciPy; C++17 compiler for the latency probe.
Run from the extracted package root:
  python3 prototype/run_experiments.py
  python3 architecture-experiment/architecture-experiment.py
  g++ -std=c++17 -O2 open-source/latency_probe.cpp -o latency_probe
  ./latency_probe
Scripts write results next to themselves. Copy the extracted directory first
to preserve the original measurements.

REPRODUCE COMPOSE
Requires Node24, Python3+NumPy, git and access to public sources. Follow
benchmarks/runtime-findings.md for exact binary URL/hash, host/submodule
revisions and commands. Set WEBCLAP_HOST to your pinned checkout, then:
  node benchmarks/run-compose.mjs /absolute/path/compose-2026-10-01.wclap.wasm
  python3 benchmarks/analyze-compose.py
The host checkout and demo binary must be fetched separately. No proprietary
executables, native demos, disassembly or decompiled listings are bundled.

INTERPRETATION
Vendor claims, source observations, measurements, inferences and hypotheses
are distinct. Ocean is a baseline with demonstrated weaknesses. WOLA scaffold
does no pitch shifting. Synthetic Compose tests do not establish guitar quality
or Neural DSP parity. CPU timings are not native SDK benchmarks.

LICENSES
MIT source copies carry upstream notices (Ocean and Signalsmith Stretch/Linear).
Other fetched reference code is not bundled. Public host access does not imply
a permissive license. Original scripts contain no reconstructed proprietary DSP.

REPORT REBUILD
build_report.py needs NumPy, Matplotlib and ReportLab; it reads benchmark data
and writes deliverables/Pitch_Shifting_Research.pdf. Rendering is separate from
algorithm experiments. Artifact hashes are recorded before upload.
