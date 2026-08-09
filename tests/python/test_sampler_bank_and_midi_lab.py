from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from drum_sampler import CaptureRequest, CaptureSessionPlan, SampleLibrary, analyze_wav, capture_pending, library_from_captures, library_from_plan
from ddrum4_bank.ddrum4ui import encoded_block_count
from ddrum4_bank.backup import validate_settings_backup
from ddrum4_bank.nested import NestedRoute, NestedSound
from ddrum4_bank.routing_contract import ContractRoute, RoutingContract
from midi_lab import MidiTrace, TraceEvent, resolve_unique_port


class SamplerBankAndMidiLabTests(unittest.TestCase):
    def test_capture_grid_is_dense_and_resumable(self) -> None:
        request = CaptureRequest("snare_main", "head", 38, (16, 64, 127), 2)
        plan = CaptureSessionPlan("out_APC", "loopback", ("left", "right"), (request,))
        self.assertEqual(len(plan.takes()), 6)
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary)
            first = plan.takes()[0]
            (raw / first.raw_filename()).touch()
            self.assertEqual(len(plan.incomplete_takes(raw)), 5)

    def test_neutral_sample_library_round_trip(self) -> None:
        request = CaptureRequest("snare_main", "head", 38, (64,), 2)
        library = library_from_plan("sd3-metalcore", ("left", "right"), CaptureSessionPlan("out_APC", "loopback", ("left", "right"), (request,)).takes())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "library.json"
            library.write(path)
            self.assertEqual(SampleLibrary.read(path), library)

    def test_wav_analysis_returns_portable_library_facts(self) -> None:
        import numpy as np
        from scipy.io import wavfile
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "take.wav"
            wavfile.write(path, 44100, np.array([[0], [16384], [-16384]], dtype=np.int16))
            facts = analyze_wav(path)
            self.assertEqual(facts["sample_rate"], 44100)
            self.assertEqual(facts["frames"], 3)
            self.assertEqual(facts["channels"], 1)
            self.assertFalse(facts["clipped"])
            self.assertEqual(len(str(facts["sha256"])), 64)

    def test_capture_executor_is_resumable_and_enriches_library(self) -> None:
        import numpy as np
        from scipy.io import wavfile
        request = CaptureRequest("kick_main", "head", 36, (64,), 2)
        session = CaptureSessionPlan("fixture-midi", "fixture-audio", ("kick", "snare", "left", "right"), (request,), tail_ms=10)
        calls: list[Path] = []
        def fake_capture(**kwargs: object) -> Path:
            output = kwargs["output"]
            assert isinstance(output, Path)
            calls.append(output)
            wavfile.write(output, 44100, np.zeros((8, 4), dtype=np.int16))
            return output
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary)
            self.assertEqual(len(capture_pending(session, raw, capture=fake_capture)), 2)
            self.assertEqual(len(calls), 2)
            self.assertEqual(capture_pending(session, raw, capture=fake_capture), ())
            library = library_from_captures("fixture", session, raw, source="test VST", license_statement="user-owned render")
            self.assertTrue(all(take.status == "captured" for take in library.takes))
            self.assertTrue(all(take.channels == ("kick", "snare", "left", "right") for take in library.takes))
            self.assertTrue(all(take.frames == 8 for take in library.takes))

    def test_safe_cli_entry_points_create_and_inspect_metadata(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "fixture.json"
            sampler = subprocess.run(
                [sys.executable, "-m", "drum_sampler.cli", "fixture", "--output", str(fixture)],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(sampler.returncode, 0, sampler.stderr)
            self.assertEqual(len(SampleLibrary.read(fixture).takes), 6)
            midi_trace = Path(temporary) / "trace.jsonl"
            MidiTrace("fixture", (TraceEvent(0, "note_on", 10, 36, 120),)).write(midi_trace)
            midi_lab = subprocess.run(
                [sys.executable, "-m", "midi_lab.cli", "trace-info", str(midi_trace)],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(midi_lab.returncode, 0, midi_lab.stderr)
            self.assertIn("events=1", midi_lab.stdout)
            bank = subprocess.run(
                [sys.executable, "-m", "ddrum4_bank.cli", "discover", "--root", "D:/Studio/ddrum4ui"],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(bank.returncode, 0, bank.stderr)
            self.assertIn("ddrum4edit.exe", bank.stdout)

    def test_nested_layout_enforces_ddrum4_limits(self) -> None:
        sound = NestedSound("CYMB_801", 4, (
            NestedRoute("crash_1", 1, 5, 5, 1),
            NestedRoute("crash_2", 2, 5, 5, 1),
        ))
        self.assertEqual(sound.validate(), ())
        invalid = NestedSound("CYMB_802", 2, (
            NestedRoute("a", 1, 6, 5, 1),
            NestedRoute("b", 1, 5, 6, 1),
        ))
        self.assertIn("nested positions must be unique", invalid.validate())
        self.assertIn("nested sound exceeds ten sample slots", invalid.validate())

    def test_backend_block_parser_is_retained(self) -> None:
        self.assertEqual(encoded_block_count("Total Blocks Count : 00 0C (12)"), 12)

    def test_settings_backup_validator_requires_real_midi_content(self) -> None:
        import mido
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "backup.mid"
            midi = mido.MidiFile(type=0)
            track = mido.MidiTrack()
            track.append(mido.Message("sysex", data=(1, 2, 3)))
            midi.tracks.append(track)
            midi.save(path)
            record = validate_settings_backup(path)
            self.assertEqual(record.message_count, 1)
            self.assertEqual(record.sysex_count, 1)

    def test_routing_contract_is_valid_and_serializable(self) -> None:
        contract = RoutingContract(
            "metalcore-main",
            10,
            {"ddti": 10, "edrumin": 11},
            {"mode": "direct_cc4", "source": "edrumin", "input_cc": 4, "output_cc": 4, "input_closed": 0, "input_open": 127, "output_closed": 0, "output_open": 127},
            (ContractRoute("snare_head", "ddti", 38, 40, "SNRE_801", position=1),),
        )
        document = contract.to_document()
        self.assertEqual(document["kind"], "ddrum4-routing-contract")
        self.assertEqual(document["routes"][0]["velocity"]["output_max"], 127)
        root = Path(__file__).resolve().parents[2]
        generator = root / "firmware/ddrum4-midi-bridge/tools/generate_mapping.py"
        with tempfile.TemporaryDirectory() as temporary:
            input_path = Path(temporary) / "routing-contract.json"
            output_path = Path(temporary) / "generated_mapping.h"
            contract.write(input_path)
            result = subprocess.run([sys.executable, str(generator), str(input_path), "--output", str(output_path)], text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("{10, 38, 40, 1, 127, 1, 127}", output_path.read_text(encoding="utf-8"))

    def test_trace_round_trip_and_unique_port_matching(self) -> None:
        trace = MidiTrace("edrumin", (TraceEvent(0, "note_on", 11, 42, 100),))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trace.jsonl"
            trace.write(path)
            self.assertEqual(MidiTrace.read(path), trace)
        self.assertEqual(resolve_unique_port(["MIDI4x4", "MIDIOUT2 (MIDI4x4)"], "MIDI4x4"), "MIDI4x4")
        with self.assertRaises(ValueError):
            resolve_unique_port(["MIDI4x4", "MIDIOUT2 (MIDI4x4)"], "midi")

    def test_midi_replay_requires_explicit_hardware_write_flag(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trace.jsonl"
            MidiTrace("fixture", ()).write(path)
            result = subprocess.run(
                [sys.executable, "-m", "midi_lab.cli", "replay", str(path), "--output", "MIDI4x4"],
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--send", result.stderr)
