import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


DDTI_SOURCE = Path(__file__).resolve().parents[2] / "apps" / "ddti" / "src"
if str(DDTI_SOURCE) not in sys.path:
    sys.path.insert(0, str(DDTI_SOURCE))

from ddti.capture import CaptureCancelled, CaptureResult, _WINDOWS_SYSEX_BUFFER_COUNT, _receive_mido_sysex, capture_dump, capture_series
from ddti.device import DDTi, ProtocolNotValidatedError
from ddti.cli import main
from ddti.models import VELOCITY_CURVE_LABELS, decode_configuration, encode_configuration
from ddti.mappings import apply_role_template
from ddti.monitor import observe_messages
from ddti.presets import load_document
from ddti.protocol import decode_dump
from ddti.diff import diff_bytes, diff_ddti_bytes, diff_files, render_diff
from ddti.sysex import SysExMessage, parse_stream, render_hex
from ddti.state import DDTiStateStore
from ddti.transfer import build_note_write_validation_plan, build_safe_write_plan, build_settings_write_validation_plan, build_transfer_plan, send_note_write_validation, send_reviewed_transfer, send_safe_configuration


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


class _OutputPort:
    def __init__(self) -> None:
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def send(self, message) -> None:
        self.messages.append(message)


class DDTiTests(unittest.TestCase):
    def test_documented_velocity_curve_codes_are_named(self) -> None:
        self.assertEqual(
            VELOCITY_CURVE_LABELS,
            {
                0: "Cst", 1: "OFF", 2: "E1", 3: "E2", 4: "E3", 5: "E4",
                6: "Lin", 7: "LG1", 8: "LG2", 9: "LG3", 10: "LG4",
                11: "SPL1", 12: "SPL2", 13: "SPL3", 14: "SPL4",
            },
        )

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
            self.assertIn("Input 2 Tip MIDI Channel (CONFIRMED; stored channel-1)", render_diff(diff_files(before, after)))
            self.assertEqual(diff_ddti_bytes(before.read_bytes(), after.read_bytes())[0].observed_packet_family, 1)

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
        receiver.assert_called_once_with("TriggerIO 30", seconds=1, idle_seconds=1, cancelled=None)
        windows_receiver.assert_not_called()

    def test_capture_cancellation_publishes_no_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stem = Path(temporary) / "cancelled"
            with patch("ddti.capture._resolve_input", return_value="TriggerIO 30"), \
                 patch("ddti.capture.platform.system", return_value="not-windows"), \
                 patch("ddti.capture._receive_mido_sysex", return_value=[]):
                with self.assertRaises(CaptureCancelled):
                    capture_dump(
                        "TriggerIO",
                        stem,
                        seconds=1,
                        idle_seconds=1,
                        cancelled=lambda: True,
                    )
            self.assertFalse(stem.with_suffix(".syx").exists())
            self.assertFalse(stem.with_suffix(".hex").exists())
            self.assertFalse(stem.with_suffix(".json").exists())

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

    def test_live_observer_streams_midi_records_and_stops_cleanly(self) -> None:
        import mido
        records = []
        cancellations = iter((False, True))
        messages = [
            mido.Message("note_on", channel=9, note=38, velocity=112),
            mido.Message("control_change", channel=9, control=4, value=63),
        ]
        with patch("ddti.monitor._resolve_input", return_value="TriggerIO 30"), \
             patch("mido.open_input", return_value=_InputPort(messages)), \
             patch("ddti.monitor.time.sleep"):
            count = observe_messages(
                "TriggerIO",
                records.append,
                cancelled=lambda: next(cancellations),
            )
        self.assertEqual(count, 2)
        self.assertEqual(records[0]["channel"], 10)
        self.assertEqual(records[0]["note"], 38)
        self.assertEqual(records[0]["velocity"], 112)
        self.assertEqual(records[1]["control"], 4)
        self.assertEqual(records[1]["value"], 63)

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
        raw = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, index)) + bytes(body) + bytes((0xF7,))
            for index in range(21)
        )
        raw += b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x0A, 2, index, 15, 6, 5, 1, 10, 0, 0xF7))
            for index in range(21)
        )
        configuration = decode_configuration(decode_dump(raw))
        self.assertEqual(configuration.kits[0].inputs[0].tip.note, 35)
        self.assertEqual(configuration.kits[0].inputs[0].ring.note, 36)
        self.assertEqual(configuration.kits[0].inputs[1].tip.note, 37)
        self.assertEqual(encode_configuration(configuration), raw)
        edited = configuration.with_note(0, 2, "tip", 50)
        self.assertEqual(edited.kits[0].inputs[1].tip.note, 50)
        differences = diff_bytes(raw, encode_configuration(edited))
        self.assertEqual([(change.offset, change.before, change.after) for change in differences], [(18, 37, 50)])
        self.assertIn("Input 2 Tip MIDI Note (CONFIRMED)", render_diff(diff_ddti_bytes(raw, encode_configuration(edited))))

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

    def test_complete_dump_exposes_lossless_global_trigger_records(self) -> None:
        kit_body = bytes((9, 35, 3)) * 20 + bytes(6)
        kit = bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, 0)) + kit_body + bytes((0xF7,))
        global_records = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x0A, 2, index, index, 6, 5, 1, 10, 0, 0xF7))
            for index in range(21)
        )
        configuration = decode_configuration(decode_dump(kit + global_records))
        self.assertEqual(len(configuration.global_trigger_records), 21)
        self.assertEqual(configuration.global_trigger_records[0].values, (0, 6, 5, 1, 10, 0))
        self.assertEqual(configuration.global_trigger_records[20].raw_offsets[0], len(kit) + 20 * 18 + 11)

    def test_complete_editor_model_stages_channels_hi_hat_and_all_global_targets(self) -> None:
        kits = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, index))
            + (bytes((9, 35, 3)) * 20)
            + bytes((9, 44, 3, 42, 1, 127, 0xF7))
            for index in range(21)
        )
        globals_ = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x0A, 2, index, 15, 6, 5, 1, 10, 0, 0xF7))
            for index in range(21)
        )
        source = decode_configuration(decode_dump(kits + globals_))
        staged = (
            source.with_zone(0, 2, "tip", channel=12, note=39)
            .with_hi_hat_kit_settings(0, pedal_channel=11, pedal_note=45, closed_note=43)
            .with_global_trigger_settings(2, {
                "gain": 17, "velocity_curve": 8, "threshold": 8, "xtalk": 5,
                "retrigger": 15, "trigger_type_raw": 33,
            })
        )
        self.assertEqual(staged.kits[0].inputs[1].tip.channel, 12)
        self.assertEqual(staged.kits[0].inputs[1].tip.note, 39)
        self.assertEqual(staged.kits[0].hi_hat.to_document(), {
            "pedal_channel": 11, "pedal_note": 45, "closed_note": 43, "link_raw": 3,
        })
        self.assertEqual(staged.global_trigger_records[2].label, "Input 2 Tip")
        self.assertEqual(staged.global_trigger_records[2].settings["retrigger"], 15)
        preset = staged.to_configuration_preset()
        preset["global_triggers"][2]["trigger_type_raw"] = 99
        round_tripped = source.with_configuration_preset(preset)
        self.assertEqual(round_tripped.raw, staged.canonicalize_disabled_program_changes().raw)
        self.assertEqual(round_tripped.global_trigger_records[2].trigger_type_raw, 33)

        with tempfile.TemporaryDirectory() as temporary:
            store = DDTiStateStore(Path(temporary))
            saved = store.save(staged.raw, source="unit test", reason="verified write")
            self.assertEqual(saved, store.syx_path)
            self.assertEqual(store.load().raw, staged.raw)
            metadata = json.loads(store.metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["sha256"], build_transfer_plan(staged.raw).sha256)

    def test_configuration_preset_stages_confirmed_notes_and_input_1_tip_settings(self) -> None:
        kit_body = bytes((9, 35, 3)) * 20 + bytes(6)
        kit = bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, 0)) + kit_body + bytes((0xF7,))
        global_record = bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x0A, 2, 0, 15, 6, 5, 1, 10, 0, 0xF7))
        configuration = decode_configuration(decode_dump(kit + global_record))
        self.assertEqual(configuration.input_1_tip_gain, 15)
        preset = configuration.to_configuration_preset(name="My SD3 mapping")
        self.assertEqual(preset["format"], "ddti-configuration-preset/v1")
        self.assertEqual(preset["name"], "My SD3 mapping")
        staged = configuration.with_configuration_preset({
            "format": "ddti-configuration-preset/v1",
            "notes": [{"kit": 0, "inputs": [{"input": 1, "tip_note": 36}]}],
            "confirmed_global_trigger": {"input_1_tip": {
                "gain": 16, "velocity_curve": 7, "threshold": 7, "xtalk": 4, "retrigger": 14,
            }},
        })
        differences = diff_bytes(configuration.raw, staged.raw)
        self.assertEqual(
            [(change.offset, change.before, change.after) for change in differences],
            [(12, 35, 36), (89, 15, 16), (90, 6, 7), (91, 5, 7), (92, 1, 4), (93, 10, 14)],
        )
        rendered = render_diff(diff_ddti_bytes(configuration.raw, staged.raw))
        self.assertIn("Input 1 Tip Gain (CONFIRMED)", rendered)
        self.assertIn("Velocity Curve (CONFIRMED; observed 6=Lin, 7=LG1)", rendered)
        self.assertIn("Threshold (CONFIRMED)", rendered)
        self.assertEqual(staged.input_1_tip_velocity_curve_label, "LG1")
        with self.assertRaisesRegex(ValueError, "Gain"):
            configuration.with_input_1_tip_gain(128)

    def test_program_change_decodes_three_observed_states_and_canonicalizes_disabled(self) -> None:
        normal_zones = bytes((9, 35, 3)) * 20
        packet = lambda disabled, value: bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, 0)) + normal_zones + bytes((9, 44, 3, 42, disabled, value, 0xF7))
        disabled = decode_configuration(decode_dump(packet(1, 127)))
        self.assertIsNone(disabled.kits[0].program_change)
        active_zero = disabled.with_program_change(0, 0)
        self.assertEqual(active_zero.kits[0].program_change, 0)
        self.assertEqual(active_zero.raw[-3:-1], bytes((0, 0)))
        active_one = active_zero.with_program_change(0, 1)
        self.assertEqual(active_one.kits[0].program_change, 1)
        self.assertEqual(active_one.raw[-3:-1], bytes((0, 1)))
        canonical = disabled.canonicalize_disabled_program_changes()
        self.assertEqual(canonical.raw[-3:-1], bytes((1, 0)))
        self.assertIsNone(canonical.kits[0].program_change)
        with self.assertRaisesRegex(ValueError, "Program Change"):
            disabled.with_program_change(0, 128)
        self.assertIn("Program Change value (CONFIRMED", render_diff(diff_ddti_bytes(disabled.raw, canonical.raw)))
        with self.assertRaisesRegex(ValueError, "requires all 21|factory golden"):
            build_note_write_validation_plan(disabled.raw)
        with self.assertRaisesRegex(ValueError, "requires all 21|factory golden"):
            build_settings_write_validation_plan(disabled.raw)

    def test_role_templates_require_an_explicit_physical_input_layout(self) -> None:
        kit_body = bytes((9, 35, 3)) * 20 + bytes(6)
        raw = bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, 0)) + kit_body + bytes((0xF7,))
        configuration = decode_configuration(decode_dump(raw))
        template = {
            "format": "ddti-note-role-template/v1",
            "roles": {"kick": {"note": 36}, "snare": {"tip": 38, "ring": 40}},
        }
        layout = {
            "format": "ddti-input-layout/v1",
            "kits": [0],
            "bindings": [
                {"input": 1, "zone": "tip", "role": "kick.note"},
                {"input": 2, "zone": "tip", "role": "snare.tip"},
                {"input": 2, "zone": "ring", "role": "snare.ring"},
            ],
        }
        staged = apply_role_template(configuration, template, layout)
        self.assertEqual(staged.kits[0].inputs[0].tip.note, 36)
        self.assertEqual(staged.kits[0].inputs[1].tip.note, 38)
        self.assertEqual(staged.kits[0].inputs[1].ring.note, 40)
        with self.assertRaisesRegex(ValueError, "repeats Input"):
            apply_role_template(configuration, template, {**layout, "bindings": layout["bindings"] + [{"input": 1, "zone": "tip", "role": "kick.note"}]})
        repository = Path(__file__).resolve().parents[2]
        self.assertEqual(load_document(repository / "presets" / "sd3.yaml")["format"], "ddti-note-role-template/v1")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, template_path, layout_path, staged_path = root / "source.syx", root / "template.yaml", root / "layout.yaml", root / "staged.syx"
            source.write_bytes(raw)
            import yaml
            template_path.write_text(yaml.safe_dump(template), encoding="utf-8")
            layout_path.write_text(yaml.safe_dump(layout), encoding="utf-8")
            self.assertEqual(main(["apply-role-preset", str(source), str(template_path), str(layout_path), str(staged_path)]), 0)
            self.assertEqual(decode_configuration(decode_dump(staged_path.read_bytes())).kits[0].inputs[1].ring.note, 40)

    def test_greg_hybrid_ddti_layout_covers_the_declared_cymbal_contract(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        template = load_document(repository / "presets" / "greg-hybrid-ddti-raw.yaml")
        layout = load_document(repository / "profiles" / "physical" / "greg-hybrid-ddti-layout.yaml")
        roles = {
            f"{role}.{articulation}": note
            for role, articulations in template["roles"].items()
            for articulation, note in articulations.items()
        }
        bindings = {binding["role"] for binding in layout["bindings"]}
        self.assertEqual(bindings, set(roles))
        self.assertEqual(sorted(roles.values()), list(range(16, 24)))
        self.assertEqual(len({(binding["input"], binding["zone"]) for binding in layout["bindings"]}), 8)
        kit_body = bytes((9, 35, 3)) * 20 + bytes(6)
        raw = bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, 0)) + kit_body + bytes((0xF7,))
        staged = apply_role_template(decode_configuration(decode_dump(raw)), template, layout)
        for binding in layout["bindings"]:
            zone = getattr(staged.kits[0].inputs[binding["input"] - 1], binding["zone"])
            self.assertEqual(zone.channel, 2)
            self.assertEqual(zone.note, roles[binding["role"]])

    def test_transfer_plan_accepts_only_a_complete_observed_dump(self) -> None:
        kits = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, index)) + (bytes((9, 35, 3)) * 20) + bytes(6) + bytes((0xF7,))
            for index in range(21)
        )
        globals_ = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x0A, 2, index, 15, 6, 5, 1, 10, 0, 0xF7))
            for index in range(21)
        )
        plan = build_transfer_plan(kits + globals_)
        self.assertEqual(plan.to_document()["packet_count"], 42)
        self.assertEqual(plan.to_document()["hardware_write"], "unrestricted_raw_disabled")
        with self.assertRaisesRegex(ValueError, "requires all 21"):
            build_transfer_plan(kits)

    def test_reviewed_transfer_is_hard_disabled_before_opening_output(self) -> None:
        kits = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, index)) + (bytes((9, 35, 3)) * 20) + bytes(6) + bytes((0xF7,))
            for index in range(21)
        )
        globals_ = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x0A, 2, index, 15, 6, 5, 1, 10, 0, 0xF7))
            for index in range(21)
        )
        plan = build_transfer_plan(kits + globals_)
        output = _OutputPort()
        with patch("mido.open_output", return_value=output) as open_output:
            with self.assertRaisesRegex(ProtocolNotValidatedError, "unrestricted raw"):
                send_reviewed_transfer(plan, "TriggerIO", expected_sha256=plan.sha256, confirmation="I_UNDERSTAND_DDTI_WRITE")
        open_output.assert_not_called()
        self.assertEqual(output.messages, [])

    def test_note_write_validation_rejects_any_unreviewed_payload_before_output(self) -> None:
        kits = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, index)) + (bytes((9, 35, 3)) * 20) + bytes(6) + bytes((0xF7,))
            for index in range(21)
        )
        globals_ = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x0A, 2, index, 15, 6, 5, 1, 10, 0, 0xF7))
            for index in range(21)
        )
        plan = build_transfer_plan(kits + globals_)
        output = _OutputPort()
        with patch("mido.open_output", return_value=output) as open_output:
            with self.assertRaisesRegex(ValueError, "not the fixed"):
                send_note_write_validation(
                    plan,
                    "TriggerIO",
                    expected_sha256=plan.sha256,
                    confirmation="I_AUTHORIZE_DDTI_NOTE_35_TO_36",
                )
        open_output.assert_not_called()

    def test_safe_writer_allows_only_confirmed_fields_and_reviewed_hash(self) -> None:
        kits = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, index))
            + (bytes((9, 35, 3)) * 20)
            + bytes((9, 44, 3, 42, 1, 127, 0xF7))
            for index in range(21)
        )
        globals_ = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x0A, 2, index, 15, 6, 5, 1, 10, 0, 0xF7))
            for index in range(21)
        )
        source = decode_configuration(decode_dump(kits + globals_))
        candidate = (
            source.with_note(0, 1, "tip", 36)
            .with_zone(0, 2, "tip", channel=12)
            .with_hi_hat_kit_settings(0, pedal_channel=11, pedal_note=45, closed_note=43)
            .with_program_change(0, 0)
            .with_input_1_tip_settings({
                "gain": 20, "velocity_curve": 14, "threshold": 127, "xtalk": 7, "retrigger": 127,
            })
            .with_global_trigger_settings(2, {
                "gain": 17, "velocity_curve": 8, "threshold": 8, "xtalk": 5,
                "retrigger": 15, "trigger_type_raw": 33,
            })
        )
        plan = build_safe_write_plan(source.raw, candidate.raw)
        self.assertEqual(plan.transfer.dump.family_indexes(), {1: tuple(range(21)), 2: tuple(range(21))})
        self.assertEqual(decode_configuration(plan.transfer.dump).kits[0].inputs[0].tip.note, 36)
        output = _OutputPort()
        with patch("ddti.transfer._resolve_output", return_value="TriggerIO 10"), \
             patch("mido.open_output", return_value=output), \
             patch("ddti.transfer.time.sleep"):
            result = send_safe_configuration(
                source.raw,
                candidate.raw,
                "TriggerIO",
                expected_sha256=plan.sha256,
                confirmation="I_AUTHORIZE_DDTI_CONFIRMED_FIELDS",
            )
        self.assertEqual(result.packet_count, 42)
        self.assertEqual(len(output.messages), 42)

        forbidden = bytearray(candidate.raw)
        forbidden[13] = 4  # confirmed note companion byte remains unvalidated
        with self.assertRaisesRegex(ProtocolNotValidatedError, "unvalidated"):
            build_safe_write_plan(source.raw, bytes(forbidden))
        with self.assertRaisesRegex(ValueError, "PP or SS"):
            source.with_global_trigger_settings(2, {"trigger_type_raw": 34})
        with self.assertRaisesRegex(ValueError, "not editable"):
            source.with_global_trigger_settings(20, {"trigger_type_raw": 33})
        with self.assertRaisesRegex(ValueError, "0..20"):
            source.with_global_trigger_settings(2, {"gain": 21})

    def test_cli_has_no_hardware_transfer_command(self) -> None:
        with self.assertRaises(SystemExit) as error:
            main(["transfer", "would-not-be-read.syx"])
        self.assertEqual(error.exception.code, 2)

    def test_preset_cli_exports_and_applies_to_a_new_staged_file(self) -> None:
        body = bytearray()
        for zone in range(20):
            body.extend((9, 35 + zone, 3))
        body.extend(b"\x00" * 6)
        raw = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, index)) + bytes(body) + bytes((0xF7,))
            for index in range(21)
        )
        raw += b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x0A, 2, index, 15, 6, 5, 1, 10, 0, 0xF7))
            for index in range(21)
        )
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

    def test_configuration_cli_round_trips_a_yaml_preset_offline(self) -> None:
        kit_body = bytes((9, 35, 3)) * 20 + bytes(6)
        kit = bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, 0)) + kit_body + bytes((0xF7,))
        global_record = bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x0A, 2, 0, 15, 6, 5, 1, 10, 0, 0xF7))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.syx"
            preset = root / "mapping.yaml"
            staged = root / "staged.syx"
            source.write_bytes(kit + global_record)
            self.assertEqual(main(["export-config", str(source), str(preset), "--name", "SD3"]), 0)
            text = preset.read_text(encoding="utf-8")
            self.assertIn("format: ddti-configuration-preset/v1", text)
            document = __import__("yaml").safe_load(text)
            document["global_triggers"][0]["gain"] = 16
            preset.write_text(__import__("yaml").safe_dump(document, sort_keys=False), encoding="utf-8")
            self.assertEqual(main(["apply-config", str(source), str(preset), str(staged)]), 0)
            self.assertEqual(decode_configuration(decode_dump(staged.read_bytes())).input_1_tip_gain, 16)

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
        raw = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, index)) + bytes(body) + bytes((0xF7,))
            for index in range(21)
        )
        raw += b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x0A, 2, index, 15, 6, 5, 1, 10, 0, 0xF7))
            for index in range(21)
        )
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
            response = client.patch("/kits/0", json={"program_change": 1})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["kit"]["program_change"], 1)
            preset = client.get("/preset")
            self.assertEqual(preset.status_code, 200)
            preset_document = preset.json()
            preset_document["kits"][0]["inputs"][0]["ring_note"] = 61
            response = client.put("/preset", json=preset_document)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["staged_only"])
            self.assertEqual(client.get("/kits/0/inputs/1").json()["ring"]["note"], 61)
            response = client.patch("/global-trigger/input-1/tip", json={
                "gain": 16, "velocity_curve": 7, "threshold": 7, "xtalk": 4, "retrigger": 14,
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["confirmed_global_trigger"]["input_1_tip"]["gain"], 16)
            configuration_preset = client.get("/configuration-preset")
            self.assertEqual(configuration_preset.status_code, 200)
            self.assertEqual(configuration_preset.json()["confirmed_global_trigger"]["input_1_tip"]["velocity_curve"], 7)
            response = client.post("/role-template", json={
                "template": {"format": "ddti-note-role-template/v1", "roles": {"kick": {"note": 36}}},
                "layout": {"format": "ddti-input-layout/v1", "kits": [0], "bindings": [{"input": 1, "zone": "tip", "role": "kick.note"}]},
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get("/kits/0/inputs/1").json()["tip"]["note"], 36)
            diff = client.get("/staged-diff")
            self.assertEqual(diff.status_code, 200)
            self.assertGreater(diff.json()["changed_bytes"], 0)
            self.assertIn("hardware_write", diff.json())
            staged_sysex = client.get("/staged-sysex")
            self.assertEqual(staged_sysex.status_code, 200)
            self.assertEqual(staged_sysex.headers["x-ddti-hardware-write"], "disabled")
            self.assertNotEqual(staged_sysex.content, raw)
            self.assertEqual(decode_configuration(decode_dump(staged_sysex.content)).kits[0].inputs[0].tip.note, 36)
            write_plan = client.get("/write-plan")
            self.assertEqual(write_plan.status_code, 200)
            output = _OutputPort()
            with patch("ddti.transfer._resolve_output", return_value="TriggerIO 10"), \
                 patch("mido.open_output", return_value=output), \
                 patch("ddti.transfer.time.sleep"):
                written = client.post("/write", json={
                    "output": "TriggerIO",
                    "expected_sha256": write_plan.json()["candidate_sha256"],
                    "confirmation": "I_AUTHORIZE_DDTI_CONFIRMED_FIELDS",
                })
            self.assertEqual(written.status_code, 200)
            self.assertEqual(written.json()["packet_count"], 42)
            self.assertEqual(len(output.messages), 42)
            self.assertEqual(client.get("/staged-diff").json()["changed_bytes"], 0)

            generic_client = TestClient(create_app(source))
            response = generic_client.patch("/kits/0/inputs/2", json={"tip_channel": 12, "tip_note": 39})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["input"]["tip"]["channel"], 12)
            response = generic_client.patch(
                "/kits/0/hi-hat",
                json={"pedal_channel": 11, "pedal_note": 45, "closed_note": 43},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["hi_hat"]["closed_note"], 43)
            response = generic_client.patch(
                "/global-triggers/2", json={"gain": 17, "threshold": 8, "trigger_type": "SS"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["global_trigger"]["target"], "Input 2 Tip")
            self.assertEqual(response.json()["global_trigger"]["settings"]["threshold"], 8)
            self.assertEqual(response.json()["global_trigger"]["trigger_type"], "SS")
            generic_plan = generic_client.get("/write-plan")
            self.assertEqual(generic_plan.status_code, 200)
            self.assertGreater(generic_plan.json()["changed_bytes"], 0)

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
        raw = b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x46, 1, index)) + bytes(body) + bytes((0xF7,))
            for index in range(21)
        )
        raw += b"".join(
            bytes((0xF0, 0, 0, 0x0E, 0x2C, 0x0D, 0, 0, 0x0A, 2, index, 15, 6, 5, 1, 10, 0, 0xF7))
            for index in range(21)
        )
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "fixture.syx"
            source.write_bytes(raw)
            application = QApplication.instance() or QApplication([])
            QTimer.singleShot(20, application.quit)
            with patch.dict(os.environ, {"LOCALAPPDATA": temporary}):
                self.assertEqual(launch(source), 0)
