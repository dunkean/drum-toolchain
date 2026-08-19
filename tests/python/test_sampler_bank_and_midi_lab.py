from pathlib import Path
import tempfile
from hashlib import sha256
import unittest
import subprocess
import sys
from unittest.mock import patch

import mido

from drum_sampler import CaptureRequest, CaptureSessionPlan, SampleLibrary, analyze_wav, capture_pending, export_drumgizmo, library_from_captures, library_from_plan
from ddrum4_bank.ddrum4ui import encoded_block_count
from ddrum4_bank.ddrum4edit_backend import Ddrum4EditBackend, _declared_output
from ddrum4_bank.sound_config import cymbal_velocity_layers, materialize_sound_config, positional_snare_layers, snare_velocity_layers
from ddrum4_bank.actual_bank import report_actual_bank
from ddrum4_bank.backup import inspect_settings_backup, validate_settings_backup
from ddrum4_bank.allocator import AllocationOption, compare_allocations
from ddrum4_bank.plan import compare_plan, render_comparison
from ddrum4_bank.nested import NestedRoute, NestedSound
from ddrum4_bank.routing_contract import ContractRoute, RoutingContract
from midi_lab import MidiTrace, TraceEvent, decode_ddrum4_program, program_for_kit, program_for_palette, resolve_unique_port
from midi_lab.cli import _message_from_trace, _trace_event
from ddrum4_bank.transport import resolve_port, send_midi_file
from ddrum4_bank.b0 import B0Fixture, verify_b0_build, write_fixture_manifest
from ddrum4_bank.hardware import transfer_one_sound
from ddrum4_bank.render_compare import compare_renders
from ddrum4_bank.compiler import compile_nested, compile_nested_file, write_compilation
from ddrum4_bank.selection import select_snare, select_velocity_layers
from ddrum4_bank.cymbal_build import materialize_flagship_cymbal
from ddrum4_bank.snare_build import materialize_positional_snare
from drum_sampler.audio import QualityProfile
from drum_sampler.library import SampleTake, merge_libraries
from drum_domain import validate_document


class SamplerBankAndMidiLabTests(unittest.TestCase):
    def test_flagship_cymbal_preparation_selects_best_round_robin(self) -> None:
        import numpy as np
        from scipy.io import wavfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            for name in ("first.wav", "best.wav", "hard.wav"):
                wavfile.write(raw / name, 44100, np.tile(np.linspace(0, 0.5, 4410, dtype=np.float32)[:, None], (1, 2)))
            def take(name: str, velocity: int, repetition: int, peak: float) -> SampleTake:
                return SampleTake("crash", "bow", 49, 10, velocity, repetition, name,
                                  source="local render", license_statement="personal", status="captured", peak_dbfs=peak)
            library = SampleLibrary("crash-library", ("left", "right"), (
                take("first.wav", 56, 1, -6.0), take("best.wav", 56, 2, -3.0),
                take("hard.wav", 127, 1, -1.0),
            ))
            template = root / "template.cfg"
            template.write_text(
                "-Begin-Layers-\nold\n-End-Layers-\n-Begin-Variations-\nVL1 old\n-End-Variations-\n"
                "-Begin-Sample-Files-\nold\n-End-Sample-Files-\n-Begin-Sample-Name-\nold\n-End-Sample-Name-\n"
                "-Begin-Sound-File-Out-\nold.mid\n-End-Sound-File-Out-\n", encoding="utf-8")
            build = materialize_flagship_cymbal(
                library, raw_directory=raw, output_directory=root / "build", sound_id="CYMB_777",
                instrument="crash", template=template,
                profile=QualityProfile(trim_threshold_db=-80, force_mono=True, max_duration_seconds=0.05),
                velocities=(56,),
            )
            self.assertEqual(build.layers[0].raw_file, "best.wav")
            self.assertEqual(build.layers[0].channels, 1)
            self.assertTrue(build.config.is_file())
            self.assertTrue((root / "build" / "CYMB_777_s01.wav").is_file())

    def test_cymbal_builder_refuses_unreviewed_partial_velocity_layout(self) -> None:
        with self.assertRaisesRegex(ValueError, "no audited DDrum4 cymbal velocity layout"):
            cymbal_velocity_layers(4)
        single = cymbal_velocity_layers(1)
        self.assertEqual(len(single), 1)
        # A one-layer cymbal must respond at the panel's hard velocity too.
        self.assertEqual(single[0].split()[4:12], ["FF"] * 8)
        self.assertEqual(len(cymbal_velocity_layers(7)), 7)

    def test_positional_snare_layout_covers_every_velocity_and_position_zone_once(self) -> None:
        rows = [row.split() for row in positional_snare_layers()]
        self.assertEqual(len(rows), 10)
        self.assertEqual([row[0] for row in rows], [f"{index:02X}" for index in range(10)])
        for position_zone in range(8):
            for velocity_zone in range(8):
                active = [
                    row for row in rows
                    if row[4 + velocity_zone] == "FF" and row[12 + position_zone] == "FF"
                ]
                self.assertEqual(len(active), 1)

    def test_positional_snare_builder_selects_two_positions_by_five_velocities(self) -> None:
        import numpy as np
        from scipy.io import wavfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            takes = []
            for position in ("head_position_000", "head_position_127"):
                for velocity in (24, 48, 72, 96, 120):
                    name = f"{position}_{velocity}.wav"
                    wavfile.write(raw / name, 44100, np.linspace(0, 0.4, 1000, dtype=np.float32))
                    takes.append(SampleTake(
                        "snare_main", position, 38, 10, velocity, 1, name,
                        source="local render", license_statement="personal", status="captured", peak_dbfs=-3.0,
                    ))
            library = SampleLibrary("position-fixture", ("mono",), tuple(takes))
            template = root / "template.cfg"
            template.write_text(
                "-Begin-Layers-\nold\n-End-Layers-\n-Begin-Variations-\nVL1 old\n-End-Variations-\n"
                "-Begin-Sample-Files-\nold\n-End-Sample-Files-\n-Begin-Sample-Name-\nold\n-End-Sample-Name-\n"
                "-Begin-Sound-File-Out-\nold.mid\n-End-Sound-File-Out-\n", encoding="utf-8"
            )
            build = materialize_positional_snare(
                library,
                raw_directory=raw,
                output_directory=root / "build",
                sound_id="SNRE_950",
                instrument="snare_main",
                positions=("head_position_000", "head_position_127"),
                velocities=(24, 48, 72, 96, 120),
                template=template,
                profile=QualityProfile(force_mono=True, max_duration_seconds=0.05),
            )
            self.assertEqual(len(build.layers), 10)
            self.assertEqual(build.layers[0].position, "head_position_000")
            self.assertEqual(build.layers[-1].position, "head_position_127")
            self.assertIn("VL1 01 01 01 01 01 01 01 01 01 01", build.config.read_text(encoding="utf-8"))

    def test_render_comparison_measures_onset_level_tail_and_tone(self) -> None:
        import numpy as np
        from scipy.io import wavfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = np.concatenate((np.zeros(10), np.linspace(1, 0, 90))).astype(np.float32)
            module = np.concatenate((np.zeros(20), np.linspace(0.5, 0, 90))).astype(np.float32)
            wavfile.write(root / "source.wav", 44100, source)
            wavfile.write(root / "module.wav", 44100, module)
            comparison = compare_renders(root / "source.wav", root / "module.wav")
            self.assertAlmostEqual(comparison.onset_delta_ms, 10 / 44.1, places=3)
            self.assertLess(comparison.module_minus_source_peak_db, -5.9)
            self.assertLess(comparison.module_pre_onset_rms_dbfs, -100)

    def test_hardware_transfer_requires_confirmation_and_receipt_follows_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sound = Path(temporary) / "fixture.mid"
            sound.write_bytes(b"MThd")
            with self.assertRaisesRegex(ValueError, "hardware write refused"):
                transfer_one_sound(sound, "fixture-out", confirmed=False, sound_id="RIM_999")
            with patch("ddrum4_bank.hardware.send_midi_file", return_value=11) as sender:
                receipt = transfer_one_sound(sound, "fixture-out", confirmed=True, sound_id="RIM_999", sysex_chunk_bytes=255)
            self.assertEqual(receipt.messages_sent, 11)
            self.assertEqual(receipt.sound_id, "RIM_999")
            self.assertEqual(receipt.sysex_chunk_bytes, 255)
            self.assertEqual(sender.call_args.args[:3], (sound, "fixture-out", 0.4))
            receipt_path = Path(temporary) / "receipt.json"
            receipt.write(receipt_path)
            self.assertIn('"messages_sent": 11', receipt_path.read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                receipt.write(receipt_path)

    def test_midi_sound_transfer_routes_an_all_sysex_file_to_native_sender(self) -> None:
        class SoundFile:
            tracks: list[object] = []

            def play(self, *, meta_messages: bool) -> list[mido.Message]:
                assert not meta_messages
                return [mido.Message("sysex", data=(1, 2, 3)), mido.Message("sysex", data=(4, 5, 6))]

        with tempfile.TemporaryDirectory() as temporary:
            sound = Path(temporary) / "fixture.mid"
            sound.touch()
            with patch("ddrum4_bank.transport.mido.get_output_names", return_value=["fixture-out"]), \
                 patch("ddrum4_bank.transport.mido.MidiFile", return_value=SoundFile()), \
                 patch("ddrum4_bank.transport.mido.merge_tracks", return_value=[mido.Message("sysex", data=(1, 2, 3)), mido.Message("sysex", data=(4, 5, 6))]), \
                 patch("ddrum4_bank.transport._send_sysex_messages", return_value=2) as native_sender:
                self.assertEqual(send_midi_file(sound, "fixture-out"), 2)
            sent_messages, sent_name, sent_pause = native_sender.call_args.args
            self.assertEqual([message.type for message in sent_messages], ["sysex", "sysex"])
            self.assertEqual(sent_name, "fixture-out")
            self.assertEqual(sent_pause, 0.4)
            self.assertEqual(native_sender.call_args.kwargs, {"sysex_chunk_bytes": None, "sysex_chunk_pause": 0.0})

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
        request = CaptureRequest("snare_main", "head", 38, (32, 127), 2, controllers=((16, 64),))
        plan = CaptureSessionPlan("out_APC", "loopback", ("left", "right"), (request,))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "session.json"
            plan.write(path)
            self.assertEqual(CaptureSessionPlan.read(path), plan)
            self.assertEqual(CaptureSessionPlan.read(path).requests[0].controllers, ((16, 64),))
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
            self.assertEqual(kwargs["controllers"], ())
            wavfile.write(output, 44100, np.zeros((8, 4), dtype=np.int16))
            return output
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary)
            with patch("drum_sampler.recorder.time.sleep") as cooldown:
                self.assertEqual(len(capture_pending(session, raw, capture=fake_capture)), 2)
            cooldown.assert_called_once_with(session.cooldown_ms / 1000)
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

    def test_drumgizmo_export_allows_target_note_overrides_for_merged_sources(self) -> None:
        import numpy as np
        from scipy.io import wavfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wavfile.write(root / "closed.wav", 44100, np.zeros((8, 2), dtype=np.int16))
            wavfile.write(root / "open.wav", 44100, np.zeros((8, 2), dtype=np.int16))
            common = dict(channel=10, velocity=90, repetition=1, sample_rate=44100,
                          channels=("left", "right"), frames=8, status="captured")
            library = SampleLibrary("hat-fixture", ("left", "right"), (
                SampleTake("hi_hat", "closed", 42, raw_file="closed.wav", **common),
                SampleTake("hi_hat", "open", 42, raw_file="open.wav", **common),
            ))
            with self.assertRaisesRegex(ValueError, "MIDI note 42 maps"):
                export_drumgizmo(library, audio_root=root, output_directory=root / "conflict")
            export = export_drumgizmo(
                library, audio_root=root, output_directory=root / "kit",
                midi_notes={("hi_hat", "closed"): 42, ("hi_hat", "open"): 46},
            )
            map_text = export.midimap.read_text(encoding="utf-8")
            self.assertIn('note="42" instr="hi_hat__closed"', map_text)
            self.assertIn('note="46" instr="hi_hat__open"', map_text)

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

    def test_backend_reads_internal_group_and_number_sound_id(self) -> None:
        backend = Ddrum4EditBackend(Path("fixture-ddrum4edit.exe"))
        with patch.object(Ddrum4EditBackend, "inspect", return_value="Sound Name : 52 49 (RIM_999) Total Blocks Count"):
            self.assertEqual(backend.sound_id(Path("ignored.mid")), "RIM_999")

    def test_backend_reads_declared_build_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "fixture.cfg"
            config.write_text(
                "-Begin-Sound-File-Out-\nresult.mid\n-End-Sound-File-Out-\n",
                encoding="utf-8",
            )
            self.assertEqual(_declared_output(config), root / "result.mid")

    def test_backend_rejects_mismatched_or_missing_build_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "fixture.cfg"
            config.write_text(
                "-Begin-Sound-File-Out-\nactual.mid\n-End-Sound-File-Out-\n",
                encoding="utf-8",
            )
            backend = Ddrum4EditBackend(Path("ddrum4edit.exe"))
            with self.assertRaisesRegex(RuntimeError, "configuration declares output"):
                backend.build(config, root / "other.mid")

    def test_snare_config_materializes_velocity_crossfade_without_source_paths(self) -> None:
        self.assertEqual(len(snare_velocity_layers(7)), 7)
        with self.assertRaisesRegex(ValueError, "1..7"):
            snare_velocity_layers(8)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "template.cfg"
            template.write_text(
                "-Begin-Layers-\nold\n-End-Layers-\n"
                "-Begin-Variations-\nVL1 old\n-End-Variations-\n"
                "-Begin-Sample-Files-\nold\n-End-Sample-Files-\n"
                "-Begin-Sample-Name-\nold\n-End-Sample-Name-\n"
                "-Begin-Sound-File-Out-\nold.mid\n-End-Sound-File-Out-\n",
                encoding="utf-8",
            )
            config = materialize_sound_config(
                template,
                root / "SNRE_999.cfg",
                sound_name="SNRE_999",
                output_sound=root / "SNRE_999.mid",
                sample_files=("SNRE_999_s01.wav", "SNRE_999_s02.wav"),
                layer_rows=snare_velocity_layers(2),
            )
            text = config.read_text(encoding="utf-8")
            self.assertIn("L01 00 00 02", text)
            self.assertIn("L02 01 00 02", text)
            self.assertIn("VL1 01 01 00", text)
            self.assertIn("S02 SNRE_999_s02.wav", text)
            self.assertNotIn("sample-library", text)

    def test_actual_bank_report_uses_encoded_counts_and_rejects_duplicate_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "SNRE_998.mid"
            second = root / "KICK_997.mid"
            first.write_bytes(b"snare")
            second.write_bytes(b"kick")
            report = report_actual_bank(1270, ((first, 94), (second, 124)))
            self.assertTrue(report.fits)
            self.assertEqual(report.used_blocks, 218)
            self.assertEqual(report.remaining_blocks, 1052)
            self.assertEqual(report.to_document()["sounds"][0]["bytes"], 5)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                report_actual_bank(100, ((first, 1), (first, 1)))

    def test_neutral_libraries_merge_without_moving_audio(self) -> None:
        take = SampleTake("kick", "main", 36, 10, 100, 1, "raw.wav", status="captured")
        first = SampleLibrary("first", ("left", "right"), (take,))
        second = SampleLibrary("second", ("left", "right"), (take,))
        merged = merge_libraries("merged", ((first, "core/raw"), (second, "snare/raw")))
        self.assertEqual([take.raw_file for take in merged.takes], ["core/raw/raw.wav", "snare/raw/raw.wav"])
        incompatible = SampleLibrary("bad", ("mono",), (take,))
        with self.assertRaisesRegex(ValueError, "same channel layout"):
            merge_libraries("bad", ((first, "core"), (incompatible, "bad")))

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
        centre_library = SampleLibrary("centre-snare", ("left", "right"), tuple(
            [take("head_center", velocity) for velocity in range(16, 128, 16)]
            + [take("rimshot", velocity) for velocity in (40, 120)]
            + [take("cross_stick", velocity) for velocity in (48, 100)]
        ))
        centre_selected = select_snare(centre_library)
        self.assertEqual([layer.velocity for layer in centre_selected.head], [16, 32, 48, 64, 80, 96, 112])
        self.assertEqual(centre_selected.accent.velocity, 100)
        self.assertIn("head_center", centre_selected.warnings[0])
        self.assertIn("rimshot", centre_selected.warnings[1])
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
            generated = output_path.read_text(encoding="utf-8")
            self.assertIn("{10, 38, 40, 1, 127, 1, 127}", generated)
            self.assertIn(sha256(input_path.read_bytes()).hexdigest(), generated)

    def test_trace_round_trip_and_unique_port_matching(self) -> None:
        trace = MidiTrace("edrumin", (
            TraceEvent(0, "note_on", 11, 42, 100),
            TraceEvent(4, "program_change", 11, 106, None),
        ))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trace.jsonl"
            trace.write(path)
            self.assertEqual(MidiTrace.read(path), trace)
        self.assertEqual(resolve_unique_port(["MIDI4x4", "MIDIOUT2 (MIDI4x4)"], "MIDI4x4"), "MIDI4x4")
        with self.assertRaises(ValueError):
            resolve_unique_port(["MIDI4x4", "MIDIOUT2 (MIDI4x4)"], "midi")

    def test_ddrum4_program_contract_covers_kits_and_all_palette_groups(self) -> None:
        self.assertEqual(decode_ddrum4_program(0).label, "P.1")
        self.assertEqual(decode_ddrum4_program(98).label, "F.99")
        self.assertEqual(decode_ddrum4_program(99).label, "PAL")
        self.assertEqual(decode_ddrum4_program(100).label, "kick palette 1")
        self.assertEqual(decode_ddrum4_program(110).label, "snare palette 5")
        self.assertEqual(decode_ddrum4_program(117).label, "toms palette off")
        self.assertEqual(decode_ddrum4_program(122).label, "percussion palette 5")
        self.assertEqual(program_for_kit(26), 25)
        self.assertEqual(program_for_palette("snare", 3), 108)
        self.assertEqual(program_for_palette("percussion", None), 123)
        message = mido.Message("program_change", channel=11, program=108)
        event = _trace_event(message, 17)
        self.assertEqual(event, TraceEvent(17, "program_change", 12, 108, None))
        self.assertEqual(_message_from_trace(mido, event), message)

    def test_ddrum4_program_sender_requires_explicit_write_flag(self) -> None:
        result = subprocess.run(
            [
                sys.executable, "-m", "midi_lab.cli", "send-ddrum4-program",
                "--output", "UMC404HD", "--channel", "12", "--program", "108",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--send", result.stderr)

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
