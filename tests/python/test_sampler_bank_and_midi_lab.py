from pathlib import Path
import tempfile
import unittest

from drum_sampler.session import CaptureRequest, CaptureSessionPlan
from ddrum4_bank.ddrum4ui import encoded_block_count
from ddrum4_bank.nested import NestedRoute, NestedSound
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

    def test_trace_round_trip_and_unique_port_matching(self) -> None:
        trace = MidiTrace("edrumin", (TraceEvent(0, "note_on", 11, 42, 100),))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trace.jsonl"
            trace.write(path)
            self.assertEqual(MidiTrace.read(path), trace)
        self.assertEqual(resolve_unique_port(["MIDI4x4", "MIDIOUT2 (MIDI4x4)"], "MIDI4x4"), "MIDI4x4")
        with self.assertRaises(ValueError):
            resolve_unique_port(["MIDI4x4", "MIDIOUT2 (MIDI4x4)"], "midi")
