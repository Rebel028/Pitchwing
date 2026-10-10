#!/usr/bin/env python3
"""Bounded synthetic diagnostics; no audio files or implicit result writes.

Run with the separately approved NumPy environment, for example:
  /tmp/pitchwing-env/bin/python -B experiments/transport/evaluate.py --quick
"""

import argparse
import hashlib
import json
import math
import platform
import sys
import time
from pathlib import Path

import numpy as np

try:
    from .engine import TransportEngine
except ImportError:
    from engine import TransportEngine


SAMPLE_RATE = 48000
NOTES = {"B0": 30.867706, "C1": 32.703196, "E1": 41.203445,
         "F1": 43.653529, "F#1": 46.249303, "E2": 82.406889,
         "A4": 440.0}
CONFIGURATIONS = {
    "asymmetric": {"analysis_size": 2048, "synthesis_size": 384,
                   "hop": 96, "window": "asymmetric"},
    "symmetric": {"analysis_size": 384, "synthesis_size": 384,
                  "hop": 96, "window": "symmetric"},
}


def db(value):
    """A zero ratio has no finite dB value; JSON null represents it."""
    return float(20.0 * math.log10(value)) if value > 0 else None


def rms(samples):
    return float(np.sqrt(np.mean(np.square(samples))))


def fit_lines(samples, frequencies, sample_rate=SAMPLE_RATE):
    """Joint sine/cosine fit at known frequencies, with a separate DC term."""
    clock = np.arange(len(samples), dtype=float) / sample_rate
    columns = [np.ones(len(samples))]
    for frequency in frequencies:
        angle = 2.0 * np.pi * frequency * clock
        columns.extend((np.sin(angle), np.cos(angle)))
    matrix = np.column_stack(columns)
    coefficients, _, _, singular_values = np.linalg.lstsq(matrix, samples, rcond=None)
    fitted = matrix @ coefficients
    residual_rms = rms(samples - fitted)
    centered_rms = rms(samples - float(np.mean(samples)))
    energy_fraction = (1.0 - (residual_rms / centered_rms) ** 2
                       if centered_rms > 1e-14 else None)
    return {
        "frequencies_hz": [float(f) for f in frequencies],
        "amplitudes": [float(np.hypot(coefficients[1 + 2 * i],
                                     coefficients[2 + 2 * i]))
                       for i in range(len(frequencies))],
        "dc": float(coefficients[0]),
        "fitted_ac_energy_fraction": (float(np.clip(energy_fraction, 0.0, 1.0))
                                      if energy_fraction is not None else None),
        "residual_rms": residual_rms,
        "residual_to_ac_rms_db": db(residual_rms / centered_rms)
        if centered_rms > 1e-14 else None,
        "design_condition_number": float(singular_values[0] / singular_values[-1]),
    }


def spectrum(samples, sample_rate=SAMPLE_RATE):
    size = 1 << int(math.ceil(math.log2(max(2, len(samples) * 4))))
    magnitude = np.abs(np.fft.rfft((samples - np.mean(samples))
                                 * np.hanning(len(samples)), n=size))
    return np.fft.rfftfreq(size, 1.0 / sample_rate), magnitude


def interpolate_peak(index, frequencies, magnitude):
    """Log-magnitude parabola refines a local peak, not spectral resolution."""
    if index <= 0 or index >= len(magnitude) - 1:
        return float(frequencies[index])
    left, center, right = np.log(np.maximum(magnitude[index - 1:index + 2], 1e-300))
    curvature = left - 2.0 * center + right
    offset = 0.5 * (left - right) / curvature if abs(curvature) > 1e-15 else 0.0
    return float(frequencies[index] + np.clip(offset, -0.5, 0.5)
                 * (frequencies[1] - frequencies[0]))


def strongest_line(samples):
    if rms(samples - np.mean(samples)) <= 1e-14:
        return None
    frequencies, magnitude = spectrum(samples)
    index = int(np.argmax(magnitude[1:])) + 1
    return interpolate_peak(index, frequencies, magnitude)


def observed_dyad_lines(samples, targets):
    """Reject adjacent leakage bins and weak/overlapping peak pairs.

    Two resolved spectral lines still need not correspond to two source notes:
    modulation sidebands can pass this diagnostic. See METRICS.md.
    """
    duration = len(samples) / SAMPLE_RATE
    minimum_separation = 2.0 / duration
    expected_spacing = float(targets[1] - targets[0])
    result = {
        "status": "unresolved",
        "analysis_duration_s": duration,
        "minimum_peak_separation_hz": minimum_separation,
        "target_spacing_hz": expected_spacing,
        "observed_lines_hz": None,
        "observed_spacing_hz": None,
        "spacing_error_hz": None,
    }
    if rms(samples - np.mean(samples)) <= 1e-14:
        result["reason"] = "silent output"
        return result
    if expected_spacing < minimum_separation:
        result["reason"] = "target pair is below the diagnostic resolution limit"
        return result
    frequencies, magnitude = spectrum(samples)
    margin = max(3.0 * expected_spacing, 4.0 / duration)
    low = max(1.0 / duration, targets[0] - margin)
    high = targets[1] + margin
    result["search_band_hz"] = [float(low), float(high)]
    maxima = np.flatnonzero((magnitude[1:-1] > magnitude[:-2])
                           & (magnitude[1:-1] >= magnitude[2:])) + 1
    maxima = maxima[(frequencies[maxima] >= low) & (frequencies[maxima] <= high)]
    maxima = maxima[np.argsort(magnitude[maxima])[::-1]]
    if len(maxima) < 2:
        result["reason"] = "fewer than two local maxima near target frequencies"
        return result
    strongest = int(maxima[0])
    # A Hann sidelobe of one clean tone is about -31 dB; require -24 dB or louder.
    candidates = [int(i) for i in maxima[1:]
                  if abs(frequencies[i] - frequencies[strongest]) >= minimum_separation
                  and magnitude[i] >= magnitude[strongest] * 10.0 ** (-24.0 / 20.0)]
    if not candidates:
        result["reason"] = "no separated second peak within 24 dB of the strongest"
        return result
    second = candidates[0]
    left, right = sorted((strongest, second))
    valley_ratio = float(np.min(magnitude[left:right + 1])
                         / min(magnitude[left], magnitude[right]))
    result["valley_to_weaker_peak_ratio"] = valley_ratio
    if valley_ratio > 0.8:
        result["reason"] = "candidate peaks lack a 20-percent intervening valley"
        return result
    observed = sorted(interpolate_peak(i, frequencies, magnitude)
                      for i in (strongest, second))
    result.update({"status": "two_resolved_spectral_lines",
                   "observed_lines_hz": observed,
                   "observed_spacing_hz": observed[1] - observed[0],
                   "spacing_error_hz": observed[1] - observed[0] - expected_spacing})
    return result


NATIVE_TOOL = None  # set by --native: path to pitchwing_live_render


def render_native(samples, semitones):
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory(prefix="pitchwing-eval-") as scratch:
        source = Path(scratch) / "in.f64"
        sink = Path(scratch) / "out.f64"
        np.asarray(samples, dtype=np.float64).tofile(source)
        completed = subprocess.run([NATIVE_TOOL, str(source), str(sink), str(SAMPLE_RATE),
                                    repr(float(semitones)), "32"], capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError("native render failed: " + completed.stderr)
        delay = int(completed.stderr.strip().rsplit("latency", 1)[1])
        return np.fromfile(sink), delay


def render_aligned(samples, config, semitones):
    if NATIVE_TOOL is not None:
        output, delay = render_native(samples, semitones)
    else:
        engine = TransportEngine(sample_rate=SAMPLE_RATE, semitones=semitones, **config)
        output = np.concatenate((engine.process(samples), engine.flush()))
        delay = engine.latency_samples
    if len(output) < len(samples) + delay:
        raise RuntimeError("engine flush did not expose the complete delayed signal")
    if not np.all(np.isfinite(output)):
        raise RuntimeError("engine produced nonfinite output")
    return output[delay:], delay


def tone_case(name, semitones, config, duration):
    frequency = NOTES[name]
    ratio = 2.0 ** (semitones / 12.0)
    clock = np.arange(round(duration * SAMPLE_RATE)) / SAMPLE_RATE
    source = 0.3 * np.sin(2.0 * np.pi * frequency * clock + 0.31)
    target = 0.3 * np.sin(2.0 * np.pi * frequency * ratio * clock + 0.31)
    output, delay = render_aligned(source, config, semitones)
    start = round(0.35 * SAMPLE_RATE)
    stop = len(source) - round(0.05 * SAMPLE_RATE)
    steady = output[start:stop]
    peak = strongest_line(steady)
    return {
        "fixture": name, "semitones": semitones, "input_hz": frequency,
        "target_hz": frequency * ratio, "declared_delay_samples": delay,
        "steady_interval_s": [start / SAMPLE_RATE, stop / SAMPLE_RATE],
        "strongest_line_hz": peak,
        "strongest_line_cents_error": 1200.0 * math.log2(peak / (frequency * ratio))
        if peak is not None and peak > 0 else None,
        "rms_gain_db": db(rms(steady) / rms(target[start:stop])),
        "expected_target_fit": fit_lines(steady, [frequency * ratio]),
    }


def dyad_case(names, semitones, config):
    duration = 4.0
    frequencies = [NOTES[name] for name in names]
    ratio = 2.0 ** (semitones / 12.0)
    clock = np.arange(round(duration * SAMPLE_RATE)) / SAMPLE_RATE
    source = sum(0.2 * np.sin(2.0 * np.pi * f * clock + p)
                 for f, p in zip(frequencies, (0.19, 0.71)))
    targets = [f * ratio for f in frequencies]
    output, delay = render_aligned(source, config, semitones)
    start, stop = round(0.45 * SAMPLE_RATE), round(3.95 * SAMPLE_RATE)
    steady = output[start:stop]
    return {
        "fixture": "/".join(names), "semitones": semitones,
        "input_frequencies_hz": frequencies, "target_frequencies_hz": targets,
        "declared_delay_samples": delay,
        "steady_interval_s": [start / SAMPLE_RATE, stop / SAMPLE_RATE],
        "expected_target_fit": fit_lines(steady, targets),
        "spectral_spacing": observed_dyad_lines(steady, targets),
    }


def gate(clock, start, end, attack=0.005, release=0.015):
    envelope = np.zeros(len(clock))
    active = (clock >= start) & (clock < end)
    envelope[active] = 1.0
    rising = active & (clock < start + attack)
    falling = active & (clock > end - release)
    envelope[rising] = 0.5 - 0.5 * np.cos(np.pi * (clock[rising] - start) / attack)
    envelope[falling] = 0.5 - 0.5 * np.cos(np.pi * (end - clock[falling]) / release)
    return envelope


def harmonic_sound(clock, frequencies, ratio):
    return sum(np.sin(2 * np.pi * f * harmonic * ratio * clock
                      + 0.17 * harmonic + 0.23 * voice) / harmonic ** 1.3
               for voice, f in enumerate(frequencies) for harmonic in range(1, 9))


def temporal_fixture(kind, ratio):
    clock = np.arange(round(1.5 * SAMPLE_RATE)) / SAMPLE_RATE
    if kind == "B0_harmonic_gate":
        envelope = gate(clock, 0.15, 0.75)
        source = envelope * harmonic_sound(clock, [NOTES["B0"]], 1.0)
        target = envelope * harmonic_sound(clock, [NOTES["B0"]], ratio)
        events = [{"name": "onset", "input_time_s": 0.15},
                  {"name": "release_end", "input_time_s": 0.75}]
        late_frequencies = [NOTES["B0"] * h * ratio for h in range(1, 9)]
        late_interval = (0.4, 0.65)
    else:
        first = [NOTES["B0"], NOTES["F#1"], 2 * NOTES["B0"]]
        second = [NOTES["E1"], 2 * NOTES["B0"], NOTES["E2"]]
        # Complementary raised-cosine fades over 0.65--0.67 s.
        old_envelope = gate(clock, 0.15, 0.67, release=0.020)
        new_envelope = gate(clock, 0.65, 1.25, attack=0.020)
        source = (old_envelope * harmonic_sound(clock, first, 1.0)
                  + new_envelope * harmonic_sound(clock, second, 1.0))
        target = (old_envelope * harmonic_sound(clock, first, ratio)
                  + new_envelope * harmonic_sound(clock, second, ratio))
        events = [{"name": "onset", "input_time_s": 0.15},
                  {"name": "chord_crossfade_start", "input_time_s": 0.65},
                  {"name": "chord_crossfade_end", "input_time_s": 0.67},
                  {"name": "release_end", "input_time_s": 1.25}]
        # These decimal note constants make equal harmonics differ slightly.
        # Merge lines within 0.001 Hz to avoid an artificial ill-conditioned fit.
        late_frequencies = []
        for f in sorted(f * h * ratio for f in second for h in range(1, 9)):
            if not late_frequencies or f - late_frequencies[-1] > 0.001:
                late_frequencies.append(f)
        late_interval = (0.95, 1.20)
    scale = 0.5 / np.max(np.abs(source))
    return source * scale, target * scale, events, late_frequencies, late_interval


def moving_rms(samples):
    half_width = round(0.010 * SAMPLE_RATE)
    width = 2 * half_width + 1
    padded = np.pad(np.square(samples), (half_width, half_width))
    sums = np.concatenate(([0.0], np.cumsum(padded)))
    return np.sqrt(np.maximum(0.0, (sums[width:] - sums[:-width]) / width))


def first_crossing(envelope, threshold):
    indices = np.flatnonzero(envelope >= threshold)
    return float(indices[0] / SAMPLE_RATE) if len(indices) else None


def energy_quantiles(samples):
    energy = np.cumsum(np.square(samples))
    if not len(energy) or energy[-1] <= 1e-24:
        return [None, None, None]
    return [float(np.searchsorted(energy, q * energy[-1]) / SAMPLE_RATE)
            for q in (0.1, 0.5, 0.9)]


def temporal_case(kind, semitones, config):
    source, target, events, late_frequencies, late_interval = temporal_fixture(
        kind, 2.0 ** (semitones / 12.0))
    output, delay = render_aligned(source, config, semitones)
    target = np.pad(target, (0, len(output) - len(target)))
    out_envelope, target_envelope = moving_rms(output), moving_rms(target)
    threshold = 0.1 * float(np.max(target_envelope))
    out_onset = first_crossing(out_envelope, threshold)
    target_onset = first_crossing(target_envelope, threshold)
    # At 1 ms spacing, cross-correlation is small and bounded in memory/CPU.
    stride = SAMPLE_RATE // 1000
    correlation = np.correlate(out_envelope[::stride], target_envelope[::stride], "full")
    lags = np.arange(-len(target_envelope[::stride]) + 1, len(out_envelope[::stride]))
    selected = np.abs(lags) <= 100
    best_lag = int(lags[selected][np.argmax(correlation[selected])])
    gain = float(np.dot(out_envelope, target_envelope)
                 / np.dot(target_envelope, target_envelope))
    envelope_error = rms(out_envelope - gain * target_envelope) / rms(target_envelope)
    start, stop = [round(value * SAMPLE_RATE) for value in late_interval]
    last_release = events[-1]["input_time_s"]
    tail_start = round((last_release + 0.05) * SAMPLE_RATE)
    output_energy = float(np.dot(output, output))
    return {
        "fixture": kind, "semitones": semitones,
        "declared_delay_samples": delay, "events": events,
        "onset_target_aligned_s": target_onset, "onset_output_aligned_s": out_onset,
        "onset_difference_ms": 1000.0 * (out_onset - target_onset)
        if out_onset is not None and target_onset is not None else None,
        "onset_total_delay_ms": delay * 1000.0 / SAMPLE_RATE
        + 1000.0 * (out_onset - target_onset)
        if out_onset is not None and target_onset is not None else None,
        "envelope_best_lag_ms": best_lag,
        "envelope_lag_at_search_boundary": abs(best_lag) == 100,
        "envelope_gain_fit": gain,
        "envelope_normalized_rms_error_after_gain_fit": envelope_error,
        "target_energy_quantile_times_s": energy_quantiles(target),
        "output_energy_quantile_times_s": energy_quantiles(output),
        "energy_fraction_after_release_plus_50ms":
        float(np.dot(output[tail_start:], output[tail_start:])) / output_energy
        if output_energy > 1e-24 else None,
        "late_steady_interval_s": list(late_interval),
        "late_expected_harmonics_fit": fit_lines(output[start:stop], late_frequencies),
    }


def unity_delay_case(config):
    source = np.zeros(round(0.2 * SAMPLE_RATE))
    source_index = round(0.08 * SAMPLE_RATE)
    source[source_index] = 1.0
    if NATIVE_TOOL is not None:
        output, latency = render_native(source, 0.0)
    else:
        engine = TransportEngine(sample_rate=SAMPLE_RATE, semitones=0.0, **config)
        output = np.concatenate((engine.process(source), engine.flush()))
        latency = engine.latency_samples
    peak = int(np.argmax(np.abs(output)))
    energy = np.square(output)
    active = np.flatnonzero(np.abs(output) > 1e-9)
    reference = np.zeros(len(output))
    reference[source_index + latency] = 1.0
    return {
        "declared_delay_samples": latency,
        "measured_peak_delay_samples": peak - source_index,
        "measured_energy_centroid_delay_samples":
        float(np.dot(np.arange(len(output)), energy) / np.sum(energy) - source_index),
        "first_sample_above_1e_minus_9_delay_samples": int(active[0] - source_index)
        if len(active) else None,
        "maximum_delayed_identity_error": float(np.max(np.abs(output - reference))),
    }


def dc_case(semitones, config):
    """A retained DFT bin zero is not a guarantee of constant-signal preservation."""
    source = np.full(SAMPLE_RATE, 0.2)
    output, delay = render_aligned(source, config, semitones)
    steady = output[24000:47000]
    return {
        "semitones": semitones, "input_dc": 0.2,
        "declared_delay_samples": delay,
        "steady_interval_samples": [24000, 47000],
        "output_mean": float(np.mean(steady)),
        "output_ac_rms": float(np.std(steady)),
        "maximum_constant_preservation_error": float(np.max(np.abs(steady - 0.2))),
    }


def evaluate(quick=False):
    started = time.monotonic()
    tones = ["B0", "E1", "F#1", "E2"] if quick else ["B0", "E1", "F#1", "E2", "A4"]
    shifts = [-7, 0, 7] if quick else [-7, -1, 0, 1, 7]
    dyads = [("B0", "C1")] if quick else [("B0", "C1"), ("E1", "F1")]
    tone_duration = 1.0 if quick else 1.5
    result = {
        "schema_version": 1,
        "purpose": "synthetic DSP diagnostics; NOT a perceptual or production quality score",
        "environment": {"python": sys.version.split()[0], "numpy": np.__version__,
                        "platform": platform.platform(), "execution_context":
                        "WSL research run; not target-native real-time performance"},
        "source_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("engine.py", "evaluate.py")
        },
        "sample_rate": SAMPLE_RATE, "quick": quick,
        "fixture_metadata": {
            "tone_duration_s": tone_duration, "tone_names": tones, "tone_semitones": shifts,
            "dyad_duration_s": 4.0, "dyad_pairs": [list(pair) for pair in dyads],
            "dyad_and_temporal_semitones": [-7, 0, 7],
            "temporal_duration_s": 1.5, "temporal_harmonics_per_voice": 8,
            "temporal_harmonic_amplitude": "1 / harmonic**1.3",
            "target_definition": "frequency ratios scale; amplitude envelope event times stay fixed",
            "rms_envelope_window_samples": 961, "rms_envelope_centered": True,
            "notes_hz": NOTES,
        },
        "configurations": {},
        "limitations": [
            "B0 and E1 are engineering stress cases, not a supported tuning guarantee.",
            "Strongest FFT line is not perceived pitch; all signals here are synthetic.",
            "Resolved dyad spectral lines may be modulation sidebands, not two preserved notes.",
            "20 ms RMS smoothing and carrier phase limit envelope timing interpretation.",
            "No real DI, listening, stereo, automation, or native deadline validation.",
        ],
    }
    configurations = {"live_native": {"tool": NATIVE_TOOL}} if NATIVE_TOOL else CONFIGURATIONS
    for name, config in configurations.items():
        result["configurations"][name] = {
            "engine_parameters": config,
            "unity_delay": unity_delay_case(config),
            "dc": [dc_case(shift, config) for shift in (-7, 0, 7)],
            "tones": [tone_case(note, shift, config, tone_duration)
                      for note in tones for shift in shifts],
            "dyads": [dyad_case(pair, shift, config)
                      for pair in dyads for shift in (-7, 0, 7)],
            "temporal": [temporal_case(kind, shift, config)
                         for kind in ("B0_harmonic_gate", "low_chord_crossfade")
                         for shift in (-7, 0, 7)],
        }
    result["diagnostic_wall_time_seconds"] = time.monotonic() - started
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="smaller tone/dyad matrix; retains low notes")
    parser.add_argument("--output", type=Path, help="explicit new JSON path; default prints to stdout")
    parser.add_argument("--native", type=Path, help="render through this pitchwing_live_render binary instead of the Python engine")
    args = parser.parse_args()
    if args.native is not None:
        global NATIVE_TOOL
        NATIVE_TOOL = str(args.native.resolve())
    if args.output is not None and args.output.exists():
        parser.error("output already exists; choose a new path to preserve previous evidence")
    result = evaluate(quick=args.quick)
    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        # Exclusive creation also protects against a writer arriving during evaluation.
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
        print("Wrote synthetic diagnostic results to {}".format(args.output))


if __name__ == "__main__":
    main()
