from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.io import wavfile

from drum_sampler.audio import QualityProfile
from drum_sampler.library import SampleLibrary, SampleTake
from drum_sampler.offline import (drumgizmo_note_overrides, merge_library_files,
                                  prepare_selected_takes, run_offline_recipe, validate_drumgizmo_kit,
                                  verify_drumgizmo_kit)


class OfflineSamplerTests(unittest.TestCase):
    def test_compiler_note_map_parses_instrument_articulation_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "drumgizmo-midimap.json"
            path.write_text(json.dumps({"format": "drum-note-map/v1", "target": "drumgizmo",
                                        "mappings": [{"logical_target": "hi_hat.closed", "note": 42}]}), encoding="utf-8")
            self.assertEqual(drumgizmo_note_overrides(path), {("hi_hat", "closed"): 42})

    def test_compiler_note_map_prefers_explicit_drumgizmo_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "drumgizmo-midimap.json"
            path.write_text(json.dumps({"format": "drum-note-map/v1", "target": "drumgizmo",
                                        "mappings": [{"logical_target": "scene.variant", "note": 42,
                                                      "instrument": "hi_hat", "articulation": "closed"}]}), encoding="utf-8")
            self.assertEqual(drumgizmo_note_overrides(path), {("hi_hat", "closed"): 42})

    def test_preparation_writes_new_file_and_preserves_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); raw = root / "raw.wav"
            wavfile.write(raw, 44100, np.array([0, 12000, -12000, 0], dtype=np.int16))
            original = raw.read_bytes()
            take = SampleTake("snare", "head", 38, 10, 100, 1, "raw.wav", sample_rate=44100,
                              channels=("left",), frames=4, status="captured")
            library = SampleLibrary("fixture", ("left",), (take,))
            prepared = prepare_selected_takes(library, audio_root=root, output_root=root / "prepared",
                                              profile=QualityProfile(target_sample_rate=44100))
            self.assertEqual(raw.read_bytes(), original)
            self.assertTrue((root / prepared.takes[0].prepared_file).is_file())
            self.assertEqual(prepared.takes[0].processing_history, ("offline-quality-profile",))

    def test_merge_files_prefixes_audio_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            take = SampleTake("kick", "head", 36, 10, 90, 1, "raw.wav", channels=("left",))
            source = root / "one.json"; SampleLibrary("one", ("left",), (take,)).write(source)
            merged = merge_library_files("merged", ((source, "source-one"),))
            self.assertEqual(merged.takes[0].raw_file, "source-one/raw.wav")

    def test_recipe_writes_resumable_offline_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library = root / "library.json"
            SampleLibrary("fixture", ("left", "right"), ()).write(library)
            note_map = root / "drumgizmo-midimap.json"
            note_map.write_text(json.dumps({"format": "drum-note-map/v1", "target": "drumgizmo", "mappings": []}), encoding="utf-8")
            recipe = root / "recipe.json"
            recipe.write_text(json.dumps({"kind": "drum-sampler-offline-recipe", "schema_version": 1,
                                          "library": "library.json", "drumgizmo_note_map": "drumgizmo-midimap.json",
                                          "output_directory": "kit"}), encoding="utf-8")
            report = root / "report.json"
            result = run_offline_recipe(recipe, report)
            self.assertEqual(result["channel_layout"], ["left", "right"])
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["hardware_io"], "disabled")

    def test_drumgizmo_verification_records_version_backend_and_valid_xml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "instruments").mkdir(); (root / "samples").mkdir()
            wavfile.write(root / "samples" / "kick.wav", 44100, np.zeros(16, dtype=np.int16))
            (root / "instruments" / "kick.xml").write_text(
                '<instrument version="2.0" name="kick"><samples><sample name="hit" power="1.0">'
                '<audiofile channel="left" file="../samples/kick.wav" filechannel="1"/>'
                '</sample></samples></instrument>', encoding="utf-8")
            (root / "drumkit.xml").write_text(
                '<drumkit version="2.0" samplerate="44100"><channels><channel name="left"/>'
                '</channels><instruments><instrument name="kick" file="instruments/kick.xml"/>'
                '</instruments></drumkit>', encoding="utf-8")
            (root / "midimap.xml").write_text('<midimap><map note="36" instr="kick"/></midimap>', encoding="utf-8")
            report_path = root / "report.json"
            with patch("drum_sampler.offline.subprocess.run") as run:
                run.return_value = __import__("subprocess").CompletedProcess(("drumgizmo", "--version"), 0, "DrumGizmo 0.9\n", "")
                report = verify_drumgizmo_kit(root, report_path, backend="jackmidi")
            self.assertEqual(report["drumgizmo"]["version"], "DrumGizmo 0.9")
            self.assertEqual(report["backend"], "jackmidi")
            self.assertEqual(report["audio_load"], "not_executed")
            self.assertEqual(report["kit"], {"channels": 1, "instruments": 1, "samples": 1, "mappings": 1})
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["kind"], "drumgizmo-smoke-report")

    def test_drumgizmo_validation_rejects_unknown_midi_instrument(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "drumkit.xml").write_text(
                '<drumkit version="2.0" samplerate="44100"><channels><channel name="left"/>'
                '</channels><instruments><instrument name="kick" file="kick.xml"/>'
                '</instruments></drumkit>', encoding="utf-8")
            (root / "kick.xml").write_text(
                '<instrument version="2.0" name="kick"><samples><sample name="hit" power="1">'
                '<audiofile channel="left" file="kick.wav" filechannel="1"/>'
                '</sample></samples></instrument>', encoding="utf-8")
            wavfile.write(root / "kick.wav", 44100, np.zeros(16, dtype=np.int16))
            (root / "midimap.xml").write_text('<midimap><map note="36" instr="missing"/></midimap>', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unknown instrument"):
                validate_drumgizmo_kit(root)

    def test_drumgizmo_validation_rejects_invalid_wav_channel_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wavfile.write(root / "kick.wav", 44100, np.zeros(16, dtype=np.int16))
            (root / "kick.xml").write_text(
                '<instrument version="2.0" name="kick"><samples><sample name="hit" power="1">'
                '<audiofile channel="left" file="kick.wav" filechannel="2"/>'
                '</sample></samples></instrument>', encoding="utf-8")
            (root / "drumkit.xml").write_text(
                '<drumkit version="2.0" samplerate="44100"><channels><channel name="left"/>'
                '</channels><instruments><instrument name="kick" file="kick.xml"/>'
                '</instruments></drumkit>', encoding="utf-8")
            (root / "midimap.xml").write_text('<midimap><map note="36" instr="kick"/></midimap>', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "exceeds WAV channels"):
                validate_drumgizmo_kit(root)


if __name__ == "__main__":
    unittest.main()
