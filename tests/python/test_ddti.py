import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


DDTI_SOURCE = Path(__file__).resolve().parents[2] / "apps" / "ddti" / "src"
if str(DDTI_SOURCE) not in sys.path:
    sys.path.insert(0, str(DDTI_SOURCE))

from ddti.capture import CaptureResult, _WINDOWS_SYSEX_BUFFER_COUNT, _receive_mido_sysex, capture_dump, capture_series
from ddti.device import DDTi, ProtocolNotValidatedError
from ddti.cli import main
from ddti.models import decode_configuration, encode_configuration
from ddti.protocol import decode_dump
from ddti.diff import diff_bytes, diff_files, render_diff
from ddti.sysex import SysExMessage, parse_stream, render_hex


class _InputPort:
    def __init__(self, messages):
        self.messages = messages

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_pending(self):
        messages, self.messages = self.messages, []
        return messages


class DDTiTests(unittest.TestCase):
    def test_sysex_parser_preserves_complete_concatenated_frames(self) -> None:
        raw = bytes.fromhex("F0 01 02 F7 F0 7F F7")
        messages = parse_stream(raw)
        self.assertEqual(tuple(message.raw for message in messages), (bytes.fromhex("F0 01 02 F7"), bytes.fromhex("F0 7F F7")))
        self.assertIn("000004: F0 7F F7", render_hex(messages))
        with self.assertRaisesRegex(ValueError, "unterminated"):
            parse_stream(bytes.fromhex("F0 01"))
        with self.assertRaisesRegex(ValueError, "7-bit"):
            SysExMessage(bytes.fromhex("F0 80 F7"))

    def test_offline_diff_identifies_only_changed_offsets(self) -> None:
        changes = diff_bytes(bytes.fromhex("F0 01 02 F7"), bytes.fromhex("F0 01 03 F7"))
        self.assertEqual(changes[0].offset, 2)
        self.assertIn("Offset 0x000002", render_diff(changes))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, after = root / "a.syx", root / "b.syx"
            before.write_bytes(bytes.fromhex("F0 01 F7"))
            after.write_bytes(bytes.fromhex("F0 02 F7"))
            # Generic malformed-to-DDTi framing is intentionally rejected by the DDTi-aware file diff.
            with self.assertRaisesRegex(ValueError, "too short|manufacturer"):
                diff_files(before, after)
            before.write_bytes(bytes.fromhex("F0 00 00 0E 2C 0D 00 00 0A 01 00 01 F7"))
            after.write_bytes(bytes.fromhex("F0 00 00 0E 2C 0D 00 00 0A 01 00 02 F7"))
            change = diff_files(before, after)[0]
            self.assertEqual(change.offset, 11)
            self.assertEqual(change.observed_packet_family, 1)
            self.assertIn("family 0x01", render_diff((change,)))
            before.write_bytes(bytes.fromhex("F0 00 00 0E 2C 0D 00 00 0A 01 00 00 00 00 00 00 00 01 F7"))
            after.write_bytes(bytes.fromhex("F0 00 00 0E 2C 0D 00 00 0A 01 00 00 00 00 00 00 00 02 F7"))
            self.assertIn("opaque body byte +0x06", render_diff(diff_files(before, after)))

    def test_capture_writes_hashed_triad_without_overwriting(self) -> None:
        import mido
        with tempfile.TemporaryDirectory() as temporary:
            stem = Path(temporary) / "factory_dump_001"
            messages = [SysExMessage(bytes(mido.Message("sysex", data=(1, 2, 3)).bytes()))]
            with patch("ddti.capture._resolve_input", return_value="TriggerIO 30"), \
                 patch("ddti.capture.platform.system", return_value="not-windows"), \
                 patch("ddti.capture._receive_mido_sysex", return_value=messages):
                result = capture_dump("TriggerIO", stem, seconds=1, idle_seconds=1)
            self.assertEqual(result.message_count, 1)
            self.assertTrue(result.syx_path.is_file())
            self.assertTrue(result.hex_path.is_file())
            self.assertIn(result.sha256, result.metadata_path.read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                capture_dump("TriggerIO", stem, seconds=1, idle_seconds=1)

    def test_capture_can_force_the_independent_mido_receiver_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stem = Path(temporary) / "mido_check"
            with patch("ddti.capture._resolve_input", return_value="TriggerIO 30"), \
                 patch("ddti.capture.platform.system", return_value="Windows"), \
                 patch("ddti.capture._receive_mido_sysex", return_value=(SysExMessage(bytes.fromhex("F0 01 F7")),)) as receiver, \
                 patch("ddti.capture._receive_windows_sysex") as windows_receiver:
                capture_dump("TriggerIO", stem, seconds=1, idle_seconds=1, receiver="mido")
        receiver.assert_called_once_with("TriggerIO 30", seconds=1, idle_seconds=1)
        windows_receiver.assert_not_called()

    def test_windows_receiver_has_capacity_for_the_observed_full_dump(self) -> None:
        self.assertGreaterEqual(_WINDOWS_SYSEX_BUFFER_COUNT, 42)

    def test_capture_refuses_a_recognised_but_incomplete_ddti_dump(self) -> None:
        raw = bytes.fromhex("F0 00 00 0E 2C 0D 00 00 0A 01 00 01 F7")
        with tempfile.TemporaryDirectory() as temporary:
            stem = Path(temporary) / "partial"
            with patch("ddti.capture._resolve_input", return_value="TriggerIO 30"), \
                 patch("ddti.capture.platform.system", return_value="not-windows"), \
                 patch("ddti.capture._receive_mido_sysex", return_value=(SysExMessage(raw),)):
                with self.assertRaisesRegex(ValueError, "incomplete DDTi"):
                    capture_dump("TriggerIO", stem, seconds=1, idle_seconds=1)
            self.assertFalse(stem.with_suffix(".syx").exists())

    def test_capture_series_uses_new_numbered_stems_without_reopening_a_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = []
            def fake_capture(port: str, stem: Path, *, seconds: float, idle_seconds: float):
                results.append((port, stem, seconds, idle_seconds))
                return CaptureResult(port, "now", 1, 1, 3, "a" * 64, stem.with_suffix(".syx"), stem.with_suffix(".hex"), stem.with_suffix(".json"))
            announcements = []
            with patch("ddti.capture.capture_dump", side_effect=fake_capture):
                captured = capture_series("TriggerIO", root, label="notes", snapshots=2, seconds_per_snapshot=30, idle_seconds=2, on_listening=lambda number, stem: announcements.append((number, stem)))
            self.assertEqual([item[1].name for item in results], ["notes_001", "notes_002"])
            self.assertEqual([item[0] for item in announcements], [1, 2])
            self.assertEqual(len(captured), 2)
            with self.assertRaisesRegex(ValueError, "label"):
                capture_series("TriggerIO", root, label="bad label", snapshots=1, seconds_per_snapshot=1, idle_seconds=1)

    def test_session_cli_runs_offline_diffs_against_an_explicit_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "golden.syx"
            snapshot = root / "snapshot.syx"
            result = CaptureResult("TriggerIO 30", "now", 32, 32, 1836, "a" * 64, snapshot, root / "snapshot.hex", root / "snapshot.json")
            with patch("ddti.cli.capture_series", return_value=(result,)) as capture, \
                 patch("ddti.cli.diff_files", return_value=()) as comparison, \
                 patch("sys.stdout") as stdout:
                self.assertEqual(main([
                    "session", str(root / "session"), "--input", "TriggerIO", "--listen", "--snapshots", "1",
                    "--compare-to", str(baseline),
                ]), 0)
        capture.assert_called_once()
        comparison.assert_called_once_with(baseline, snapshot)
        output = "".join(str(call.args[0]) for call in stdout.write.call_args_list)
        self.assertIn("offline comparisons", output)
        self.assertIn("No byte differences", output)

    def test_portable_receiver_filters_non_sysex_events(self) -> None:
        import mido
        messages = [mido.Message("note_on", note=36, velocity=100), mido.Message("sysex", data=(1,))]
        with patch("ddti.capture.time.monotonic", side_effect=(0, 0, 0, 2)), \
             patch("mido.open_input", return_value=_InputPort(messages)):
            received = _receive_mido_sysex("TriggerIO", seconds=1, idle_seconds=1)
        self.assertEqual([frame.raw for frame in received], [bytes.fromhex("F0 01 F7")])

    def test_public_device_facade_has_a_non_bypassable_write_boundary(self) -> None:
        info = object()
        device = DDTi(info)  # type: ignore[arg-type]
        with self.assertRaises(ProtocolNotValidatedError):
            device.read_configuration()
        with self.assertRaises(ProtocolNotValidatedError):
            device.write_configuration(object())

    def test_dump_cli_announces_receive_only_listening_before_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, \
             patch("ddti.cli.capture_dump") as capture, \
             patch("sys.stdout") as stdout:
            capture.return_value = type("Result", (), {
                "syx_path": Path(temporary) / "dump.syx",
                "hex_path": Path(temporary) / "dump.hex",
                "metadata_path": Path(temporary) / "dump.json",
                "sha256": "a" * 64,
                "message_count": 1,
            })()
            self.assertEqual(main(["dump", str(Path(temporary) / "dump"), "--input", "TriggerIO", "--listen"]), 0)
        output = "".join(str(call.args[0]) for call in stdout.write.call_args_list)
        self.assertIn("never opens a MIDI output", output)

    def test_observed_packet_decoder_preserves_raw_stream_and_groups_families(self) -> None:
        first = bytes.fromhex("F0 00 00 0E 2C 0D 00 00 0A 01 00 01 F7")
        second = bytes.fromhex("F0 00 00 0E 2C 0D 00 00 0A 02 03 02 F7")
        dump = decode_dump(first + second)
        self.assertEqual(dump.raw, first + second)
        self.assertEqual(dump.family_indexes(), {1: (0,), 2: (3,)})
        self.assertEqual(dump.to_document()["packet_lengths"], {13: 2})
        with self.assertRaisesRegex(ValueError, "manufacturer"):
            decode_dump(bytes.fromhex("F0 01 02 03 2C 0D 00 00 0A 01 00 01 F7"))

    def test_note_model_uses_interleaved_tip_ring_records_and_is_lossless(self) -> None:
        body = bytearray()
        for zone in range(20):
            body.extend((9, 35 + zone, 3))
        body.extend(b"\x00" * 6)
        raw = bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, 0)) + bytes(body) + bytes((0xF7,))
        configuration = decode_configuration(decode_dump(raw))
        self.assertEqual(configuration.kits[0].inputs[0].tip.note, 35)
        self.assertEqual(configuration.kits[0].inputs[0].ring.note, 36)
        self.assertEqual(configuration.kits[0].inputs[1].tip.note, 37)
        self.assertEqual(encode_configuration(configuration), raw)
        edited = configuration.with_note(0, 2, "tip", 50)
        self.assertEqual(edited.kits[0].inputs[1].tip.note, 50)
        differences = diff_bytes(raw, encode_configuration(edited))
        self.assertEqual([(change.offset, change.before, change.after) for change in differences], [(18, 37, 50)])

    def test_note_presets_are_portable_subset_edits_and_never_touch_companion_bytes(self) -> None:
        packets = []
        for kit in range(2):
            body = bytearray()
            for zone in range(20):
                body.extend((9 + kit, 35 + zone + kit, 3))
            body.extend(b"\x00" * 6)
            packets.append(bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, kit)) + bytes(body) + bytes((0xF7,)))
        configuration = decode_configuration(decode_dump(b"".join(packets)))
        preset = configuration.to_note_preset()
        self.assertEqual(preset["format"], "ddti-note-preset/v1")
        self.assertEqual(len(preset["kits"]), 2)
        staged = configuration.with_note_preset({
            "format": "ddti-note-preset/v1",
            "kits": [{"kit": 1, "inputs": [{"input": 10, "ring_note": 64}]}],
        })
        self.assertEqual(staged.kits[0].inputs[9].ring.note, configuration.kits[0].inputs[9].ring.note)
        self.assertEqual(staged.kits[1].inputs[9].ring.note, 64)
        self.assertEqual(staged.kits[1].inputs[9].ring.channel_raw, configuration.kits[1].inputs[9].ring.channel_raw)
        with self.assertRaisesRegex(ValueError, "repeats kit"):
            configuration.with_note_preset({"format": "ddti-note-preset/v1", "kits": [{"kit": 0, "inputs": []}, {"kit": 0, "inputs": []}]})

    def test_preset_cli_exports_and_applies_to_a_new_staged_file(self) -> None:
        body = bytearray()
        for zone in range(20):
            body.extend((9, 35 + zone, 3))
        body.extend(b"\x00" * 6)
        raw = bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, 0)) + bytes(body) + bytes((0xF7,))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.syx"
            preset = root / "notes.json"
            staged = root / "staged.syx"
            source.write_bytes(raw)
            self.assertEqual(main(["export-preset", str(source), str(preset)]), 0)
            document = json.loads(preset.read_text(encoding="utf-8"))
            document["kits"][0]["inputs"][0]["tip_note"] = 60
            preset.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(main(["apply-preset", str(source), str(preset), str(staged)]), 0)
            result = decode_configuration(decode_dump(staged.read_bytes()))
            self.assertEqual(result.kits[0].inputs[0].tip.note, 60)
            with self.assertRaises(FileExistsError):
                main(["apply-preset", str(source), str(preset), str(staged)])

    def test_optional_fastapi_stages_notes_without_hardware_output(self) -> None:
        try:
            from fastapi.testclient import TestClient
            from ddti.api import create_app
        except ImportError:
            self.skipTest("FastAPI optional extra is not installed")
        body = bytearray()
        for zone in range(20):
            body.extend((9, 35 + zone, 3))
        body.extend(b"\x00" * 6)
        raw = bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, 0)) + bytes(body) + bytes((0xF7,))
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "fixture.syx"
            source.write_bytes(raw)
            client = TestClient(create_app(source))
            self.assertEqual(client.get("/configuration").status_code, 200)
            response = client.patch("/kits/0/inputs/1", json={"tip_note": 36})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["staged_only"])
            self.assertEqual(response.json()["hardware_write"], "disabled")
            self.assertEqual(client.get("/kits/0/inputs/1").json()["tip"]["note"], 36)
            preset = client.get("/preset")
            self.assertEqual(preset.status_code, 200)
            preset_document = preset.json()
            preset_document["kits"][0]["inputs"][0]["ring_note"] = 61
            response = client.put("/preset", json=preset_document)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["staged_only"])
            self.assertEqual(client.get("/kits/0/inputs/1").json()["ring"]["note"], 61)

    def test_optional_pyside_editor_starts_offscreen(self) -> None:
        try:
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            from ddti.gui import launch
        except ImportError:
            self.skipTest("PySide6 optional extra is not installed")
        body = bytearray()
        for zone in range(20):
            body.extend((9, 35 + zone, 3))
        body.extend(b"\x00" * 6)
        raw = bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, 0)) + bytes(body) + bytes((0xF7,))
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "fixture.syx"
            source.write_bytes(raw)
            application = QApplication.instance() or QApplication([])
            QTimer.singleShot(20, application.quit)
            self.assertEqual(launch(source), 0)
