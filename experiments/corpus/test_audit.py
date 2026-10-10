"""Small analytic and temporary-WAV checks; never reads the user's corpus."""

import hashlib
import io
import json
import struct
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from audit_stems import (audit_samples, candidate_excerpts, coarse_envelope,
                         decode_pcm, load_pcm_wav)


def pack24(values):
    return b"".join((int(value) & 0xffffff).to_bytes(3, "little") for value in values)


class PcmAuditTests(unittest.TestCase):
    def test_pcm24_signed_endpoints_and_channel_order_are_exact(self):
        integers = [-8388608, 8388607, -1, 0, 1, -1234567]
        decoded = decode_pcm(pack24(integers), 3, 2)
        expected = np.asarray(integers, dtype=np.float64).reshape(3, 2) / 8388608
        np.testing.assert_array_equal(decoded, expected)
        self.assertEqual(decoded.dtype, np.float64)

    def test_pcm16_and_pcm32_endpoints_are_exact(self):
        for width, code in ((2, "h"), (4, "i")):
            with self.subTest(width=width):
                scale = 1 << (width * 8 - 1)
                integers = [-scale, -1, 0, 1, scale - 1]
                decoded = decode_pcm(struct.pack("<5" + code, *integers), width, 1)
                np.testing.assert_array_equal(decoded[:, 0], np.asarray(integers) / scale)

    def test_misaligned_or_unsupported_pcm_is_rejected(self):
        for payload, width, channels in ((b"\x00", 3, 1), (b"\x00" * 3, 3, 2),
                                          (b"", 1, 1), (b"", 3, 0)):
            with self.subTest(width=width, channels=channels):
                with self.assertRaises(ValueError):
                    decode_pcm(payload, width, channels)

    def test_loader_hashes_and_decodes_the_same_small_pcm24_wav(self):
        memory = io.BytesIO()
        integers = [-8388608, 8388607, 0, -1, 12345, -67890]
        with wave.open(memory, "wb") as writer:
            writer.setnchannels(2)
            writer.setsampwidth(3)
            writer.setframerate(44100)
            writer.writeframes(pack24(integers))
        encoded = memory.getvalue()
        with tempfile.TemporaryDirectory(prefix="pitchwing-audit-test-", dir="/tmp") as scratch:
            path = Path(scratch) / "tiny.wav"
            path.write_bytes(encoded)
            samples, rate, metadata = load_pcm_wav(path)
        self.assertEqual(rate, 44100)
        self.assertEqual(metadata["sha256"], hashlib.sha256(encoded).hexdigest())
        self.assertEqual(metadata["frame_count"], 3)
        self.assertEqual(metadata["pcm_bits"], 24)
        np.testing.assert_array_equal(samples, np.asarray(integers).reshape(3, 2) / 8388608)

    def test_float_wav_header_is_rejected(self):
        # IEEE float format tag 3 must not silently pass through the PCM32 path.
        format_chunk = struct.pack("<HHIIHH", 3, 1, 48000, 192000, 4, 32)
        audio = struct.pack("<f", 0.5)
        body = b"WAVEfmt " + struct.pack("<I", len(format_chunk)) + format_chunk
        body += b"data" + struct.pack("<I", len(audio)) + audio
        encoded = b"RIFF" + struct.pack("<I", len(body)) + body
        with tempfile.TemporaryDirectory(prefix="pitchwing-audit-test-", dir="/tmp") as scratch:
            path = Path(scratch) / "float.wav"
            path.write_bytes(encoded)
            with self.assertRaisesRegex(ValueError, "unsupported or malformed WAV"):
                load_pcm_wav(path)

    def test_identical_stereo_statistics_and_endpoint_counts(self):
        scale = 8388608
        mono = np.array([-1.0, (scale - 1) / scale, 0.0, 0.25, -0.5])
        measured = audit_samples(np.column_stack((mono, mono)), 100, 3)
        self.assertTrue(measured["stereo"]["left_right_exactly_equal"])
        self.assertEqual(measured["stereo"]["different_frame_count"], 0)
        self.assertAlmostEqual(measured["stereo"]["pearson_correlation"], 1.0, places=14)
        for channel in measured["channel_statistics"]:
            self.assertEqual(channel["peak_absolute"], 1.0)
            self.assertAlmostEqual(channel["rms"], float(np.sqrt(np.mean(mono * mono))))
            self.assertAlmostEqual(channel["dc_mean"], float(np.mean(mono)))
            self.assertEqual(channel["positive_pcm_endpoint_samples"], 1)
            self.assertEqual(channel["negative_pcm_endpoint_samples"], 1)
            self.assertEqual(channel["exact_zero_samples"], 1)

    def test_opposite_stereo_is_not_cancelled_in_the_energy_envelope(self):
        mono = np.tile([-0.25, 0.25], 100)
        samples = np.column_stack((mono, -mono))
        measured = audit_samples(samples, 100, 3)
        self.assertFalse(measured["stereo"]["left_right_exactly_equal"])
        self.assertEqual(measured["stereo"]["different_frame_count"], 200)
        self.assertAlmostEqual(measured["stereo"]["pearson_correlation"], -1.0)
        np.testing.assert_allclose(measured["coarse_rms_envelope"]["values"], 0.25)

    def test_silence_has_no_candidates_and_json_remains_finite(self):
        for count in (0, 1000):
            with self.subTest(frame_count=count):
                measured = audit_samples(np.zeros((count, 2)), 1000, 3)
                self.assertEqual(measured["candidate_excerpts"], [])
                self.assertIsNone(measured["stereo"]["pearson_correlation"])
                self.assertTrue(measured["stereo"]["left_right_exactly_equal"])
                json.dumps(measured, allow_nan=False)

    def test_nonzero_constant_channel_has_undefined_correlation(self):
        left = np.full(1000, 1234567 / 8388608)
        right = np.tile([-0.25, 0.25], 500)
        measured = audit_samples(np.column_stack((left, right)), 1000, 3)
        self.assertIsNone(measured["stereo"]["pearson_correlation"])
        self.assertFalse(measured["stereo"]["left_right_exactly_equal"])

    def test_candidates_include_known_activity_and_stay_within_source(self):
        rate = 1000
        samples = np.zeros((20000, 2))
        samples[2000:4000] = 0.1
        samples[14000:18000] = 0.3
        envelope, hop = coarse_envelope(samples, rate)
        candidates, threshold = candidate_excerpts(envelope, hop, len(samples), rate)
        self.assertEqual(candidates[0]["start_frame"], 1750)
        self.assertEqual(candidates[0]["selection_reason"], "first_rms_activity_threshold_crossing")
        self.assertGreaterEqual(len(candidates), 2)
        self.assertLessEqual(len(candidates), 3)
        self.assertGreater(threshold, 0)
        for candidate in candidates:
            start, count = candidate["start_frame"], candidate["frame_count"]
            self.assertGreaterEqual(start, 0)
            self.assertLessEqual(count, 6000)
            self.assertLessEqual(start + count, len(samples))
            self.assertGreater(float(np.max(np.abs(samples[start:start + count]))), 0)
        short, _ = candidate_excerpts(np.array([0.1]), 50, 20, rate)
        self.assertEqual(short[0]["start_frame"], 0)
        self.assertEqual(short[0]["frame_count"], 20)


if __name__ == "__main__":
    unittest.main()
