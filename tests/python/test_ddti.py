from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


DDTI_SOURCE = Path(__file__).resolve().parents[2] / "apps" / "ddti" / "src"
if str(DDTI_SOURCE) not in sys.path:
    sys.path.insert(0, str(DDTI_SOURCE))

from ddti.capture import _receive_mido_sysex, capture_dump
from ddti.device import DDTi, ProtocolNotValidatedError
from ddti.cli import main
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
