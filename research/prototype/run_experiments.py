"""Reproduce Ocean baseline diagnostics. Requires NumPy and SciPy."""
from pathlib import Path
import csv
import json
import platform
import time
import wave
import numpy as np
import scipy
from scipy.signal import hilbert
from ocean_numpy import render

ROOT = Path(__file__).resolve().parent
FS = 48000
N, H = 512, 64
DURATION = 3
SEMITONES = [-12, -5, -1, 0, 1, 5, 12]


def wav(path, data):
    """Signed 16-bit PCM; common fixed scale, never per-file peak normalization."""
    with wave.open(str(path), "wb") as handle:
        handle.setparams((1, 2, FS, 0, "NONE", "not compressed"))
        handle.writeframes((np.clip(data, -1, 1) * 32767).astype("<i2").tobytes())


def dominant_frequency(y):
    nfft = 2 ** int(np.ceil(np.log2(len(y) * 8)))
    magnitude = np.abs(np.fft.rfft(y * np.hanning(len(y)), nfft))
    lo = int(20 * nfft / FS)
    k = np.argmax(magnitude[lo:]) + lo
    if 0 < k < len(magnitude) - 1:
        a, b, c = np.log(np.maximum(magnitude[k-1:k+2], 1e-30))
        fractional = 0.5 * (a-c) / (a-2*b+c)
    else:
        fractional = 0.0
    return float((k + fractional) * FS / nfft)


def tone_metrics(y, target):
    y = y[FS:2*FS]
    measured = dominant_frequency(y)
    envelope = np.abs(hilbert(y))[FS//10:-FS//10]
    # Frequency-specific least-squares sine fit catches pitch error AND AM/FM.
    # The residual is not a perceptual audio-quality or listening-test score.
    t = np.arange(len(y))/FS
    basis = np.column_stack([np.sin(2*np.pi*target*t), np.cos(2*np.pi*target*t)])
    fit = basis @ np.linalg.lstsq(basis, y, rcond=None)[0]
    rms = np.sqrt(np.mean(y*y))
    residual = np.sqrt(np.mean((y-fit)**2))
    return {"target_hz": float(target), "dominant_hz": measured,
            "dominant_pitch_error_cents": float(1200*np.log2(measured/target)),
            "envelope_cv": float(envelope.std()/max(envelope.mean(),1e-30)),
            "target_sine_residual_fraction": float(residual/max(rms,1e-30)),
            "output_rms": float(rms)}


def main():
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "audio").mkdir(exist_ok=True)
    t = np.arange(FS*DURATION) / FS
    rng = np.random.default_rng(20261008)
    noise = rng.normal(0, 0.1, FS)
    tests = []
    for pad in [1, 2, 4, 8]:
        y, engine = render(noise, n=N, hop=H, pad=pad)
        error = y[engine.latency_samples:engine.latency_samples+len(noise)]-noise
        tests.append({"test": "unity_noise_reconstruction", "pad": pad,
                      "max_abs_error": float(np.max(np.abs(error))),
                      "rms_error": float(np.sqrt(np.mean(error**2)))})
        assert np.max(np.abs(error)) < 1e-12
    impulse = np.zeros(FS)
    impulse[FS//4] = 0.5
    impulse_rows = []
    for semitone in SEMITONES:
        y, engine = render(impulse, ratio=2**(semitone/12), n=N, hop=H)
        energy = y*y
        total = energy.sum()
        indices = np.arange(len(y))
        cumulative = np.cumsum(energy)/max(total, 1e-30)
        nonzero = np.flatnonzero(np.abs(y) > max(np.max(np.abs(y))*1e-3,1e-12))
        row = {"semitones": semitone,
               "first_above_minus60db_delay_samples": int(nonzero[0]-FS//4),
               "peak_delay_samples": int(np.argmax(np.abs(y))-FS//4),
               "energy_centroid_delay_samples": float(np.dot(indices,energy)/total-FS//4),
               "central_90pct_energy_width_samples": int(np.searchsorted(cumulative,.95)-np.searchsorted(cumulative,.05))}
        impulse_rows.append(row)
        if semitone == 0:
            assert row["peak_delay_samples"] == N-H
    rows = []
    for frequency in [82.4069, 110.0, 440.0, 1000.0]:
        x = 0.25*np.sin(2*np.pi*frequency*t)
        for pad in [1, 2, 4, 8]:
            for semitone in SEMITONES:
                ratio = 2**(semitone/12)
                start = time.perf_counter()
                y, engine = render(x, ratio, N, H, pad)
                elapsed = time.perf_counter()-start
                row = {"input_hz": frequency, "semitones": semitone, "pad": pad,
                       "python_render_seconds": elapsed,
                       "minimum_demod_denominator": engine.minimum_demod_denominator}
                row.update(tone_metrics(y, frequency*ratio))
                rows.append(row)
                if frequency == 82.4069 and pad in [2, 8] and semitone in [-12,-5,0,5,12]:
                    tag = f"{semitone:+d}".replace("-","down").replace("+","up")
                    wav(ROOT/"audio"/f"low_e_pad{pad}_{tag}st.wav", y)
    # A deliberately synthetic E-minor voicing with plucked harmonic decays.
    # This is not evidence from real guitar recordings or a listening panel.
    frequencies = [82.4069, 123.4708, 164.8138, 195.9977, 246.9417, 329.6276]
    chord = np.zeros_like(t)
    for string, f in enumerate(frequencies):
        local = t-0.01*string
        attack = np.clip(local/.002,0,1)
        for harmonic in range(1,19):
            chord += (attack*np.exp(-np.maximum(local,0)*(0.65+0.1*harmonic))
                      * np.sin(2*np.pi*f*harmonic*local+0.17*string*harmonic)
                      / harmonic**1.4)
    chord *= 0.5/np.max(np.abs(chord))
    wav(ROOT/"audio"/"synthetic_guitar_chord_input.wav",chord)
    chord_rows = []
    for pad in [2, 8]:
        for semitone in SEMITONES:
            y, engine = render(chord, 2**(semitone/12), N, H, pad)
            tag = f"{semitone:+d}".replace("-","down").replace("+","up")
            wav(ROOT/"audio"/f"synthetic_guitar_chord_pad{pad}_{tag}st.wav",y)
            chord_rows.append({"semitones":semitone,"pad":pad,"output_peak":float(np.max(np.abs(y))),
                               "output_rms":float(np.sqrt(np.mean(y*y)))})
    result = {"date":"2026-10-08","python":platform.python_version(),
              "numpy":np.__version__,"scipy":scipy.__version__,
              "sample_rate":FS,"analysis_N":N,"hop_H":H,
              "algorithm_index_delay_samples":N-H,"algorithm_index_delay_ms":1000*(N-H)/FS,
              "tests":tests,"impulse":impulse_rows,"tones":rows,"synthetic_chord":chord_rows,
              "limitations":["No vendor parity test", "No real guitar recordings", "No production CPU timing",
              "No ratio automation", "Mono fixed-ratio prototype", "Tone residual is diagnostic, not perceptual score"]}
    (ROOT/"results"/"results.json").write_text(json.dumps(result,indent=2)+"\n")
    with (ROOT/"results"/"tone_metrics.csv").open("w") as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    with (ROOT/"results"/"impulse_metrics.csv").open("w") as file:
        writer=csv.DictWriter(file,fieldnames=list(impulse_rows[0])); writer.writeheader(); writer.writerows(impulse_rows)
    print(json.dumps({"unity_tests":tests,"impulse":impulse_rows,
                      "selected_tones":[r for r in rows if r["pad"]==2 and r["input_hz"] in [82.4069,440.0]]},indent=2))


if __name__ == "__main__":
    main()
