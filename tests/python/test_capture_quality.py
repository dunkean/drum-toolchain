from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from drum_sampler import CaptureQualityPolicy, CaptureRequest, CaptureSessionPlan, assess_wav, audit_library, library_from_plan
from drum_sampler.audio import QualityProfile, process_wav


class CaptureQualityTests(unittest.TestCase):
    def test_assess_rejects_silence_and_clipping_without_touching_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            silent = root / "silent.wav"
            clipped = root / "clipped.wav"
            wavfile.write(silent, 44100, np.zeros(4410, dtype=np.int16))
            wavfile.write(clipped, 44100, np.full(4410, 32767, dtype=np.int16))
            self.assertEqual(assess_wav(silent)["findings"], ["silent"])
            self.assertIn("clipped", assess_wav(clipped)["findings"])
            self.assertTrue(silent.is_file())

    def test_audit_marks_missing_raw(self) -> None:
        session = CaptureSessionPlan("midi", "audio", ("left",), (CaptureRequest("kick", "head", 36, (100,), 1),))
        library = library_from_plan("fixture", session.channels, session.takes())
        report = audit_library(library, Path("does-not-exist"), CaptureQualityPolicy())
        self.assertEqual(report["summary"]["missing"], 1)

    def test_assess_accepts_a_short_hit_in_a_long_raw_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "short-hit-long-window.wav"
            samples = np.zeros(441000, dtype=np.float32)
            samples[4410:8820] = 0.1
            wavfile.write(source, 44100, samples)
            self.assertNotIn("silent", assess_wav(source)["findings"])

    def test_preparation_keeps_independent_attack_and_tail_margins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "raw.wav", root / "prepared.wav"
            samples = np.zeros(44100, dtype=np.float32)
            samples[11025:13230] = 0.25
            wavfile.write(source, 44100, samples)
            facts = process_wav(
                source, output,
                QualityProfile(
                    fade_in_ms=0, fade_out_ms=0, trim_threshold_db=-60,
                    onset_margin_ms=15, tail_margin_ms=250,
                ),
            )
            self.assertAlmostEqual(float(facts["duration_seconds"]), 0.315, places=3)

    def test_preparation_pads_missing_preroll_without_fading_the_transient(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "immediate.wav", root / "prepared.wav"
            samples = np.zeros(4410, dtype=np.float32)
            samples[:220] = 0.25
            wavfile.write(source, 44100, samples)
            process_wav(
                source, output,
                QualityProfile(
                    fade_in_ms=0, fade_out_ms=0, onset_margin_ms=5,
                    tail_margin_ms=0, trim_threshold_db=-60,
                ),
            )
            _, prepared = wavfile.read(output)
            self.assertTrue(np.all(prepared[:220] == 0))
            self.assertNotEqual(int(prepared[220]), 0)


if __name__ == "__main__":
    unittest.main()
