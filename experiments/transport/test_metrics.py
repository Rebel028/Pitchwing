"""Analytic checks of diagnostic estimators; no transport-engine rendering."""

import json
import math
import unittest

import numpy as np

from evaluate import (SAMPLE_RATE, fit_lines, observed_dyad_lines,
                      strongest_line, temporal_fixture)


class SyntheticMetricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse this small in-memory fixture across the spectral checks.
        cls.clock = np.arange(round(3.5 * SAMPLE_RATE)) / SAMPLE_RATE
        cls.frequencies = (30.867706, 32.703196)  # B0 / C1
        cls.tone = 0.2 * np.sin(2 * np.pi * cls.frequencies[0] * cls.clock + 0.2)

    def test_known_b0_frequency_and_amplitude(self):
        measured = strongest_line(self.tone)
        cents_error = 1200 * math.log2(measured / self.frequencies[0])
        self.assertLess(abs(cents_error), 0.02)
        fit = fit_lines(self.tone, [self.frequencies[0]])
        self.assertGreater(fit["fitted_ac_energy_fraction"], 1 - 1e-12)
        self.assertAlmostEqual(fit["amplitudes"][0], 0.2, places=12)
        self.assertLess(fit["residual_rms"], 1e-12)

    def test_known_close_dyad_spacing(self):
        samples = self.tone + 0.2 * np.sin(
            2 * np.pi * self.frequencies[1] * self.clock + 0.7)
        measured = observed_dyad_lines(samples, self.frequencies)
        self.assertEqual(measured["status"], "two_resolved_spectral_lines")
        self.assertLess(abs(measured["spacing_error_hz"]), 0.01)
        np.testing.assert_allclose(measured["observed_lines_hz"], self.frequencies,
                                   atol=0.01, rtol=0)

    def test_single_tone_leakage_is_not_reported_as_two_notes(self):
        measured = observed_dyad_lines(self.tone, self.frequencies)
        self.assertEqual(measured["status"], "unresolved")
        self.assertIsNone(measured["observed_lines_hz"])
        self.assertIsNone(measured["observed_spacing_hz"])
        self.assertIsNone(measured["spacing_error_hz"])

    def test_silence_uses_finite_values_or_json_null(self):
        samples = np.zeros(100)
        fit = fit_lines(samples, [self.frequencies[0]])
        lines = observed_dyad_lines(samples, self.frequencies)
        self.assertIsNone(strongest_line(samples))
        self.assertIsNone(fit["fitted_ac_energy_fraction"])
        self.assertIsNone(fit["residual_to_ac_rms_db"])
        self.assertEqual(fit["residual_rms"], 0)
        self.assertEqual(lines["status"], "unresolved")
        # Nonfinite floats cause ValueError, including those in nested objects.
        encoded = json.dumps({"fit": fit, "lines": lines}, allow_nan=False)
        self.assertIn("null", encoded)
        self.assertEqual(json.loads(encoded)["fit"]["amplitudes"], [0.0])

    def test_ideal_chord_target_has_an_accurate_combined_fit(self):
        for semitones in (-7, 0, 7):
            with self.subTest(semitones=semitones):
                _, target, _, frequencies, interval = temporal_fixture(
                    "low_chord_crossfade", 2 ** (semitones / 12))
                start, stop = [round(value * SAMPLE_RATE) for value in interval]
                fitted = fit_lines(target[start:stop], frequencies)
                self.assertGreater(fitted["fitted_ac_energy_fraction"], 1 - 1e-10)
                condition = fitted["design_condition_number"]
                # Close harmonic pairs make a bound of 10 unjustified. A loose
                # numerical guard rejects near-singularity, not poor DSP audio.
                self.assertTrue(math.isfinite(condition))
                self.assertLess(condition, 1000,
                                "combined chord-fit condition = {}".format(condition))
                json.dumps(fitted, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
