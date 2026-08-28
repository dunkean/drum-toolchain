from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from midi_lab import (
    build_megakit_preset,
    compare_set,
    diff_files,
    megakit_markdown,
    mixer_inventory,
    preset_inventory,
    scan_binary,
)


class Sd3ReverseTests(unittest.TestCase):
    @staticmethod
    def _preset(instboxes: list[str]) -> bytes:
        body = "".join(instboxes)
        return ("PlugVersion 3.3.7\nSAMPLER {\nHQ {\n" + body + "mixer {\n}\n}\n}\n").encode("latin-1") + b"\x00"

    @staticmethod
    def _instbox(number: int, library: str, drum: str, pad: str, aliases: str) -> str:
        return (
            f"instbox {number} {{\n"
            f"xpad 0 {library} {{\n"
            "pos \"Snare\"\n"
            "mastermics {\nnrmaster 0\n}\n"
            "micmap {\nnrmaster 0\n}\n"
            "laylims {\n}\n"
            f"drum \"{drum}\"  \"Sticks\" 1\n"
            f"pads {{\npad {pad} {{\nmaxpoly 8\n}}\nalias {pad} {aliases}\n}}\n"
            "}\n}\n"
        )

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

    def test_inventory_reads_sd3_instruments_and_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "kit.sd3p"
            path.write_bytes(self._preset([self._instbox(0, "BASE", "SD01", "snareR", "38 40")]))
            inventory = preset_inventory(path)
            self.assertTrue(inventory["trailing_nul"])
            self.assertEqual(inventory["instrument_count"], 1)
            self.assertEqual(inventory["instruments"][0]["drum_id"], "SD01")
            self.assertEqual(len(inventory["notes"]["38"]), 1)

    def test_megakit_build_rewrites_base_and_clones_reviewed_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base.write_bytes(self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32 37")]))
            source.write_bytes(self._preset([self._instbox(2, "ALT", "SD30", "snareR", "5")]))
            recipe.write_text(
                "\n".join([
                    "schema_version: 1",
                    "kind: sd3-preset-build",
                    f"base_sha256: {scan_binary(base)['sha256']}",
                    "base_aliases:",
                    "  0: {snareR: [32]}",
                    "clones:",
                    "  - source: source.sd3p",
                    f"    source_sha256: {scan_binary(source)['sha256']}",
                    "    source_instbox: 2",
                    "    target_instbox: 1",
                    "    aliases: {snareR: [37]}",
                    "expected_unique_notes: [32, 37]",
                ]) + "\n",
                encoding="utf-8",
            )
            result = build_megakit_preset(base, recipe, root, output)
            inventory = preset_inventory(output)
            self.assertEqual(result["instrument_count"], 2)
            self.assertEqual(inventory["notes"]["37"][0]["library"], "ALT")
            self.assertEqual(inventory["notes"]["37"][0]["drum_id"], "SD30")
            self.assertEqual(len(inventory["notes"]["32"]), 1)

    def test_megakit_build_remaps_cloned_mics_to_base_master_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base_payload = self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")])
            base_payload = base_payload.replace(
                b"mastermics {\nnrmaster 0\n}",
                b'mastermics {\nnrmaster 0\n"Stereo" "Stereo" 1 0\n"X-Perc" "Electronic" 0 2\n}',
            ).replace(b"micmap {\nnrmaster 0\n}", b"micmap {\nnrmaster 3\n}")
            base.write_bytes(base_payload)
            source_payload = self._preset([self._instbox(2, "ALT", "SD30", "snareR", "5")])
            source_payload = source_payload.replace(
                b"micmap {\nnrmaster 0\n}",
                b'micmap {\nnrmaster 9\n"Snare-3" "Snare 3" 0 7\n}',
            )
            source.write_bytes(source_payload)
            recipe.write_text(
                "\n".join([
                    "schema_version: 1",
                    "kind: sd3-preset-build",
                    f"base_sha256: {scan_binary(base)['sha256']}",
                    "clones:",
                    "  - source: source.sd3p",
                    f"    source_sha256: {scan_binary(source)['sha256']}",
                    "    source_instbox: 2",
                    "    target_instbox: 1",
                    "    aliases: {snareR: [37]}",
                    "    micmap_overrides: {Snare-3: X-Perc}",
                    "    micmap_exact_match: false",
                    "expected_unique_notes: [32, 37]",
                ]) + "\n",
                encoding="utf-8",
            )
            build_megakit_preset(base, recipe, root, output)
            payload = output.read_text(encoding="latin-1")
            self.assertIn('"Snare-3" "Snare 3" 0 2', payload)
            self.assertIn("nrmaster 3", payload)

    def test_megakit_build_can_require_every_source_mic_to_be_declared(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base.write_bytes(self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")]))
            source_payload = self._preset([self._instbox(2, "ALT", "SD30", "snareR", "5")])
            source.write_bytes(source_payload.replace(
                b"micmap {\nnrmaster 0\n}",
                b'micmap {\nnrmaster 2\n"Close" "Close" 0 0\n"Room" "Room" 0 1\n}',
            ))
            recipe.write_text(
                "\n".join([
                    "schema_version: 1",
                    "kind: sd3-preset-build",
                    f"base_sha256: {scan_binary(base)['sha256']}",
                    "clones:",
                    "  - source: source.sd3p",
                    f"    source_sha256: {scan_binary(source)['sha256']}",
                    "    source_instbox: 2",
                    "    target_instbox: 1",
                    "    aliases: {snareR: [37]}",
                    "    micmap_require_explicit: true",
                    "    micmap_overrides: {Close: null}",
                    "expected_unique_notes: [32, 37]",
                ]) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "explicit map or null"):
                build_megakit_preset(base, recipe, root, output)

    def test_megakit_build_applies_validated_mixer_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            payload = self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")])
            payload = payload.replace(
                b"mixer {\n}",
                b"mixer {\nX-Snare {\npan 0.5\nvolume 1\nmute 0\nsolo 0\nroute output 0\n}\n"
                b"output 0 {\npan 0\nvolume 1\nmute 0\nsolo 0\n}\n}",
            )
            base.write_bytes(payload)
            recipe.write_text(
                "\n".join([
                    "schema_version: 1",
                    "kind: sd3-preset-build",
                    f"base_sha256: {scan_binary(base)['sha256']}",
                    "mixer_overrides:",
                    "  X-Snare: {volume: 0.6, route: 'output 0'}",
                    "expected_unique_notes: [32]",
                ]) + "\n",
                encoding="utf-8",
            )
            build_megakit_preset(base, recipe, root, output)
            entries = {entry["name"]: entry for entry in mixer_inventory(output)["entries"]}
            self.assertEqual(entries["X-Snare"]["volume"], 0.6)
            self.assertEqual(entries["X-Snare"]["route"], "output 0")

    def test_megakit_build_rejects_wrong_semantic_note_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base.write_bytes(self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")]))
            recipe.write_text(
                "\n".join([
                    "schema_version: 1",
                    "kind: sd3-preset-build",
                    f"base_sha256: {scan_binary(base)['sha256']}",
                    "expected_unique_notes: [32]",
                    "expected_mappings:",
                    "  32: {instbox: 0, pad: snareR, library: WRONG, drum_id: SD01}",
                ]) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "expected mapping mismatch"):
                build_megakit_preset(base, recipe, root, output)
            self.assertFalse(output.exists())

    def test_megakit_build_rejects_disconnected_reachable_bus(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            payload = self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")])
            payload = payload.replace(
                b"mixer {\n}",
                b"mixer {\nX-Snare {\nvolume 1\nmute 0\nroute buss 10\n}\n"
                b"buss 20 {\nvolume 1\nmute 0\nroute output -1\n}\n"
                b"buss 21 {\nvolume 1\nmute 0\nroute output -1\n}\n"
                b"output 0 {\nvolume 1\nmute 0\n}\n}",
            )
            base.write_bytes(payload)
            recipe.write_text(
                "\n".join([
                    "schema_version: 1",
                    "kind: sd3-preset-build",
                    f"base_sha256: {scan_binary(base)['sha256']}",
                    "expected_unique_notes: [32]",
                ]) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "disconnected"):
                build_megakit_preset(base, recipe, root, output)
            self.assertFalse(output.exists())

    def test_megakit_build_rejects_unknown_mixer_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base.write_bytes(self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")]))
            recipe.write_text(
                "\n".join([
                    "schema_version: 1",
                    "kind: sd3-preset-build",
                    f"base_sha256: {scan_binary(base)['sha256']}",
                    "mixer_overrides: {Missing: {volume: 0.5}}",
                    "expected_unique_notes: [32]",
                ]) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "do not exist"):
                build_megakit_preset(base, recipe, root, output)

    def test_megakit_build_imports_reviewed_mixer_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base_payload = self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")])
            base_payload = base_payload.replace(
                b"mixer {\n}",
                b"mixer {\nbuss 20 {\npan 0\nvolume 1\nsolo 0\nmute 0\nroute output -1\n}\n}",
            )
            base.write_bytes(base_payload)
            source_payload = self._preset([self._instbox(0, "SRC", "SD02", "snareR", "38")])
            source_payload = source_payload.replace(
                b"mixer {\n}",
                b"mixer {\nbuss 2 {\npan 0\nvolume 0.7\neffect 0 {\neffect 6\nactive 1\n}\nsolo 0\nmute 0\nroute output 0\n}\n}",
            )
            source.write_bytes(source_payload)
            recipe.write_text(
                "\n".join([
                    "schema_version: 1",
                    "kind: sd3-preset-build",
                    f"base_sha256: {scan_binary(base)['sha256']}",
                    "mixer_overrides:",
                    "  'buss 20': {volume: 0.7, route: 'output 0', username: DnB}",
                    "mixer_effect_imports:",
                    "  - source: source.sd3p",
                    f"    source_sha256: {scan_binary(source)['sha256']}",
                    "    source_entry: 'buss 2'",
                    "    target_entry: 'buss 20'",
                    "expected_unique_notes: [32]",
                ]) + "\n",
                encoding="utf-8",
            )
            build_megakit_preset(base, recipe, root, output)
            payload = output.read_text(encoding="latin-1")
            self.assertIn('username "DnB"', payload)
            self.assertIn("effect 0 {\neffect 6\nactive 1\n}", payload)
            entry = next(item for item in mixer_inventory(output)["entries"] if item["name"] == "buss 20")
            self.assertEqual(entry["effect_count"], 1)

    def test_megakit_markdown_identifies_shared_variations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preset = root / "kit.sd3p"
            plan = root / "plan.yaml"
            note_map = root / "map.json"
            preset.write_bytes(self._preset([self._instbox(0, "BASE", "CB01", "cowbell", "92")]))
            plan.write_text(
                "kind: sd3-megakit-plan\nvelocity_sets: {one: [100]}\narticulations:\n"
                "  - {logical: perc.utility, note: 92, capture: true, velocities: one, rr: 1}\n"
                "  - {logical: perc.cowbell, note: 92, capture: false, shared_with: perc.utility}\n",
                encoding="utf-8",
            )
            note_map.write_text(json.dumps({
                "format": "drum-note-map/v1",
                "mappings": [{"id": "metalcore.perc.hit", "logical_target": "perc.utility", "note": 92}],
            }), encoding="utf-8")
            report = megakit_markdown(plan, note_map, preset)
            self.assertIn("92 (G#6)", report)
            self.assertIn("variation partagée", report)
            self.assertIn("BASE / CB01 / cowbell", report)
