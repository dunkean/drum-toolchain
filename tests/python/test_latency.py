"""Offline regression tests for the M0 latency report contract."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import jsonschema

from midi_lab import analyze_latency_run, prepared_run, validate_latency_run


class LatencyRunTests(unittest.TestCase):
    def test_run_is_versioned_counts_duplicates_and_rejects_cross_clock_math(self) -> None:
        run = prepared_run("ddrum4-direct-001", "probe-din", "ddrum4", 38, 3, 20, "fixture wiring")
        validate_latency_run(run)
        run["status"] = "measured"
        run["observations"] = [
            {"sequence": 0, "timestamps_us": {"t0_wire": 100, "t1_ready": 220, "t2": 240, "t3_wire": 300, "t6": 2100}, "clock_domains": {"t0_wire": "logic", "t1_ready": "logic", "t2": "logic", "t3_wire": "logic", "t6": "logic"}},
            {"sequence": 0, "timestamps_us": {"t0_wire": 100, "t1_ready": 230, "t2": 250, "t3_wire": 320, "t6": 2200}, "clock_domains": {"t0_wire": "logic", "t1_ready": "logic", "t2": "logic", "t3_wire": "logic", "t6": "audio"}},
        ]
        analysis = analyze_latency_run(run)
        self.assertEqual(analysis["losses"], 2)
        self.assertEqual(analysis["duplicates"], 1)
        self.assertEqual(analysis["out_of_order"], 0)
        self.assertEqual(analysis["metrics_us"]["core_us"]["p50"], 20)
        self.assertEqual(analysis["metrics_us"]["midi_to_captured_audio_us"]["count"], 1)
        self.assertEqual(analysis["metrics_us"]["midi_to_captured_audio_us"]["incompatible_clock_pairs"], 1)

    def test_analysis_rejects_a_prepared_run(self) -> None:
        run = prepared_run("prepared", "probe", "ddrum4", 38, 3, 20, "fixture wiring")

        with self.assertRaisesRegex(ValueError, "requires a measured run"):
            analyze_latency_run(run)

    def test_loss_uses_unique_valid_sequences_and_separates_duplicates(self) -> None:
        run = prepared_run("duplicates", "probe", "ddrum4", 38, 3, 20, "fixture wiring")
        run["status"] = "measured"
        run["observations"] = [
            {"sequence": 0, "timestamps_us": {"t0_wire": 100}, "clock_domains": {"t0_wire": "logic"}},
            {"sequence": 0, "timestamps_us": {"t0_wire": 200}, "clock_domains": {"t0_wire": "logic"}},
        ]

        analysis = analyze_latency_run(run)

        self.assertEqual(analysis["losses"], 2)
        self.assertEqual(analysis["duplicates"], 1)
        self.assertEqual(analysis["out_of_range"], 0)
        self.assertEqual(analysis["out_of_order"], 0)

    def test_loss_excludes_out_of_range_sequences(self) -> None:
        run = prepared_run("range", "probe", "ddrum4", 38, 3, 20, "fixture wiring")
        run["status"] = "measured"
        run["observations"] = [
            {"sequence": 0, "timestamps_us": {"t0_wire": 100}, "clock_domains": {"t0_wire": "logic"}},
            {"sequence": 3, "timestamps_us": {"t0_wire": 200}, "clock_domains": {"t0_wire": "logic"}},
            {"sequence": 4, "timestamps_us": {"t0_wire": 300}, "clock_domains": {"t0_wire": "logic"}},
        ]

        analysis = analyze_latency_run(run)

        self.assertEqual(analysis["losses"], 2)
        self.assertEqual(analysis["duplicates"], 0)
        self.assertEqual(analysis["out_of_range"], 2)
        self.assertEqual(analysis["out_of_order"], 0)

    def test_schema_matches_prepared_and_observation_constraints(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "latency-run.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        run = prepared_run("schema", "probe", "ddrum4", 38, 3, 20, "fixture wiring")

        jsonschema.validate(run, schema)
        run["observations"] = [
            {"sequence": 0, "timestamps_us": {"not_a_milestone": 100}, "clock_domains": {"not_a_milestone": "logic"}}
        ]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(run, schema)

        run["status"] = "measured"
        run["observations"] = [
            {"sequence": 0, "timestamps_us": {"t0_wire": 100}, "clock_domains": {"t1_ready": "logic"}}
        ]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(run, schema)
        with self.assertRaisesRegex(ValueError, "milestones must match"):
            validate_latency_run(run)

    def test_prepare_cli_is_offline_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "run.json"
            command = [sys.executable, "-m", "midi_lab.cli", "latency-prepare", "--output", str(run), "--run-id", "fixture", "--source", "probe", "--renderer", "ddrum4", "--note", "38", "--wiring", "fixture wiring"]
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("no MIDI or audio hardware was opened", result.stdout)
            self.assertEqual(validate_latency_run(json.loads(run.read_text(encoding="utf-8")))["status"], "prepared")
            self.assertNotEqual(subprocess.run(command, text=True, capture_output=True, check=False).returncode, 0)
