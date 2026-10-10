Ocean baseline: reproducible experiment, 2026-10-08
================================================

Purpose
-------
Establish an independently runnable, low-latency reference and identify a
concrete weakness that a competitive new engine must solve. This is a NumPy
research port of an existing algorithm, not a new competitive algorithm, a
production DSP core, or evidence of parity with Neural DSP or Compose.

Sources and permission
----------------------
Nicolas Juillerat and Beat Hirsbrunner, "Low Latency Audio Pitch Shifting in
the Frequency Domain", ICALIP 2010.
Author publication page: https://pitchtech.ch/
Original reference archive:
https://pitchtech.ch/Confs/ICALIP2010/PitchShiftOcean.7z
Author errata: https://pitchtech.ch/Confs/ICALIP2010/Errata.txt

The author's Java source is MIT licensed, copyright 2018 Nicolas Juillerat.
LICENSE-OCEAN.txt preserves the full license. original-source/PitchShiftOcean.java
is an unchanged source copy for inspection. The third-party JAR and proprietary
framework dependencies are not included in this prototype directory. The paper
is cited rather than copied into this deliverable.

What is implemented
-------------------
1. N-sample periodic Hann analysis and H-sample input/output hops.
2. Positive real-spectrum bins move to round(m*k*ratio).
3. Frame-index phase compensation preserves destination-bin phase advance.
4. An enlarged m*N inverse FFT is cropped to its FIRST N samples.
5. Hann synthesis, overlap-add, and the original interpolated demodulation
   window, including denominator clamp at 0.1.

The compensation sign is adapted for NumPy's negative-exponential forward FFT.
The inverse FFT is multiplied by m to preserve the Java reference scaling.
Python uses float64. Ratio is fixed: the original algorithm's missing ratio
history for changing controls is not silently supplied. No real-time-safety,
CPU deadline, stereo, anti-alias-filter design, or plug-in wrapper is claimed.

Reproduce
---------
Dependencies: Python 3, NumPy, SciPy.
Run from any directory:
  python /path/to/prototype/run_experiments.py

Optional numerical comparison to the author's original Java binary:
  python /path/to/prototype/verify_java.py --jar /path/to/PitchShiftOcean.jar
Optional --java /path/to/java and --java-lib /path/to/jvm/lib select a JVM.

Files
-----
ocean_numpy.py             MIT-reference algorithm port.
run_experiments.py         Deterministic synthetic tests and WAV generation.
verify_java.py             Independent original-executable comparison.
results/results.json      Complete configuration, tone/impulse results.
results/tone_metrics.csv   Four tones x seven shifts x four synthesis pad sizes.
results/impulse_metrics.csv One impulse alignment, seven ratios, pad=2.
results/java_equivalence.json Original Java comparison, three configurations.
audio/*.wav               Synthetic listening examples, mono PCM16/48kHz.

Configuration and measured observations
---------------------------------------
N=512, H=64, Fs=48000. Analysis history is 10.667ms. The reference's nominal
input/output index delay N-H is 448 samples = 9.333ms; unity impulse measures
exactly that. Host buffering, converters, and audio callback scheduling are
not measured. Non-unity impulse peaks/centroids vary with ratio and alignment;
the unity delay is not a universal statement about perceived attack timing.
The recorded impulse uses input sample 12000, not an exhaustive phase sweep.

Unity reconstruction on seeded white noise: all tested m=1,2,4,8 produce
max sample error below 1e-12 (double precision, full zero drain).

The port matches the author's compiled Java executable for seeded noise at
(+5st,m2), (-5st,m4), (+1st,m8): maximum difference about 3.052e-5, approximately
one PCM16 output step; correlations exceed 0.99999995. This is numerical
agreement with the available binary, not proof of a mathematical specification.

Four pure tones 82.4069,110,440,1000Hz are shifted by -12,-5,-1,0,+1,+5,+12
semitones with m=1,2,4,8. m=4 and m=8 include the paper's recommended small-N
synthesis-padding range. Measurement uses the interior second of a 3s render.
The strongest spectral line is NOT a measure of perceived pitch for a complex
signal, and the sine-fit residual is NOT a perceptual quality score.

Examples with m=8 (4096-point synthesis, still 512-sample analysis):
  Input82.4069Hz, -1st: target77.7818Hz, strongest82.4069Hz (100 cents high).
  Input82.4069Hz, +1st: target87.3071Hz, strongest82.4069Hz (100 cents low).
  Input82.4069Hz, -5st: target61.7354Hz, strongest58.9694Hz (~79 cents low).
  Input440Hz, -1st: target415.3047Hz, strongest416.5625Hz (~5.2 cents high).
  Input440Hz, +5st: target587.3295Hz, strongest592.3438Hz (~14.7 cents high).
Consult CSV/JSON for exact measured values and envelope modulation statistics.
The finite-record Hilbert-envelope estimate has a small nonzero floor even at
unity for noninteger-period tones; it must not be overinterpreted near zero.

Why this occurs / next research step
-----------------------------------
Moving a whole analysis bin by b/m-k shifts its contents by approximately
(b/m-k)*Fs/N. The local sinusoid's frequency offset inside that bin is not
generally multiplied by the pitch ratio. A short analysis window cannot resolve
nearby low partials, and larger synthesis padding does not lengthen observation.
Small shifts can therefore leave the strongest low-frequency component in place.
The original Java source explicitly warns that the demodulation correction is
only probabilistically accurate and pure tones/low frequencies can be poor.

This does not establish the quality of the method on rich guitar chords. The
provided plucked six-note synthetic chord is a listening diagnostic only. A
serious next experiment should test continuous-frequency estimates, coherent
peak/region transport, transient protection, and longer trailing analysis with
short synthesis support, against real clean DI leads/chords and a vendor oracle.
Retain this implementation as a reproducible low-latency control condition.

Audio notes
-----------
Filenames include pad2 or pad8 and semitone direction. Chord input is a
deliberately synthetic E-minor six-string voicing with harmonic decays and 10ms
staggered onsets. No recorded instrument or commercial engine output is present.
All output uses a common fixed scale; there is no per-file loudness normalization.
No DC/audio clipping treatment is added. WAV duration includes the drained tail.
