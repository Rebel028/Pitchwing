#!/usr/bin/env python3
"""Print the key numbers of one or more evaluate.py result files side by side.

usage: summarize_eval.py result.json [more.json ...]
Rows: tone cents error and gain, dyad spacing (measured vs required), DC mean,
temporal onset lag / late-fit energy. Diagnostic summary, not a quality score.
"""
import json
import sys


def fmt(value, width=8, digits=2):
    if value is None:
        return "n/a".rjust(width)
    return f"{value:{width}.{digits}f}"


def main(paths):
    results = [(path, json.load(open(path))) for path in paths]
    for path, result in results:
        for name, config in result["configurations"].items():
            print(f"=== {path} :: {name}")
            unity = config["unity_delay"]
            print(f"unity delay declared {unity['declared_delay_samples']} peak {unity['measured_peak_delay_samples']} "
                  f"identity err {unity['maximum_delayed_identity_error']:.2e}")
            print("tones: fixture shift  cents_err  gain_dB  fit")
            for tone in config["tones"]:
                fit = tone.get("expected_target_fit", {})
                share = fit.get("fitted_ac_energy_fraction") if isinstance(fit, dict) else None
                print(f"  {tone['fixture']:>4} {tone['semitones']:>5} {fmt(tone['strongest_line_cents_error'])} "
                      f"{fmt(tone['rms_gain_db'])} {fmt(share, 6, 3)}")
            print("dyads: pair shift required_Hz measured_Hz fit_share status")
            for dyad in config["dyads"]:
                lines = dyad["spectral_spacing"]
                targets = dyad["target_frequencies_hz"]
                print(f"  {dyad['fixture']:>6} {dyad['semitones']:>5} {fmt(targets[1] - targets[0])} "
                      f"{fmt(lines.get('observed_spacing_hz'))} "
                      f"{fmt(dyad['expected_target_fit']['fitted_ac_energy_fraction'], 6, 3)} {lines.get('status', '?')}")
            print("dc: shift input mean ac_rms")
            for dc in config["dc"]:
                print(f"  {dc['semitones']:>5} {fmt(dc['input_dc'], 6)} {fmt(dc['output_mean'])} {fmt(dc['output_ac_rms'], 8, 5)}")
            print("temporal: kind shift onset_diff_ms env_lag_ms env_gain env_nrmse late_fit_share")
            for temporal in config["temporal"]:
                late = temporal["late_expected_harmonics_fit"]
                share = late.get("fitted_ac_energy_fraction") if isinstance(late, dict) else None
                print(f"  {temporal['fixture']:>20} {temporal['semitones']:>5} {fmt(temporal['onset_difference_ms'])} "
                      f"{fmt(temporal['envelope_best_lag_ms'])} {fmt(temporal['envelope_gain_fit'], 8, 3)} "
                      f"{fmt(temporal['envelope_normalized_rms_error_after_gain_fit'], 8, 3)} {fmt(share, 8, 3)}")


if __name__ == "__main__":
    main(sys.argv[1:])
