"""
Tests for waveform.py on synthetic audio written to temporary WAV files.
librosa decodes them for real; no network.
"""
import os
import tempfile
import unittest

import numpy as np
import soundfile as sf

import waveform

SR = 22050
RNG = np.random.default_rng(7)


def tone(seconds, amp=0.3, freq=220.0):
    t = np.arange(int(seconds * SR)) / SR
    return amp * np.sin(2 * np.pi * freq * t) + 0.01 * RNG.standard_normal(len(t))


def silence(seconds):
    return np.zeros(int(seconds * SR))


class WaveCase(unittest.TestCase):
    def measure(self, signal):
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            sf.write(path, signal.astype(np.float32), SR)
            return waveform.measure_waveform(path)
        finally:
            os.remove(path)


class TestMeasure(WaveCase):
    def test_hard_cut(self):
        m = self.measure(np.concatenate([silence(2), tone(10), silence(3)]))
        self.assertAlmostEqual(m["duration"], 15.0, delta=0.05)
        self.assertAlmostEqual(m["first_sound_t"], 2.0, delta=0.2)
        self.assertAlmostEqual(m["tail_silence"], 3.0, delta=0.3)
        self.assertLess(m["decay_seconds"], 1.0)
        self.assertLess(m["quietest_t"], 12.0)  # never inside the trailing silence
        self.assertEqual(len(m["per_sec_db"]), 15)

    def test_ring_out_is_measured(self):
        """The spec's decay formula returned 0.0 here, which would block every ring-out."""
        decay = np.exp(-np.arange(int(4 * SR)) / SR * 1.5)
        m = self.measure(np.concatenate([silence(2), tone(8), tone(4) * decay, silence(3)]))
        self.assertGreater(m["decay_seconds"], 1.0)

    def test_fade_out_is_measured(self):
        m = self.measure(np.concatenate([silence(1), tone(6), tone(6) * np.linspace(1, 0, int(6 * SR)), silence(2)]))
        self.assertGreater(m["decay_seconds"], 1.0)

    def test_quiet_opening_counts_as_sound_without_digital_silence(self):
        m = self.measure(np.concatenate([tone(5, amp=0.01), tone(10, amp=0.5)]))
        self.assertLess(m["first_sound_t"], 0.5)

    def test_loudest_and_peaks(self):
        m = self.measure(np.concatenate([tone(10, amp=0.05), tone(3, amp=0.6), tone(10, amp=0.05)]))
        self.assertTrue(10.0 <= m["loudest_t"] <= 13.0, m["loudest_t"])
        self.assertIn(m["peaks_t"][0], (10.0, 11.0, 12.0))

    def test_top_peaks_are_spaced(self):
        self.assertEqual(waveform.top_peaks([0, 9, 8, 7, 0, 0, 0, 6, 0, 0, 0, 0, 5]), [1.0, 7.0, 12.0])

    def test_measure_bytes(self):
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            sf.write(path, tone(5).astype(np.float32), SR)
            with open(path, "rb") as fh:
                m = waveform.measure_bytes(fh.read(), ".wav")
        finally:
            os.remove(path)
        self.assertAlmostEqual(m["duration"], 5.0, delta=0.05)

    def test_garbage_raises(self):
        with self.assertRaises(Exception):
            waveform.measure_bytes(b"not audio at all", ".mp3")


if __name__ == "__main__":
    unittest.main(verbosity=2)
