from pathlib import Path
import json, csv, html, math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image, KeepTogether
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.units import inch

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'deliverables'; OUT.mkdir(exist_ok=True)
SOURCES=[
 ('S01','Signalsmith Compose','Vendor product page','https://compose.signalsmith-audio.co.uk/'),
 ('S02','WebCLAP browser host','Public host source, not the Compose engine','https://github.com/WebCLAP/browser-test-host'),
 ('S03','Compose WASM 2026-10-01','Exact user-supplied binary; analyzed locally','https://cors.signalsmith-audio.co.uk/compose/compose-2026-10-01.wclap.wasm'),
 ('S04','Mauler and Martin, EUSIPCO 2007','Low-delay perfect-reconstruction analysis/synthesis','https://www.eurasip.org/Proceedings/Eusipco/Eusipco2007/Papers/A2L-D02.pdf'),
 ('S05','Juillerat and Hirsbrunner, ICALIP 2010','Ocean; author-uploaded paper','https://www.researchgate.net/publication/261078164_Low_latency_audio_pitch_shifting_in_the_frequency_domain'),
 ('S06','Ocean author errata and source','Equation correction; MIT core in archive','https://pitchtech.ch/Confs/ICALIP2010/Errata.txt'),
 ('S07','Ocean source archive','Downloaded MIT Java reference core','https://pitchtech.ch/Confs/ICALIP2010/PitchShiftOcean.7z'),
 ('S08','Laroche and Dolson, WASPAA 1999','Spectral-region pitch shifting','https://www.ee.columbia.edu/~dpwe/papers/LaroD99-pvoc.pdf'),
 ('S09','Prusa and Holighaus, EUSIPCO 2017','Phase Vocoder Done Right; later arXiv deposit','https://arxiv.org/abs/2202.07382'),
 ('S10','Luff, 2023','The Design of Signalsmith Stretch','https://signalsmith-audio.co.uk/writing/2023/stretch-design/'),
 ('S11','Signalsmith Stretch','MIT C++ implementation; version 1.3.2 inspected','https://github.com/Signalsmith-Audio/signalsmith-stretch'),
 ('S12','Signalsmith Linear','MIT FFT/STFT infrastructure','https://github.com/Signalsmith-Audio/linear'),
 ('S13','Polak and Erkut, DAS-DAGA 2025','STN pitch shifting; 166.1ms reported maximum','https://pub.dega-akustik.de/DAS-DAGA_2025/files/upload/paper/635.pdf'),
 ('S14','STN source','Public research implementation; separate source timing','https://github.com/mariapolak/STN-based-Pitch-Shifting'),
 ('S15','Kraft et al., DAFx 2012','Improved PVSOLA','https://www.dafx.de/paper-archive/2012/papers/dafx12_submission_26.pdf'),
 ('S16','stftPitchShift','MIT asymmetric-window baseline','https://github.com/jurihock/stftPitchShift'),
 ('S17','Rubber Band LiveShifter','Official API; 50ms or more documented','https://www.breakfastquay.com/rubberband/code-doc/classRubberBand_1_1RubberBandLiveShifter.html'),
 ('S18','Eventide filterbank disclosure','US20250193632A1; technical prior art, not Compose attribution','https://patents.google.com/patent/US20250193632A1/en'),
 ('S19','Juillerat et al., 2008','Rollers author companion','https://pitchtech.ch/Confs/ICALIP2008/Rollers.html'),
 ('S20','Neural DSP Misha Mansoor X manual','Transpose range; no Neural binary tested here','https://neuraldsp.com/manual/archetype-misha-mansoor-x'),
]
with (ROOT/'sources.csv').open('w') as f:
 w=csv.writer(f); w.writerow(['id','source','scope','url','retrieved']); w.writerows([(*r,'2026-10-08') for r in SOURCES])

metrics=json.loads((ROOT/'benchmarks/results/analysis.json').read_text())
cases=metrics['cases']
fig,ax=plt.subplots(figsize=(8.4,2.7))
for st,col in [(-12,'#cf7c35'),(0,'#798791'),(12,'#167d96')]:
 a=np.fromfile(ROOT/f'benchmarks/results/impulse_{st}.f32',dtype='<f4')
 t=(np.arange(len(a))-8192)/48
 keep=(t>=0)&(t<=22)
 ax.plot(t[keep],a[keep],lw=.8,label=f'{st:+d} semitones',color=col)
ax.axvline(10,ls='--',color='#222',lw=.8); ax.set(xlabel='Milliseconds after input impulse',ylabel='Amplitude',title='Compose demo: shifted impulse responses at the default 10 ms setting')
ax.legend(frameon=False,ncol=3,fontsize=8); ax.spines[['top','right']].set_visible(False); ax.grid(alpha=.15);fig.tight_layout()
plot=OUT/'Compose_Impulse_Response.png';fig.savefig(plot,dpi=180);plt.close(fig)

styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='TitleX',fontName='Helvetica-Bold',fontSize=26,leading=30,textColor=colors.HexColor('#123a4a'),spaceAfter=14))
styles.add(ParagraphStyle(name='SubX',fontName='Helvetica',fontSize=13,leading=18,textColor=colors.HexColor('#426373'),spaceAfter=14))
styles.add(ParagraphStyle(name='HX',fontName='Helvetica-Bold',fontSize=16,leading=20,textColor=colors.HexColor('#123a4a'),spaceAfter=12))
styles.add(ParagraphStyle(name='BX',fontName='Helvetica',fontSize=10,leading=14,spaceAfter=8))
styles.add(ParagraphStyle(name='SmallX',fontName='Helvetica',fontSize=8,leading=11,spaceAfter=5))
styles.add(ParagraphStyle(name='CodeX',fontName='Courier',fontSize=8.4,leading=12,backColor=colors.HexColor('#edf3f5'),borderPadding=7,spaceAfter=10))
styles.add(ParagraphStyle(name='CellX',fontName='Helvetica',fontSize=8.6,leading=11.6))
story=[]
def p(s,sty='BX'): story.append(Paragraph(s,styles[sty]))
def h(s): p(s,'HX')
def page(): story.append(PageBreak())
def code(s):p(html.escape(s).replace('\n','<br/>'),'CodeX')
def table(rows,widths=None):
 data=[[Paragraph(str(c),styles['CellX']) for c in r] for r in rows]
 t=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dceaf0')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#62818d')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f4f7f8')]),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
 story.append(t);story.append(Spacer(1,10))

p('Pitch shifting<br/>Research and implementation brief','TitleX')
p('Guitar leads, chords, and general instruments<br/>Evidence checkpoint - 8 October 2026','SubX')
p('<b>Decision:</b> pursue an original phase-coherent spectral engine with long past-heavy analysis and short synthesis support. Target 8-10 ms added DSP latency. Treat Ocean and a short-window phase vocoder as baselines, and Compose as a measured commercial reference.')
p('<b>Outcome today:</b> six parallel workstreams completed primary-paper analysis, public-source review, binary inspection, normal-API Compose measurements, an Ocean research port, and an original low-delay reconstruction experiment. This is an executable research package, not a finished competitive VST3 plug-in.')
table([
 ['Evidence class','What is established'],
 ['Measured','Compose default reports 480 samples at 48 kHz; tested impulse peaks occur at that delay. Original unity reconstruction scaffold emits a delayed identity at 383 samples.'],
 ['Source + compiled API','Signalsmith Stretch defaults give 120 ms; cheaper preset gives 140 ms. MIT asymmetric-STFT infrastructure exists.'],
 ['Forensic fact','Public binaries expose spectral controls and complex subband/frequency interfaces. Exact proprietary processing equations are not recovered.'],
 ['Proposed','Coherent region remapping, transient-aware phase guidance, and bounded historical prediction on a fixed-delay front end.'],
 ['Not established','Parity with Neural DSP; blind guitar-chord quality; production CPU deadlines; all-instrument transparency; shipping VST3 integration.']
 ],[100,405])
p('The required comparison is sound quality <i>and</i> playing response. A first nonzero sample, an API latency value, steady-tone pitch accuracy, and a musical attack delay are different measurements. This report keeps them separate.')
p('Read next: measured results (page 2), binary evidence (page 3), proposed engine (pages 5-6), and the experiment roadmap. Full notes, scripts, hashes, licenses, and machine-readable results are in Pitch_Research_Package.zip.','SmallX')

page();h('1. Measurements that change the decision')
p('Local measurements used the exact 2026-10-01 Compose WASM, its normal WCLAP/CLAP interface, 48 kHz, 128-sample blocks, and default pitch-shifter settings except the pitch amount. Tested shifts: -12, -7, -2, 0, +7, +12 semitones. No binary patching was used. [S02-S03]')
table([
 ['Test / configuration','Result','Interpretation'],
 ['Compose API and impulse peak','480 samples / 10.00 ms at every tested shift','Confirmed for this version, input, and configuration.'],
 ['Compose impulse energy centroid','479-518 samples / 9.98-10.78 ms','Shift-dependent spreading remains around the main attack.'],
 ['Compose impulse first -60 dB crossing','121-122 samples / about 2.5 ms','Small pre-peak energy. This is not evidence of a 2.5 ms pitch-shifter.'],
 ['Compose 110 Hz steady sine','Strongest line error below 0.1 cent in last second','Validates this narrow stationary case, not chord/transient quality.'],
 ['Stretch default / cheaper API','120 ms / 140 ms','Measured from compiled public C++ source; distinct from Compose.'],
 ['Original WOLA scaffold','383 samples / 7.979 ms; all 96 impulse phases','Unity reconstruction only. No pitch manipulation implemented here.']
 ],[156,158,191])
story.append(Image(str(plot),width=505,height=162))
p('The synthetic harmonic-chord test places about 95.5-98.9% of steady output spectral energy inside +/-3 Hz bands around expected harmonics at nonzero shifts. That is a descriptive diagnostic, not a perceptual score: bands overlap, amplitude balance can be wrong, and attack damage is excluded. No Neural DSP audio was measured. Runtime CPU timings in raw logs are diagnostic Node/WASM wall times, not native real-time guarantees.','SmallX')

page();h('2. What the public binaries reveal')
p('The WebCLAP repository is a browser host, with an AudioWorklet wrapper and a C++ bridge for loading WCLAP modules. It is not the Compose DSP source. Public source availability alone does not supply an engine license. [S02]')
table([
 ['Artifact','Verified observations'],
 ['Compose WASM, 2026-10-01','1,121,191 bytes; 1,155 defined functions. No name/debug/custom sections observed. WABT 1.0.39 disassembly and pseudocode generation succeeded.'],
 ['WASM identity','SHA-256: ffff817738e0386eb0f8dc44b331422535f4c6fe762252d99dca7be25a0f1dc1'],
 ['Public controls / embedded UI','Latency, analysis period, resolution, iterations, transient controls, and tonality parameters occur in the demo. It bundles several effects; a string does not prove a specific active DSP path.'],
 ['Official Windows demo, 2026-10-06','Native exports expose complex input values, per-band frequency data, nominal-band mapping, output-add operations, callbacks, update rate, and latency. This is a different build from the measured WASM.'],
 ['Bounded native inspection','Input arrays are channel-indexed. Update rate derives from sample rate / period. nominalBand has a nonlinear low-frequency branch and affine high-frequency branch; nominalHz reads stored band frequencies.']
 ],[146,359])
p('<b>Inference:</b> these interfaces are consistent with a complex subband representation that carries frequency metadata and permits coherent relocation of energy. They justify studying subband geometry and phase-preserving synthesis. They do not establish an IIR, constant-Q, STFT, neural, or particular patented implementation.')
p('<b>Unknown:</b> exact analysis kernels, spectral refinement/iteration rules, moved-output semantics, transient decisions, aliasing controls, and numerical tuning. There is no basis to claim that decompilation recovered a maintainable Compose source engine.')
p('The package preserves hashes, derived metadata, scripts and analysis notes. Proprietary executable files and large pseudocode/disassembly dumps are not redistributed. Reproduction scripts obtain the public files separately and check identity. Results from the two dates are explicitly separated.','SmallX')

page();h('3. Primary literature: useful ideas and limits')
table([
 ['Source','Contribution to our research','Limit to retain'],
 ['Mauler & Martin 2007 [S04]','Long analysis with short synthesis can reconstruct unchanged audio at low delay.','Speech-enhancement front end. Spectral modification can break cancellation and add artifacts.'],
 ['Ocean 2010 [S05-S07]','Simple coherent spectral relocation; author code and errata make reproduction practical.','Coarse tuning, modulation and transient duplication are documented tradeoffs.'],
 ['Laroche & Dolson 1999 [S08]','Translate spectral peak neighborhoods coherently.','Unresolved adjacent partials remain difficult.'],
 ['Phase Vocoder Done Right [S09]','Use time and frequency phase relationships, rather than time continuity alone.','Original results do not validate a complete sub-10 ms guitar engine.'],
 ['Signalsmith Stretch design [S10]','Complex neighbor predictions and local peak-shape preservation.','Stretch is a separate implementation; it cannot identify Compose internals.'],
 ['STN 2025 [S13]','Component-aware processing is a useful hypothesis.','Reported maximum delay 166.1 ms; small listening study below its chosen commercial baselines.'],
 ['Improved PVSOLA 2012 [S15]','Selective coherence resets can avoid some global reset problems.','Reduced delay does not imply a 5-10 ms implementation.'],
 ['Eventide disclosure [S18]','Nonuniform analytic subbands with instantaneous-frequency synthesis are an alternative route.','Dispersive delay and unresolved mixtures need measurement. This is technical prior art, not Compose attribution.']
 ],[128,187,190])
p('The current public STN repository has different settings from the paper. Source accounting gives about 103.33 ms at 48 kHz for its default decomposition plus 50 ms tonal stage, subject to the noise-branch delay. It also processes mono and copies the result to stereo. Neither timing figure is evidence for our target. [S14]')
p('A general-purpose processor must handle overlapping partials, inharmonic content, pick noise, and bends. Monophonic pitch estimation or voice-conversion papers cannot by themselves substantiate this capability. The reviewed methods support experiments, not a guarantee that one architecture works equally well on every instrument.')

page();h('4. Proposed engine: the first falsifiable design')
p('<b>Research hypothesis:</b> retain enough recent history to stabilize partial relationships, while producing a short, fresh output segment on a fixed schedule. Use one shared synthesis path. Let transient/tonal confidence guide phase behavior inside that path rather than stacking three full analysis-synthesis engines.')
table([
 ['Module','Initial configuration / behavior'],
 ['Timing and windows','48 kHz; analysis N=2048; synthesis support L=384; hop H=96. Fixed sample schedule D=L-1=383 before host/device buffering.'],
 ['Analysis','Past-heavy complex spectrum; maintain previous frames and linked-channel energy. Add a short recent view only if it demonstrably improves onset confidence.'],
 ['Region map','Estimate continuous partial frequencies and local peak regions. Move a lobe as a coherent neighborhood; do not round each bin independently.'],
 ['Phase solver','Temporal propagation for steady regions; vertical neighborhood constraints for attacks. Use confidence to blend complex predictions.'],
 ['Synthesis','Short support with bounded dual-window coefficients, overlap-add, fixed output queue. Explicit anti-alias treatment near Nyquist.'],
 ['Optional later work','Envelope/formant modes, nonuniform bands, and historical slope prediction after a matched-delay baseline succeeds.']
 ],[120,385])
code('r = 2^(semitones / 12)\nf_target = r * f_estimated\nphi_out[m] = phi_out[m-1] + 2*pi*H*f_target[m]/fs\nY[k] = magnitude[k] * P[k] / max(abs(P[k]), epsilon)')
p('Here P is a confidence-weighted complex phase prediction, not a specified proprietary formula. A minimal peak-region baseline can use the propagated peak phase plus each neighboring bin\'s input-relative phase. A second candidate combines backward time and adjacent-frequency observations. Compare these as separate ablations.')
p('Window construction in the original experiment uses a past-heavy analysis A and a short product window g with constant overlap sum. Define S=g/A only over the newest synthesis support and zero elsewhere. The experiment verifies bounded S and identity reconstruction. It does not show that a modified spectrum retains those properties.')

page();h('5. Where the engineering difficulty remains')
p('<b>Freshness versus delay.</b> The original 2048/384/96 window has an analysis-energy centroid about 686 samples, or 14.29 ms, before frame end. Its output schedule is 7.98 ms, but its spectral evidence is older. After transposition this can smear attacks or retain an old note. This is the central experiment, not a solved problem.')
p('<b>Low chords.</b> A 2048-point FFT at 48 kHz has 23.44 Hz bin spacing; neighboring semitones around low E differ by only about 4.9 Hz. Interpolation can estimate isolated tones between bins, but it does not magically separate arbitrary simultaneous close partials. Use history and cross-harmonic consistency with confidence, without assuming one monophonic fundamental.')
p('<b>Unresolved regions.</b> For two unresolved tones, moving one carrier while preserving its envelope retains the original beat spacing; true transposition requires scaling that spacing too. This can defeat both one-frequency-per-band synthesis and rigid region translation. Track stable regions with confidence and hysteresis, but do not mistake a stable wrong result for success. Low close dyads are a mandatory early falsifier.')
p('<b>Attacks.</b> Detect changes using recent energy and spectral flux; test soft phase reset against vertical phase guidance. Preserve attack timing while shifting its tonal portion. A universal unshifted transient bypass can leak the old pitch, especially on piano and picked guitar.')
p('<b>Stereo.</b> Choose regions and phase reference from linked-channel energy, then preserve measured interchannel phase and level relationships. Test hard pans, decorrelated reverbs and mono downmix. Two independent mono shifters are not enough to guarantee image stability.')
p('<b>Automation.</b> Integrate target frequency continuously and smooth map changes. Parameter steps must not reset all oscillator phases. New window or latency settings are prepared away from the audio callback, then switched with a defined state transition. A crossfade can hide a discontinuity but can introduce temporary beating.')
p('<b>Alternative research branch.</b> A nonuniform complex filterbank with partial-frequency metadata may improve the frequency/latency tradeoff. Its group delay varies by band unless compensated, so measure low-band gated-tone settling rather than only broadband impulse onset. Neither public export geometry nor the Eventide disclosure proves a suitable implementation for this project.')

page();h('6. What to implement next')
table([
 ['Stage','Concrete work','Exit condition'],
 ['A - harness','One offline runner + streaming block adapter, sample-indexed events, deterministic fixtures and latency accounting. Reuse supplied scripts/results as baselines.','Same input and ratios reproduce baseline measurements; no hidden normalization.'],
 ['B - spectral baseline','Original asymmetric front end + simple phase-coherent peak-region transport. Compare with short symmetric processing at matched measured delay.','Pass unity, isolated-tone tuning, nonfinite, and exact timing checks; preserve output level.'],
 ['C - phase and onset','Add neighborhood phase predictions, confidence/hysteresis, short-view onset evidence. One feature per experiment.','Improves blinded attack/chord cases without regressing stable tones or adding delay.'],
 ['D - instrument coverage','Dry guitar, bass, acoustic, piano, bowed strings, synths, voice and percussion. Both directions; large shifts treated separately.','No catastrophic failures; state supported range from evidence.'],
 ['E - C++ / VST3','Port only validated modules. Fixed-size memory, reusable FFT plans, variable host blocks, stereo, automation and offline rendering.','No allocation/locks in process; callback tails within chosen hardware budget.'],
 ['F - competitor gate','Same DI and downstream amp chain against exact Neural DSP version and exact Compose build. Blind, loudness-matched listening plus live play.','Meets predeclared quality and latency criteria per test family, not just averaged score.']
 ],[75,270,160])
p('Initial C++ module boundary: <font face="Courier">prepare(fs, channels, maxBlock)</font>, <font face="Courier">reset()</font>, <font face="Courier">setPitchSemitones(value)</font>, <font face="Courier">process(input, output, n)</font>, and <font face="Courier">latencySamples()</font>. The implementation must own the exact scheduler and event timing; adapting the DSP to a fixed internal hop must not silently add another host block.')
p('Do not optimize into native SIMD or build the product UI before the first pitched low-delay prototype survives attack and chord tests. The current package intentionally exposes failure cases early. No production engine or VST3 binary is delivered in this checkpoint.')

page();h('7. Evaluation contract')
p('The following are proposed engineering gates, not measured achievements. Fix them before comparing variants so that improvements cannot be selected by favorable examples.')
table([
 ['Dimension','Proposed gate / test'],
 ['Latency','Start with <=10 ms added DSP at 48 kHz. Report API delay, impulse peak/centroid, gated-tone envelope lag and frequency settling separately. Include adapters/resamplers.'],
 ['Pitch range','Primary -1/-2/-5/-7 semitones; also +1/+2/+5/+7 and +/-12. Track difficult large shifts separately.'],
 ['Tuning and artifacts','Provisional isolated-sine steady error <1 cent; measure sidebands and modulation independently. This does not score perceived chord pitch.'],
 ['Guitar corpus','Lead bends/vibrato; legato; muted chugs; open and dense jazz chords; close dyads; ringing overlaps; low seven/eight-string notes. Test clean and through identical high gain.'],
 ['Other sources','Bass low notes, piano attacks, acoustic picking, sustained strings, bright synths, voice, and noise/percussion. No instrument-specific tuning in the evaluation split.'],
 ['Listening','Blind randomized A/B ratings on attack, timbre, chord stability and overall preference. Use multiple clips/listeners and document uncertainty. Keep quality alignment and live delay comparison separate.'],
 ['Realtime safety','Preallocate; no I/O, locks or plan construction in callback. Measure worst and percentile callback times at 32/64/128 blocks on target x86/Apple Silicon.'],
 ['Robustness','44.1/48/96 kHz; odd and changing block sizes; silence; denormals; restarts; automation; mono/stereo; bypass transitions.']
 ],[115,390])
p('The user\'s exact Neural DSP plug-in/version and representative dry guitar recordings are still needed for the final parity decision. Their absence did not block literature analysis or synthetic measurements, but it prevents an honest claim that the proposed engine matches the requested reference.')
p('Compare the full quality/latency frontier. A 120 ms library is a useful sound-quality reference, while a 10 ms engine is a playability reference; they are not interchangeable controls. Use gain matching without concealing amplitude-modulation failures.')

page();h('8. Prototype status and reproducibility')
p('<b>Ocean port.</b> The NumPy research implementation ports the author\'s MIT reference core, preserving its notice. For N=512 and H=64, unchanged audio reconstructs at a delay of 448 samples (9.333 ms at 48 kHz). A nonunity deterministic-noise case was cross-checked against the original Java tool within one 16-bit PCM least-significant step. [S07]')
p('The experiment covers 112 isolated-tone/configuration combinations, including synthesis padding m=1,2,4,8. Even m=8 leaves the strongest 82.4069 Hz component unchanged for +/-1 semitone shifts. At 440 Hz / -1 semitone it produces a strongest line near 416.56 Hz versus a 415.30 Hz target. These are strongest-line diagnostics, not perceived pitch scores. Exact results are in prototype/results/tone_metrics.csv. This baseline is not the finished engine.')
p('<b>Original window experiment.</b> N=2048, synthesis support=384, hop=96; maximum overlap-sum error about 2.22e-16; all 96 impulse phases peak at exactly 383 samples. White noise, DC and low tones reconstruct near double-precision rounding error. No spectral modification, instrument recording, CPU deadline, or VST3 behavior was tested by this scaffold.')
p('<b>Compose harness.</b> Original Node host calls the public WASM API. It enumerates parameters, processes deterministic signals and saves raw output plus metadata. Re-running requires fetching the public demo and matching its SHA-256; the executable is not in the deliverable.')
code('python3 prototype/run_experiments.py\npython3 architecture-experiment/architecture-experiment.py\ng++ -std=c++17 -O2 open-source/latency_probe.cpp -o latency_probe\n./latency_probe\n# Compose: see benchmarks/runtime-findings.md for setup')
p('Run these from the extracted package root. Python needs NumPy/SciPy for the Ocean tests, and NumPy for the window test. The compiled latency probe needs a C++17 compiler and its included MIT headers. The Compose runner needs Node, the separately fetched public demo and pinned WebCLAP dependencies.')
p('The handoff lists next steps, existing file identities, versions, and unresolved work. The package manifest records every included artifact\'s SHA-256, enabling future sessions to verify that the evidence and code are unchanged. Original measurements and failed hypotheses should remain in the history rather than being overwritten by a more favorable run.','SmallX')

page();h('9. Source register')
p('Primary references and exact public artifacts. Accessed 2026-10-08. Repository revisions and downloaded-file hashes are recorded in the package. Source URLs describe provenance; they do not imply endorsement or permission to reuse every component.','SmallX')
for ident,title,scope,url in SOURCES[:10]:
 p(f'<b>{ident} - {html.escape(title)}</b><br/>{html.escape(scope)}<br/><link href="{html.escape(url)}" color="#167d96">{html.escape(url)}</link>','SmallX')
page();h('Source register, continued')
for ident,title,scope,url in SOURCES[10:]:
 p(f'<b>{ident} - {html.escape(title)}</b><br/>{html.escape(scope)}<br/><link href="{html.escape(url)}" color="#167d96">{html.escape(url)}</link>','SmallX')
p('License notes: Signalsmith Stretch/Linear, stftPitchShift and the Ocean core provide permissive source foundations with their notices. Rubber Band offers GPL and commercial routes. The inspected STN tree did not identify a top-level license. Compose remains a proprietary reference. A patent disclosure is technical evidence, not a software license; no patent clearance conclusion is made here.','SmallX')

def footer(canvas,doc):
 canvas.saveState();canvas.setFillColor(colors.HexColor('#56717c'));canvas.setFont('Helvetica',8)
 canvas.drawString(45,28,'PITCH / RESEARCH CHECKPOINT / 2026-10-08');canvas.drawRightString(550,28,str(doc.page));canvas.restoreState()
doc=SimpleDocTemplate(str(OUT/'Pitch_Shifting_Research.pdf'),pagesize=(595,842),rightMargin=45,leftMargin=45,topMargin=42,bottomMargin=45,title='Low-Latency Polyphonic Pitch Shifting - Research and Implementation Brief',author='Pitch research project')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
print(OUT/'Pitch_Shifting_Research.pdf')
