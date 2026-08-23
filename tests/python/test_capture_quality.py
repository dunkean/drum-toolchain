from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from drum_sampler import CaptureQualityPolicy, CaptureRequest, CaptureSessionPlan, assess_wav, audit_library, library_from_plan


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


if __name__ == "__main__":
    unittest.main()
