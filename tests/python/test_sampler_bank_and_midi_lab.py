from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import patch

import mido

from drum_sampler import CaptureRequest, CaptureSessionPlan, SampleLibrary, analyze_wav, capture_pending, export_drumgizmo, library_from_captures, library_from_plan
from ddrum4_bank.ddrum4ui import encoded_block_count
from ddrum4_bank.ddrum4edit_backend import Ddrum4EditBackend
from ddrum4_bank.backup import inspect_settings_backup, validate_settings_backup
from ddrum4_bank.allocator import AllocationOption, compare_allocations
from ddrum4_bank.plan import compare_plan, render_comparison
from ddrum4_bank.nested import NestedRoute, NestedSound
from ddrum4_bank.routing_contract import ContractRoute, RoutingContract
from midi_lab import MidiTrace, TraceEvent, resolve_unique_port
from ddrum4_bank.transport import resolve_port, send_midi_file
from ddrum4_bank.b0 import B0Fixture, verify_b0_build, write_fixture_manifest
from ddrum4_bank.compiler import compile_nested, compile_nested_file, write_compilation
from ddrum4_bank.selection import select_snare, select_velocity_layers
from drum_sampler.library import SampleTake
from drum_domain import validate_document


class SamplerBankAndMidiLabTests(unittest.TestCase):
    def test_midi_sound_transfer_uses_observed_ddrum4ui_sysex_pacing(self) -> None:
        class Output:
            def __init__(self) -> None:
                self.sent: list[mido.Message] = []

            def __enter__(self) -> "Output":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def send(self, message: mido.Message) -> None:
                self.sent.append(message)

        class SoundFile:
            tracks: list[object] = []

            def play(self, *, meta_messages: bool) -> list[mido.Message]:
                assert not meta_messages
                return [mido.Message("sysex", data=(1, 2, 3)), mido.Message("sysex", data=(4, 5, 6))]

        with tempfile.TemporaryDirectory() as temporary:
            sound = Path(temporary) / "fixture.mid"
            sound.touch()
            output = Output()
            with patch("ddrum4_bank.transport.mido.get_output_names", return_value=["fixture-out"]), \
                 patch("ddrum4_bank.transport.mido.open_output", return_value=output), \
                 patch("ddrum4_bank.transport.mido.MidiFile", return_value=SoundFile()), \
                 patch("ddrum4_bank.transport.mido.merge_tracks", return_value=[mido.Message("sysex", data=(1, 2, 3)), mido.Message("sysex", data=(4, 5, 6))]), \
                 patch("ddrum4_bank.transport.time.sleep") as sleep:
                self.assertEqual(send_midi_file(sound, "fixture-out"), 2)
            self.assertEqual(len(output.sent), 2)
            self.assertEqual(sleep.call_count, 2)
            sleep.assert_called_with(0.4)

    def test_capture_grid_is_dense_and_resumable(self) -> None:
        request = CaptureRequest("snare_main", "head", 38, (16, 64, 127), 2)
        plan = CaptureSessionPlan("out_APC", "loopback", ("left", "right"), (request,))
        self.assertEqual(len(plan.takes()), 6)
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary)
            first = plan.takes()[0]
            (raw / first.raw_filename()).touch()
            self.assertEqual(len(plan.incomplete_takes(raw)), 5)

    def test_capture_session_round_trip_and_cli_write_protection(self) -> None:
        request = CaptureRequest("snare_main", "head", 38, (32, 127), 2)
        plan = CaptureSessionPlan("out_APC", "loopback", ("left", "right"), (request,))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "session.json"
            plan.write(path)
            self.assertEqual(CaptureSessionPlan.read(path), plan)
            validate_document(plan.to_document(), Path(__file__).resolve().parents[2] / "contracts/schemas/capture-session.schema.json")
            result = subprocess.run(
                [sys.executable, "-m", "drum_sampler.cli", "capture", "--session", str(path), "--raw-directory", temporary, "--library-output", str(Path(temporary) / "library.json"), "--id", "fixture", "--source", "test", "--license", "test"],
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--confirm-capture", result.stderr)

    def test_neutral_sample_library_round_trip(self) -> None:
        request = CaptureRequest("snare_main", "head", 38, (64,), 2)
        library = library_from_plan("sd3-metalcore", ("left", "right"), CaptureSessionPlan("out_APC", "loopback", ("left", "right"), (request,)).takes())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "library.json"
            library.write(path)
            self.assertEqual(SampleLibrary.read(path), library)
            validate_document(library.to_document(), Path(__file__).resolve().parents[2] / "contracts/schemas/sample-library.schema.json")

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

    def test_drumgizmo_export_creates_valid_stereo_or_multichannel_xml(self) -> None:
        import numpy as np
        from scipy.io import wavfile
        requests = (CaptureRequest("kick_main", "head", 36, (64,), 1), CaptureRequest("snare_main", "head", 38, (64,), 1))
        session = CaptureSessionPlan("fixture-midi", "fixture-audio", ("kick", "snare", "left", "right"), requests, tail_ms=10)
        def fake_capture(**kwargs: object) -> Path:
            output = kwargs["output"]
            assert isinstance(output, Path)
            wavfile.write(output, 44100, np.zeros((8, 4), dtype=np.int16))
            return output
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture_pending(session, root, capture=fake_capture)
            library = library_from_captures("fixture", session, root, source="test", license_statement="user-owned")
            export = export_drumgizmo(library, audio_root=root, output_directory=root / "kit")
            self.assertTrue(export.drumkit.is_file())
            self.assertTrue(export.midimap.is_file())
            self.assertEqual(len(export.instruments), 2)
            self.assertEqual(len(export.copied_audio), 2)
            self.assertIn('samplerate="44100"', export.drumkit.read_text(encoding="utf-8"))
            self.assertIn('note="38"', export.midimap.read_text(encoding="utf-8"))

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

    def test_allocator_compares_quality_and_compact_candidates(self) -> None:
        options = (
            AllocationOption("snare-full", "snare.head", "SNRE_801", 10, 100, 7, 7, 700, ("s1",)),
            AllocationOption("snare-compact", "snare.head", "SNRE_801", 6, 100, 4, 4, 350, ("s1",)),
            AllocationOption("crash-full", "crash_1.bow", "CYMB_801", 10, 90, 5, 4, 500, ("c1",)),
            AllocationOption("crash-compact", "crash_1.bow", "CYMB_801", 5, 90, 3, 2, 240, ("c1",)),
        )
        quality, compact = compare_allocations(options, 950)
        self.assertEqual([option.identifier for option in quality.selected], ["snare-full", "crash-compact"])
        self.assertEqual([option.identifier for option in compact.selected], ["snare-compact", "crash-compact"])
        self.assertTrue(any("reduced quality" in warning for warning in quality.warnings))

    def test_metalcore_plan_is_editable_and_compares_two_allocations(self) -> None:
        root = Path(__file__).resolve().parents[2]
        results = compare_plan(root / "profiles/banks/metalcore-main.yaml")
        self.assertEqual([result.strategy for result in results], ["quality-first", "compact-first"])
        self.assertGreater(results[0].estimated_blocks, results[1].estimated_blocks)
        self.assertIn("snare_main.head", render_comparison(results))

    def test_backend_block_parser_is_retained(self) -> None:
        self.assertEqual(encoded_block_count("Total Blocks Count : 00 0C (12)"), 12)

    def test_backend_refuses_unverified_sound_build_invocation(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "intentionally disabled"):
            Ddrum4EditBackend(Path("ddrum4edit.exe")).build(Path("input.cfg"), Path("output.mid"))

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
            inspection = inspect_settings_backup(path)
            self.assertEqual(inspection.message_types, {"sysex": 1})
            self.assertEqual(inspection.sysex_data_lengths, (3,))
            self.assertEqual(inspection.sysex_prefixes, {"01 02 03": 1})
            self.assertEqual(inspection.repeated_message_sequence_count, 1)

    def test_settings_backup_inspection_detects_repeated_message_sequence(self) -> None:
        import mido
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "repeated.mid"
            midi = mido.MidiFile(type=0)
            track = mido.MidiTrack()
            for _ in range(2):
                track.append(mido.Message("sysex", data=(1, 2, 3)))
                track.append(mido.Message("sysex", data=(4, 5, 6)))
            midi.tracks.append(track)
            midi.save(path)
            self.assertEqual(inspect_settings_backup(path).repeated_message_sequence_count, 2)

    def test_ddrum4_port_resolution_prefers_exact_name(self) -> None:
        self.assertEqual(
            resolve_port(["MIDI4x4 30", "MIDIIN2 (MIDI4x4) 31", "MIDI4x4"], "MIDI4x4"),
            "MIDI4x4",
        )
        self.assertEqual(
            resolve_port(["MIDI4x4 30", "MIDIIN2 (MIDI4x4) 31"], "MIDI4x4 30"),
            "MIDI4x4 30",
        )

    def test_b0_fixture_is_deterministic_pcm_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wav = root / "b0.wav"
            manifest = root / "b0.json"
            document = write_fixture_manifest(B0Fixture(), wav, manifest)
            self.assertTrue(wav.is_file())
            self.assertEqual(document["audio"]["channels"], 1)
            self.assertFalse(document["hardware_write"])
            self.assertEqual(len(str(document["sha256"])), 64)
            with self.assertRaises(FileExistsError):
                write_fixture_manifest(B0Fixture(), wav, root / "other.json")

    def test_b0_build_record_requires_intact_fixture_and_nonempty_midi(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wav = root / "b0.wav"
            fixture = root / "b0.json"
            write_fixture_manifest(B0Fixture(), wav, fixture)
            sound = root / "KICK_999.mid"
            sound.write_bytes(b"MThd")
            record = verify_b0_build(fixture, sound, 10)
            self.assertEqual(record.encoded_blocks, 10)
            self.assertFalse(record.to_document()["hardware_transfer"])
            record.write(root / "record.json")
            wav.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "matches"):
                verify_b0_build(fixture, sound, 10)

    def test_nested_compiler_generates_contract_and_rejects_impossible_layout(self) -> None:
        root = Path(__file__).resolve().parents[2]
        compilation = compile_nested_file(root / "profiles/banks/nested-compiler-fixture.yaml")
        self.assertEqual(compilation.contract.routes[0].output_note, 38)
        self.assertEqual(compilation.contract.routes[1].position, 2)
        validate_document(compilation.contract.to_document(), root / "contracts/schemas/routing-contract.schema.json")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            write_compilation(compilation, output / "routing-contract.json", output / "coverage.md")
            self.assertIn("SNRE_801", (output / "coverage.md").read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                write_compilation(compilation, output / "routing-contract.json", output / "other.md")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = subprocess.run([
                sys.executable, "-m", "ddrum4_bank.cli", "compile-nested", str(root / "profiles/banks/nested-compiler-fixture.yaml"),
                "--routing-contract", str(output / "routing-contract.json"), "--report", str(output / "coverage.md"),
                "--firmware-header", str(output / "generated_mapping.h"),
            ], text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("SNRE_801", (output / "generated_mapping.h").read_text(encoding="utf-8"))
        bad = {
            "bank": {"id": "bad"}, "midi": {"ddrum_output_channel": 10, "sources": {"ddti": {"channel": 10}}}, "sounds": [{"id": "CYMB_801", "output_note": 49, "note_p": 2, "routes": [
                {"id": "a", "source": "ddti", "input_note": 49, "position": 1, "sample_slots": 6, "layers": 5},
                {"id": "b", "source": "ddti", "input_note": 50, "position": 1, "sample_slots": 5, "layers": 6},
            ]}],
        }
        with self.assertRaisesRegex(ValueError, "nested positions must be unique"):
            compile_nested(bad)

    def test_snare_selector_spreads_captured_velocity_layers_and_requires_provenance(self) -> None:
        def take(articulation: str, velocity: int) -> SampleTake:
            return SampleTake("snare_main", articulation, 38, 10, velocity, 1, f"{articulation}-{velocity}.wav", source="user-owned SD3 render", license_statement="user-owned render", status="captured", sha256=f"{velocity:064x}")
        library = SampleLibrary("dense-snare", ("left", "right"), tuple(
            [take("head", velocity) for velocity in range(8, 129, 8)] + [take("rim", velocity) for velocity in (32, 112)]
        ))
        selected = select_snare(library)
        self.assertEqual([layer.velocity for layer in selected.head], [8, 24, 48, 72, 88, 104, 128])
        self.assertEqual([layer.velocity for layer in selected.rim], [32, 112])
        self.assertEqual(selected.accent.velocity, 128)
        self.assertEqual(selected.to_document()["sample_slots"], 10)
        self.assertTrue(selected.warnings)
        unlicensed = SampleLibrary("bad", ("left",), (SampleTake("snare_main", "head", 38, 10, 64, 1, "bad.wav", status="captured"),))
        with self.assertRaisesRegex(ValueError, "provenance"):
            select_velocity_layers(unlicensed, "snare_main", "head", 1)

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
        validate_document(document, root / "contracts/schemas/routing-contract.schema.json")
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
