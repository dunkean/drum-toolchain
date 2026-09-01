from __future__ import annotations

import tempfile
import unittest
import warnings
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from scipy.io import wavfile

from drum_sampler import CaptureQualityPolicy, CaptureRequest, CaptureSessionPlan, assess_wav, audit_library, calibrate_session, library_from_plan
from drum_sampler.audio import QualityProfile, WASAPI_LOOPBACK_BLOCKSIZE, _capture_loopback, process_wav


class _FakeRecorder:
    def __init__(self, microphone: "_FakeMicrophone", warning_type: type[Warning] | None = None) -> None:
        self.microphone = microphone
        self.warning_type = warning_type

    def __enter__(self) -> "_FakeRecorder":
        self.microphone.entered = True
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def record(self, *, numframes: int) -> np.ndarray:
        if self.warning_type is not None:
            warnings.warn("data discontinuity in recording", self.warning_type)
        return np.zeros((numframes, 2), dtype=np.float32)


class _FakeMicrophone:
    name = "OUT 3-4"
    isloopback = True

    def __init__(self, warning_type: type[Warning] | None = None) -> None:
        self.warning_type = warning_type
        self.blocksize: int | None = None
        self.entered = False

    def recorder(self, *, samplerate: int, channels: list[int], blocksize: int) -> _FakeRecorder:
        self.blocksize = blocksize
        return _FakeRecorder(self, self.warning_type)


class CaptureQualityTests(unittest.TestCase):
    def test_calibration_selects_representative_hits_and_reuses_probe_wavs(self) -> None:
        session = CaptureSessionPlan(
            "virtual-midi", "loopback:output", ("left", "right"),
            (
                CaptureRequest("kick", "acoustic", 24, (24, 72, 120), 4, channel=10),
                CaptureRequest("hh", "bow_half", 64, (24, 96, 120), 3, channel=10, controllers=((4, 64),)),
            ),
            sample_rate=48000,
        )
        calls: list[dict[str, object]] = []

        def fake_capture(**kwargs: object) -> Path:
            calls.append(kwargs)
            output = kwargs["output"]
            assert isinstance(output, Path)
            wavfile.write(output, 48000, np.full((128, 2), 0.25, dtype=np.float32))
            return output

        with tempfile.TemporaryDirectory() as temporary, patch("drum_sampler.calibration.time.sleep"):
            output = Path(temporary)
            preset = output / "preset.sd3p"
            preset.write_bytes(b"preset-a")
            preset_sha = hashlib.sha256(preset.read_bytes()).hexdigest()
            arguments = {
                "session_sha256": "a" * 64,
                "preset_path": preset,
                "preset_sha256": preset_sha,
                "preset_loaded_confirmed": True,
                "capture": fake_capture,
            }
            first = calibrate_session(session, output, **arguments)
            second = calibrate_session(session, output, **arguments)
            changed = calibrate_session(session, output, **{**arguments, "preset_sha256": "b" * 64})
        self.assertEqual([call["velocity"] for call in calls], [120, 120, 120, 120])
        self.assertEqual(calls[1]["controllers"], ((4, 64),))
        self.assertEqual(first["summary"]["captured_now"], 2)
        self.assertEqual(second["summary"]["reused"], 2)
        self.assertEqual(changed["summary"]["captured_now"], 2)
        self.assertNotEqual(first["probe_set_id"], changed["probe_set_id"])
        self.assertEqual(first["summary"]["status"], "technical-pass-user-mix-review-required")

    def test_calibration_reports_silence_clipping_headroom_and_relative_outliers(self) -> None:
        session = CaptureSessionPlan(
            "virtual-midi", "loopback:output", ("left", "right"),
            tuple(CaptureRequest("probe", name, note, (110,), 1) for name, note in (
                ("silent", 24), ("clipped", 25), ("hot", 26), ("quiet", 27),
            )),
        )
        levels = {24: 0.0, 25: 1.0, 26: 0.98, 27: 0.01}

        def fake_capture(**kwargs: object) -> Path:
            output = kwargs["output"]
            note = kwargs["note"]
            assert isinstance(output, Path) and isinstance(note, int)
            wavfile.write(output, 44100, np.full((256, 2), levels[note], dtype=np.float32))
            return output

        with tempfile.TemporaryDirectory() as temporary, patch("drum_sampler.calibration.time.sleep"):
            report = calibrate_session(
                session, Path(temporary), session_sha256="a" * 64,
                preset_path=Path("MegaKit.sd3p"), preset_sha256="b" * 64,
                preset_loaded_confirmed=True, capture=fake_capture,
            )
        rows = {row["articulation"]: row for row in report["rows"]}
        self.assertIn("silent", rows["silent"]["findings"])
        self.assertIn("clipped", rows["clipped"]["findings"])
        self.assertIn("insufficient-headroom", rows["hot"]["findings"])
        self.assertIn("relative-level-outlier", rows["quiet"]["findings"])
        self.assertEqual(report["summary"]["status"], "technical-fail")

    def test_calibration_relative_level_gate_compares_musical_families_only(self) -> None:
        session = CaptureSessionPlan(
            "virtual-midi", "loopback:output", ("left", "right"),
            (
                CaptureRequest("kick", "acoustic", 24, (110,), 1),
                CaptureRequest("kick", "electronic", 25, (110,), 1),
                CaptureRequest("hh", "bow_closed", 64, (110,), 1),
                CaptureRequest("snare1", "metalcore", 32, (110,), 1),
                CaptureRequest("snare_layer", "sleep_snare7", 103, (110,), 1),
            ),
        )
        levels = {24: 0.5, 25: 0.05, 64: 0.005, 32: 0.5, 103: 0.05}

        def fake_capture(**kwargs: object) -> Path:
            output, note = kwargs["output"], kwargs["note"]
            assert isinstance(output, Path) and isinstance(note, int)
            wavfile.write(output, 44100, np.full((256, 2), levels[note], dtype=np.float32))
            return output

        with tempfile.TemporaryDirectory() as temporary, patch("drum_sampler.calibration.time.sleep"):
            report = calibrate_session(
                session, Path(temporary), session_sha256="a" * 64,
                preset_path=Path("MegaKit.sd3p"), preset_sha256="b" * 64,
                preset_loaded_confirmed=True, capture=fake_capture,
            )

        rows = {f"{row['instrument']}.{row['articulation']}": row for row in report["rows"]}
        self.assertIn("relative-level-outlier", rows["kick.electronic"]["findings"])
        self.assertNotIn("relative-level-outlier", rows["hh.bow_closed"]["findings"])
        self.assertNotIn("relative-level-outlier", rows["snare_layer.sleep_snare7"]["findings"])
        self.assertEqual(report["summary"]["level_groups"]["snare.layer"]["articulations"], 1)
        self.assertAlmostEqual(report["summary"]["level_groups"]["kick"]["peak_span_db"], 20.0, places=6)
        self.assertEqual(report["summary"]["status"], "level-fail")

    def test_calibration_can_probe_exact_articulations_then_reuse_them_in_full_run(self) -> None:
        session = CaptureSessionPlan(
            "virtual-midi", "loopback:output", ("left", "right"),
            (
                CaptureRequest("snare", "rimshot", 35, (80, 120), 1, channel=10),
                CaptureRequest("tom2", "electronic", 53, (80, 120), 1, channel=10),
                CaptureRequest("ride", "bow", 83, (80, 120), 1, channel=10),
            ),
        )
        calls: list[int] = []

        def fake_capture(**kwargs: object) -> Path:
            output, note = kwargs["output"], kwargs["note"]
            assert isinstance(output, Path) and isinstance(note, int)
            calls.append(note)
            wavfile.write(output, 44100, np.full((256, 2), 0.25, dtype=np.float32))
            return output

        arguments = {
            "session_sha256": "a" * 64,
            "preset_path": Path("MegaKit.sd3p"),
            "preset_sha256": "b" * 64,
            "preset_loaded_confirmed": True,
            "capture": fake_capture,
        }
        with tempfile.TemporaryDirectory() as temporary, patch("drum_sampler.calibration.time.sleep"):
            output = Path(temporary)
            targeted = calibrate_session(
                session, output, only=("tom2.electronic", "snare.rimshot"), **arguments,
            )
            full = calibrate_session(session, output, **arguments)

        self.assertEqual(calls, [35, 53, 83])
        self.assertEqual([row["note"] for row in targeted["rows"]], [35, 53])
        self.assertEqual(targeted["summary"]["captured_now"], 2)
        self.assertEqual(full["summary"]["reused"], 2)
        self.assertEqual(full["summary"]["captured_now"], 1)
        with self.assertRaisesRegex(ValueError, "unknown calibration articulation selectors"):
            calibrate_session(session, Path("unused"), only=("missing.articulation",), **arguments)

    def test_loopback_uses_safe_buffer_and_writes_clean_take(self) -> None:
        class FakeSoundcardWarning(Warning):
            pass

        microphone = _FakeMicrophone()
        soundcard = SimpleNamespace(
            SoundcardRuntimeWarning=FakeSoundcardWarning,
            all_microphones=lambda **_kwargs: [microphone],
        )
        with tempfile.TemporaryDirectory() as temporary, \
             patch.dict("sys.modules", {"soundcard": soundcard}), \
             patch("drum_sampler.audio._emit_note", side_effect=lambda *_args: self.assertTrue(microphone.entered)):
            output = Path(temporary) / "capture.wav"
            _capture_loopback(
                midi_port="virtual", query="OUT 3-4", note=36, velocity=100,
                output=output, channel=10, controllers=(), frames=64,
                duration=0.01, gate=0, preroll=0, sample_rate=48000, channels=2,
            )
            self.assertEqual(microphone.blocksize, WASAPI_LOOPBACK_BLOCKSIZE)
            self.assertTrue(output.is_file())

    def test_loopback_rejects_discontinuous_take_before_writing(self) -> None:
        class FakeSoundcardWarning(Warning):
            pass

        microphone = _FakeMicrophone(FakeSoundcardWarning)
        soundcard = SimpleNamespace(
            SoundcardRuntimeWarning=FakeSoundcardWarning,
            all_microphones=lambda **_kwargs: [microphone],
        )
        with tempfile.TemporaryDirectory() as temporary, \
             patch.dict("sys.modules", {"soundcard": soundcard}), \
             patch("drum_sampler.audio._emit_note"):
            output = Path(temporary) / "capture.wav"
            with self.assertRaisesRegex(RuntimeError, "potentially cracked WAV"):
                _capture_loopback(
                    midi_port="virtual", query="OUT 3-4", note=36, velocity=100,
                    output=output, channel=10, controllers=(), frames=64,
                    duration=0.01, gate=0, preroll=0, sample_rate=48000, channels=2,
                )
            self.assertFalse(output.exists())

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

    def test_assess_rejects_wrong_master_rate_and_channel_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "wrong-master.wav"
            wavfile.write(source, 44100, np.full(4410, 0.25, dtype=np.float32))

            report = assess_wav(source, CaptureQualityPolicy(
                expected_sample_rate=48000, expected_channels=2,
            ))

            self.assertEqual(report["automatic_status"], "rejected")
            self.assertEqual(report["findings"], ["wrong_sample_rate", "wrong_channel_count"])

    def test_audit_marks_missing_raw(self) -> None:
        session = CaptureSessionPlan("midi", "audio", ("left",), (CaptureRequest("kick", "head", 36, (100,), 1),))
        library = library_from_plan("fixture", session.channels, session.takes())
        report = audit_library(library, Path("does-not-exist"), CaptureQualityPolicy())
        self.assertEqual(report["summary"]["missing"], 1)

    def test_audit_rejects_byte_identical_round_robin_cells(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = CaptureSessionPlan(
                "midi", "audio", ("left",),
                (CaptureRequest("snare", "center", 38, (100,), 2),),
            )
            library = library_from_plan("fixture", session.channels, session.takes())
            samples = np.linspace(-0.2, 0.2, 4410, dtype=np.float32)
            for take in library.takes:
                wavfile.write(root / take.raw_file, 44100, samples)

            report = audit_library(library, root, CaptureQualityPolicy())

            self.assertEqual(report["summary"]["round_robin_duplicate_cells"], 1)
            self.assertEqual(report["round_robin_duplicates"][0]["unique_audio_fingerprints"], 1)

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
