"""Interface checks for the experimental mono engine; NumPy + stdlib only."""
import unittest

import numpy as np

from engine import TransportEngine


CONFIGURATIONS = (
    dict(analysis_size=2048, synthesis_size=384, hop=96, window="asymmetric"),
    dict(analysis_size=384, synthesis_size=384, hop=96, window="symmetric"),
)


def run_stream(engine, samples, block_sizes=(127, 1, 32, 96, 17)):
    outputs = []
    position = 0
    block = 0
    while position < len(samples):
        size = block_sizes[block % len(block_sizes)]
        piece = samples[position:position + size]
        output = engine.process(piece)
        if output.shape != piece.shape:
            raise AssertionError("process must return exactly the input block length")
        outputs.append(output)
        position += len(piece)
        block += 1
    outputs.append(engine.flush())
    return np.concatenate(outputs)


class TransportInterfaceTests(unittest.TestCase):
    def test_unity_is_delayed_identity_for_noise_dc_and_low_tone(self):
        rng = np.random.default_rng(20261008)
        count = 6001
        t = np.arange(count) / 48000.0
        samples = 0.1 * rng.standard_normal(count) + 0.2 + 0.3 * np.sin(
            2 * np.pi * 30.8677 * t)
        original = samples.copy()
        for config in CONFIGURATIONS:
            with self.subTest(config=config):
                engine = TransportEngine(**config)
                self.assertEqual(engine.latency_samples, 383)
                result = run_stream(engine, samples)
                expected = np.zeros(len(result))
                expected[383:383 + count] = samples
                np.testing.assert_allclose(result, expected, atol=2e-12, rtol=0)
                np.testing.assert_array_equal(samples, original)

    def test_every_impulse_hop_phase_has_the_declared_delay(self):
        for config in CONFIGURATIONS:
            engine = TransportEngine(**config)
            for phase in range(96):
                with self.subTest(window=config["window"], phase=phase):
                    engine.reset()
                    samples = np.zeros(192)
                    samples[phase] = 1.0
                    result = run_stream(engine, samples, (1, 31, 64))
                    self.assertEqual(int(np.argmax(np.abs(result))) - phase, 383)
                    expected = np.zeros(len(result))
                    expected[phase + 383] = 1.0
                    np.testing.assert_allclose(result, expected, atol=2e-12, rtol=0)

    def test_shifted_stream_is_independent_of_input_block_partition(self):
        t = np.arange(16007) / 48000.0
        samples = 0.3 * np.sin(2 * np.pi * 41.2034 * t)
        samples += 0.2 * np.sin(2 * np.pi * 87.3071 * t)
        for config in CONFIGURATIONS:
            with self.subTest(window=config["window"]):
                together = run_stream(TransportEngine(semitones=-7, **config),
                                      samples, (len(samples),))
                divided = run_stream(TransportEngine(semitones=-7, **config),
                                     samples, (1, 17, 128, 95, 32))
                np.testing.assert_allclose(divided, together, atol=1e-12, rtol=0)

    def test_reset_clears_phase_history_and_terminal_state(self):
        t = np.arange(4099) / 48000.0
        samples = 0.4 * np.sin(2 * np.pi * 440 * t)
        engine = TransportEngine(semitones=7)
        first = run_stream(engine, samples)
        engine.reset()
        repeated = run_stream(engine, samples)
        np.testing.assert_array_equal(first, repeated)

    def test_static_pitch_and_flush_lifecycle_are_explicit(self):
        engine = TransportEngine()
        self.assertEqual(engine.process(np.empty(0)).size, 0)
        engine.set_pitch_semitones(7)
        engine.process(np.zeros(17))
        engine.set_pitch_semitones(7)
        with self.assertRaises(RuntimeError):
            engine.set_pitch_semitones(-7)
        self.assertGreaterEqual(engine.flush().size, engine.latency_samples)
        self.assertEqual(engine.flush().size, 0)
        with self.assertRaises(RuntimeError):
            engine.process(np.zeros(1))
        engine.reset()
        engine.set_pitch_semitones(-7)
        self.assertEqual(engine.process(np.zeros(31)).size, 31)

    def test_invalid_blocks_do_not_consume_stream_state(self):
        invalid_blocks = (np.array([np.nan]), np.array([np.inf]),
                          np.zeros((2, 10)), np.array([1 + 2j]))
        for invalid in invalid_blocks:
            with self.subTest(shape=invalid.shape, dtype=str(invalid.dtype)):
                engine = TransportEngine(semitones=5)
                prefix = np.sin(2 * np.pi * 82.4069 * np.arange(113) / 48000)
                engine.process(prefix)
                with self.assertRaises((TypeError, ValueError)):
                    engine.process(invalid)
                samples = np.sin(2 * np.pi * 440 * np.arange(1025) / 48000)
                result = run_stream(engine, samples)
                reference = TransportEngine(semitones=5)
                reference.process(prefix)
                fresh = run_stream(reference, samples)
                np.testing.assert_array_equal(result, fresh)

    def test_configuration_cannot_mutate_cached_processing_state(self):
        engine = TransportEngine()
        for field, value in (("sample_rate", 96000), ("analysis_size", 512),
                             ("synthesis_size", 192), ("hop", 48),
                             ("window", "symmetric")):
            with self.subTest(field=field):
                with self.assertRaises(AttributeError):
                    setattr(engine, field, value)
        self.assertEqual(engine.latency_samples, 383)

    def test_invalid_configuration_and_controls_are_rejected(self):
        cases = (dict(sample_rate=0), dict(hop=0), dict(hop=95),
                 dict(analysis_size=128), dict(synthesis_size=0),
                 dict(window="unknown"), dict(semitones=float("nan")),
                 dict(semitones=13))
        for config in cases:
            with self.subTest(config=config):
                with self.assertRaises((TypeError, ValueError)):
                    TransportEngine(**config)
        engine = TransportEngine()
        for pitch in (float("nan"), float("inf"), -13):
            with self.assertRaises((TypeError, ValueError)):
                engine.set_pitch_semitones(pitch)
        self.assertEqual(engine.process(np.zeros(1)).size, 1)

    def test_resolved_tone_octaves_have_energy_at_the_shifted_frequency(self):
        # A coarse correctness gate for modulation sign and phase accumulation,
        # not the <1-cent quality gate or a claim about low guitar performance.
        t = np.arange(24000) / 48000.0
        samples = 0.4 * np.sin(2 * np.pi * 750 * t)
        for config in CONFIGURATIONS:
            for shift in (-12, 12):
                with self.subTest(window=config["window"], shift=shift):
                    engine = TransportEngine(semitones=shift, **config)
                    full = run_stream(engine, samples, (128,))
                    result = full[383:383 + len(samples)][9600:21600]
                    target = 750 * 2 ** (shift / 12.0)
                    phase = 2 * np.pi * target * np.arange(len(result)) / 48000
                    basis = np.column_stack((np.cos(phase), np.sin(phase)))
                    coefficients = np.linalg.lstsq(basis, result, rcond=None)[0]
                    fit = basis @ coefficients
                    self.assertAlmostEqual(float(np.linalg.norm(coefficients)), 0.4,
                                           delta=0.04)
                    power = float(result @ result)
                    self.assertGreater(power, 1.0)
                    self.assertLess(float((result - fit) @ (result - fit)) / power, 0.1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
