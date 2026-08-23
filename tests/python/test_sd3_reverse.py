from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from midi_lab import compare_set, diff_files, scan_binary


class Sd3ReverseTests(unittest.TestCase):
    def test_scan_binary_reports_stable_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "base.bin"
            path.write_bytes(bytes([0, 1, 2, 3, 4, 5, 255]))
            summary = scan_binary(path)
            self.assertEqual(summary["size_bytes"], 7)
            self.assertEqual(summary["unique_byte_values"], 7)
            self.assertIn("sha256", summary)
            self.assertFalse(summary["high_entropy_hint"])

    def test_diff_files_reports_contiguous_runs_and_length_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "base.bin"
            variant = Path(temporary) / "variant.bin"
            base.write_bytes(b"ABCDEF1234")
            variant.write_bytes(b"ABzzEF12")
            report = diff_files(base, variant)
            self.assertGreaterEqual(report["diff_run_count"], 2)
            self.assertEqual(report["base_size_bytes"], 10)
            self.assertEqual(report["variant_size_bytes"], 8)

    def test_compare_set_highlights_hot_bins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "baseline.bin"
            base.write_bytes(bytes([0]) * 1024)
            first = root / "first.bin"
            second = root / "second.bin"
            first_payload = bytearray(base.read_bytes())
            second_payload = bytearray(base.read_bytes())
            for index in range(100, 120):
                first_payload[index] = 1
                second_payload[index] = 2
            first.write_bytes(first_payload)
            second.write_bytes(second_payload)
            report = compare_set(base, [first, second], bin_size=64, top_bins=5)
            self.assertEqual(report["variant_count"], 2)
            self.assertTrue(report["top_bins"])
            self.assertEqual(report["top_bins"][0]["file_hits"], 2)

    def test_cli_sd3_scan_and_diffset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "baseline.bin"
            one = root / "one.bin"
            two = root / "two.bin"
            base.write_bytes(bytes([0]) * 256)
            one_payload = bytearray(base.read_bytes())
            two_payload = bytearray(base.read_bytes())
            one_payload[8] = 10
            two_payload[8] = 20
            one.write_bytes(one_payload)
            two.write_bytes(two_payload)

            scan_command = [sys.executable, "-m", "midi_lab.cli", "sd3-scan", str(base)]
            scan = subprocess.run(scan_command, capture_output=True, text=True)
            self.assertEqual(scan.returncode, 0, scan.stderr)
            summary = json.loads(scan.stdout)
            self.assertEqual(summary["size_bytes"], 256)

            diffset_command = [
                sys.executable,
                "-m",
                "midi_lab.cli",
                "sd3-diffset",
                str(base),
                str(root),
                "--pattern",
                "*.bin",
                "--bin-size",
                "32",
                "--top-bins",
                "3",
            ]
            diffset = subprocess.run(diffset_command, capture_output=True, text=True)
            self.assertEqual(diffset.returncode, 0, diffset.stderr)
            report = json.loads(diffset.stdout)
            self.assertEqual(report["variant_count"], 2)
            self.assertTrue(report["top_bins"])
