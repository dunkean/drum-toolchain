from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile

from drum_domain.project import KitProject
from drum_sampler.audio import QualityProfile, load_quality_profile, process_wav
from drum_sampler import CaptureSessionPlan


ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "profiles/legacy/kit_20_articulations.yaml"
ELECTRONIC_BANK = ROOT / "profiles/legacy/ddti_electronic_bank.yaml"


class LegacyCompatibilityTests(unittest.TestCase):
    def test_existing_extended_profile_still_validates(self) -> None:
        project = KitProject.load(KIT)
        self.assertEqual(project.validate(), [])
        self.assertEqual(project.allocated_blocks(), 6730)
        self.assertEqual(len(project.routes), 23)
        self.assertEqual(project.route(11, 42).output_note, 91)
        self.assertEqual(project.hihat_cc(11, 4, 64), (4, 64))

    def test_existing_velocity_window_profile_still_validates(self) -> None:
        project = KitProject.load(ELECTRONIC_BANK)
        self.assertEqual(project.validate(), [])
        self.assertEqual(len(project.routes), 10)
        self.assertEqual({route.output_note for route in project.routes}, {60})
        self.assertEqual(project.mapped_velocity(project.route(10, 36), 100), 10)
        self.assertEqual(project.mapped_velocity(project.route(10, 45), 100), 123)

    def test_existing_mapping_generator_remains_deterministic(self) -> None:
        generator = ROOT / "firmware/ddrum4-midi-bridge/tools/generate_mapping.py"
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.h"
            second = Path(temporary) / "second.h"
            for output in (first, second):
                result = subprocess.run(
                    [sys.executable, str(generator), str(KIT), "--output", str(output)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertIn(b"{11, 42, 91, 1, 127, 1, 127}", first.read_bytes())

    def test_existing_wav_processing_behavior_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "raw.wav"
            output = Path(temporary) / "prepared.wav"
            signal = np.concatenate((np.zeros(1200), np.ones(2400) * 0.1, np.zeros(1200))).astype(np.float32)
            wavfile.write(source, 48000, signal)
            result = process_wav(source, output, QualityProfile(target_sample_rate=44100, trim_threshold_db=-40, normalize_dbfs=-1))
            rate, prepared = wavfile.read(output)
            self.assertEqual(rate, 44100)
            self.assertLess(result["frames"], 4410)
            self.assertGreater(np.max(np.abs(prepared)), 28000)

    def test_existing_quality_profile_is_available(self) -> None:
        profile = load_quality_profile(ROOT / "profiles/capture/audio-quality.yaml", "compact")
        self.assertEqual(profile.lowpass_hz, 15000)
        self.assertEqual(profile.target_sample_rate, 44100)

    def test_flagship_cymbal_capture_contract_is_long_tail_and_dense(self) -> None:
        profile = load_quality_profile(ROOT / "profiles/capture/audio-quality.yaml", "ddrum4_cymbal_flagship")
        self.assertEqual(profile.max_duration_seconds, 4.5)
        self.assertTrue(profile.force_mono)
        proof = CaptureSessionPlan.read(ROOT / "profiles/capture/sd3-djentle-beast-long-tail-proof.json")
        full = CaptureSessionPlan.read(ROOT / "profiles/capture/sd3-djentle-beast-long-tail-cymbals.json")
        self.assertEqual(proof.tail_ms, 10000)
        self.assertEqual(len(proof.takes()), 1)
        self.assertEqual(full.tail_ms, 10000)
        self.assertEqual(len(full.takes()), 70)
        crash_one = next(request for request in full.requests if request.instrument == "crash_main_1")
        self.assertEqual(crash_one.velocities, (24, 56, 88, 110, 127))
        self.assertEqual(crash_one.repetitions, 3)
