from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

import yaml

from midi_lab import (
    build_sd3_edrum_preset,
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

    def test_greg_hybrid_standard_edrum_map_covers_every_megakit_note(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        profile = repository / "profiles/sd3/greg-hybrid-standard-edrum-map.yaml"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "Greg_Hybrid_Standard_SD3_Kits"
            result = build_sd3_edrum_preset(profile, output)
            payload = output.read_text(encoding="utf-8")

        self.assertEqual(result["mapping_count"], 67)
        self.assertEqual(result["controller_count"], 1)
        self.assertIn("usermap 24 kickR 36 -1", payload)
        self.assertIn("usermap 37 snareR 38 -1", payload)
        self.assertIn("usermap 64 hatsTipTrig 20 -1", payload)
        self.assertIn("usermap 83 ride4 51 -1", payload)
        self.assertIn("usermap 86 spock5 57 -1", payload)
        self.assertIn("usermap 132 hatsCtrl 129", payload)
        note_lines = [line for line in payload.splitlines() if line.startswith("usermap ") and " hatsCtrl " not in line]
        self.assertEqual(len(note_lines), len({int(line.split()[1]) for line in note_lines}))

    def test_sd3_edrum_map_rejects_duplicate_input_note(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "map.yaml"
            output = root / "map"
            profile.write_text("\n".join([
                "kind: sd3-edrum-preset",
                "name: Duplicate",
                "expected_input_notes: [24]",
                "mappings:",
                "  - {input_notes: [24], pad: kickR, standard_note: 36}",
                "  - {input_notes: [24], pad: kickR, standard_note: 36}",
            ]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate.*24"):
                build_sd3_edrum_preset(profile, output)

    def test_r15_recipe_keeps_scene_channels_on_their_reviewed_stereo_bus_pairs(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        recipe = yaml.safe_load(
            (repository / "profiles/sd3/metalcore-r15-megakit-build.yaml").read_text(encoding="utf-8")
        )
        mixer = recipe["mixer_overrides"]
        imports = recipe["mixer_effect_imports"]
        pairs = {
            ("X-Sub", "X-SubR"): ("buss 16", ("buss 32", "buss 33")),
            ("X-Perc5", "X-PercR5"): ("buss 17", ("buss 34", "buss 35")),
            ("X-Riser", "X-RiserR"): ("buss 18", ("buss 36", "buss 37")),
        }
        imported_targets = {entry["target_entry"] for entry in imports}
        for channels, (route, buses) in pairs.items():
            with self.subTest(channels=channels):
                self.assertEqual({mixer[channel]["route"] for channel in channels}, {route})
                self.assertEqual({mixer[bus]["route"] for bus in buses}, {"output 0"})

        clones = {clone["target_instbox"]: clone for clone in recipe["clones"]}
        deftones_snare = clones[30]
        sleep_snare = clones[31]
        self.assertEqual(deftones_snare["source_xpad"], 0)
        self.assertEqual(deftones_snare["aliases"], {
            "snareR": [37], "snareFO": [38], "snareRO": [39],
            "snareFX": [40], "snareSL": [41],
        })
        self.assertEqual(sleep_snare["source_xpad"], 0)
        self.assertEqual(sleep_snare["aliases"], {
            "snareR": [42], "snareFO": [43], "snareRO": [44],
            "snareFX": [45], "snareSL": [46],
        })
        layer_clones = (clones[42], clones[43], clones[45], clones[46])
        self.assertEqual([clone["source_xpad"] for clone in layer_clones], [1, 3, 1, 2])
        self.assertEqual([clone["aliases"] for clone in layer_clones], [
            {"Snare": [100]}, {"Snare": [101]}, {"snareR": [102]}, {"snareR": [103]},
        ])
        for clone in (deftones_snare, sleep_snare, *layer_clones):
            self.assertTrue(clone["micmap_require_used_explicit"])
            self.assertNotIn("stack_routes", clone)
        self.assertEqual(
            set(deftones_snare["micmap_overrides"].values()) - {None},
            {"SnareTop-C"},
        )
        self.assertEqual(set(sleep_snare["micmap_overrides"].values()) - {None}, {"SnareTop-C"})
        for clone in layer_clones:
            self.assertEqual(set(clone["micmap_overrides"].values()) - {None}, {"SnareTop-C"})
        imports_by_target = {entry["target_entry"]: entry["source_entry"] for entry in imports}
        self.assertNotIn("buss 34", imported_targets)
        self.assertNotIn("buss 35", imported_targets)
        self.assertEqual(imports_by_target["buss 36"], "buss 2")
        self.assertEqual(imports_by_target["buss 37"], "buss 3")
        self.assertEqual(imports_by_target["X-Riser"], "SnareTop-C")
        for instbox in (33, 34, 35, 41):
            self.assertEqual(set(clones[instbox]["micmap_overrides"].values()) - {None}, {"X-Sub"})
        self.assertEqual((clones[39]["source"], clones[39]["source_instbox"]), ("@base", 29))
        self.assertEqual(clones[39]["aliases"], {"tom4": [53]})
        self.assertEqual(clones[39]["pad_overrides"]["tom4"]["pitch"], 1.189207)
        self.assertEqual(clones[39]["micmap_overrides"], {"Tom4": "X-Claps-2"})
        self.assertEqual(recipe["expected_mappings"][53]["drum_id"], "TL06")
        self.assertEqual(recipe["base_pad_overrides"][1]["snareFX"]["pvolume"], 0.39)
        self.assertEqual(recipe["base_pad_overrides"][2]["hatsPL"]["pvolume"], 3.50)
        self.assertEqual(clones[38]["pad_overrides"]["tom1"]["pvolume"], 4.0)
        self.assertEqual(clones[44]["pad_overrides"]["spock5"]["pvolume"], 0.24)
        self.assertEqual(recipe["expected_mappings"][37]["pad"], "snareR")
        self.assertEqual(recipe["expected_mappings"][38]["pad"], "snareFO")
        self.assertEqual(recipe["expected_mappings"][39]["pad"], "snareRO")
        self.assertEqual(recipe["expected_mappings"][40]["pad"], "snareFX")
        self.assertEqual(recipe["expected_mappings"][41]["pad"], "snareSL")
        self.assertEqual(recipe["expected_mappings"][42]["pad"], "snareR")
        self.assertEqual(recipe["expected_mappings"][43]["pad"], "snareFO")
        self.assertEqual(recipe["expected_mappings"][44]["pad"], "snareRO")
        self.assertEqual(recipe["expected_mappings"][45]["pad"], "snareFX")
        self.assertEqual(recipe["expected_mappings"][46]["pad"], "snareSL")
        self.assertEqual(
            [recipe["expected_mappings"][note]["drum_id"] for note in (100, 101, 102, 103)],
            ["SD02", "SD30", "Snare8", "Snare7"],
        )

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

    def test_megakit_build_applies_reviewed_clone_pad_volume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base.write_bytes(self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")]))
            source.write_bytes(self._preset([self._instbox(2, "ALT", "SD30", "snareR", "5")]))
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
                    "    pad_overrides: {snareR: {pvolume: 0.562341}}",
                    "expected_unique_notes: [32, 37]",
                ]) + "\n",
                encoding="utf-8",
            )
            build_megakit_preset(base, recipe, root, output)
            payload = output.read_text(encoding="latin-1")
            pad_start = payload.rindex("pad snareR {")
            pad_end = payload.index("\n}", pad_start)
            pad_block = payload[pad_start:pad_end]
            self.assertEqual(pad_block.count("pvolume 0.562341"), 1)

    def test_megakit_build_can_clone_base_and_override_base_pad(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.sd3p"
            output = root / "output.sd3p"
            recipe = root / "recipe.yaml"
            base.write_bytes(self._preset([
                self._instbox(0, "BASE", "SD01", "snareFX", "40"),
            ]))
            digest = scan_binary(base)["sha256"]
            recipe.write_text("\n".join([
                "schema_version: 1",
                "kind: sd3-preset-build",
                f"base_sha256: {digest}",
                "base_aliases:",
                "  0: {snareFX: [40]}",
                "base_pad_overrides:",
                "  0: {snareFX: {pvolume: 0.82}}",
                "clones:",
                "  - source: '@base'",
                f"    source_sha256: {digest}",
                "    source_instbox: 0",
                "    target_instbox: 1",
                "    aliases: {snareFX: [41]}",
                "expected_unique_notes: [40, 41]",
            ]), encoding="utf-8")

            result = build_megakit_preset(base, recipe, root, output)

            self.assertEqual(result["source_sha256"]["@base"], digest)
            payload = output.read_text(encoding="latin-1")
            self.assertEqual(payload.count("pvolume 0.82"), 1)

    def test_megakit_build_applies_base_pad_override_without_alias_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.sd3p"
            output = root / "output.sd3p"
            recipe = root / "recipe.yaml"
            base.write_bytes(self._preset([
                self._instbox(0, "BASE", "SD01", "snareFX", "40"),
            ]))
            recipe.write_text("\n".join([
                "schema_version: 1",
                "kind: sd3-preset-build",
                f"base_sha256: {scan_binary(base)['sha256']}",
                "base_pad_overrides:",
                "  0: {snareFX: {pvolume: 0.82}}",
                "expected_unique_notes: [40]",
            ]), encoding="utf-8")

            build_megakit_preset(base, recipe, root, output)

            payload = output.read_text(encoding="latin-1")
            self.assertEqual(payload.count("pvolume 0.82"), 1)
            self.assertIn("alias snareFX 40", payload)

    def test_megakit_build_maps_colliding_tom_name_to_explicit_master_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.sd3p"
            output = root / "output.sd3p"
            recipe = root / "recipe.yaml"
            payload = self._preset([
                self._instbox(0, "BASE", "SD01", "snareR", "38"),
                self._instbox(29, "EZX", "TL06", "tom4", "54"),
            ])
            payload = payload.replace(
                b"mastermics {\nnrmaster 0\n}",
                b'mastermics {\nnrmaster 37\n"Tom4" "Tom4" 0 12\n"X-Claps-2" "X-Claps-2" 0 36\n}',
            ).replace(
                b"micmap {\nnrmaster 0\n}",
                b'micmap {\nnrmaster 37\n"Tom4" "Tom4" 0 12\n}',
            ).replace(
                b"pad tom4 {\n",
                b'pad tom4 {\nusemic "Tom4" "Tom4R"\n',
            )
            base.write_bytes(payload)
            digest = scan_binary(base)["sha256"]
            recipe.write_text("\n".join([
                "schema_version: 1",
                "kind: sd3-preset-build",
                f"base_sha256: {digest}",
                "clones:",
                "  - source: '@base'",
                f"    source_sha256: {digest}",
                "    source_instbox: 29",
                "    target_instbox: 39",
                "    aliases: {tom4: [53]}",
                "    micmap_exact_match: false",
                "    micmap_require_used_explicit: true",
                "    micmap_overrides: {Tom4: X-Claps-2}",
                "expected_unique_notes: [38, 54, 53]",
            ]), encoding="utf-8")

            build_megakit_preset(base, recipe, root, output)

            text = output.read_text(encoding="latin-1")
            clone_start = text.index("instbox 39 {")
            clone_end = text.index("mixer {", clone_start)
            clone = text[clone_start:clone_end]
            micmap_start = clone.index("micmap {")
            micmap_end = clone.index("laylims {", micmap_start)
            micmap = clone[micmap_start:micmap_end]
            self.assertIn('"Tom4" "Tom4" 0 36', micmap)
            self.assertNotIn('"Tom4" "Tom4" 0 12', micmap)

    def test_megakit_build_can_clear_only_targeted_mixer_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            recipe = root / "recipe.yaml"
            output = root / "output.sd3p"
            base.write_bytes(
                b"PlugVersion 3.3.7\nSAMPLER {\nHQ {\ninstbox 0 {\nxpad 0 LIB {\nmastermics {\nnrmaster 1\nclose  0 0 0\n"
                b'"Kick" "Kick" 0 0\n}\nmicmap {\nnrmaster 1\nclose  0 0 0\n"Kick" "Kick" 0 0\n}\n'
                b'drum "KD" \npads {\npad kickR {\nusemic "Kick" "Kick"\nmaxpoly 8\n}\nalias kickR 24\n}\n}\n}\n'
                b"mixer {\nKick {\nvolume 1\neffect 0 {\neffect 6\nactive 1\n}\nsolo 0\nmute 0\nroute output 0\n}\n"
                b"output 0 {\nvolume 1\neffect 0 {\neffect 6\nactive 1\n}\nsolo 0\nmute 0\n}\n}\n}\n}\n"
            )
            digest = scan_binary(base)["sha256"]
            recipe.write_text(
                "\n".join([
                    "kind: sd3-preset-build",
                    f"base_sha256: {digest}",
                    "base_aliases: {0: {kickR: [24]}}",
                    "mixer_overrides:",
                    "  'output 0': {volume: 0.55, clear_effects: true}",
                    "expected_unique_notes: [24]",
                ]),
                encoding="utf-8",
            )

            build_megakit_preset(base, recipe, root, output)

            payload = output.read_text(encoding="latin-1")
            kick = payload[payload.index("Kick {"):payload.index("output 0 {")]
            master = payload[payload.index("output 0 {"):]
            self.assertIn("effect 0 {", kick)
            self.assertNotIn("effect 0 {", master)
            self.assertIn("volume 0.55", master)

    def test_megakit_build_applies_reviewed_clone_pitch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base.write_bytes(self._preset([self._instbox(0, "BASE", "TO01", "tom1", "52")]))
            source.write_bytes(self._preset([self._instbox(2, "ALT", "TL06", "tom4", "54")]))
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
                    "    aliases: {tom4: [53]}",
                    "    pad_overrides: {tom4: {pitch: 1.189207}}",
                    "expected_unique_notes: [52, 53]",
                ]) + "\n",
                encoding="utf-8",
            )
            build_megakit_preset(base, recipe, root, output)
            payload = output.read_text(encoding="latin-1")
            pad_start = payload.rindex("pad tom4 {")
            pad_end = payload.index("\n}", pad_start)
            self.assertIn("pitch 1.189207", payload[pad_start:pad_end])

    def test_megakit_build_rejects_nonfinite_or_extreme_pad_volume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            base.write_bytes(self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")]))
            source.write_bytes(self._preset([self._instbox(2, "ALT", "SD30", "snareR", "5")]))
            for index, value in enumerate((".nan", ".inf", "0", "4.1")):
                recipe = root / f"recipe-{index}.yaml"
                output = root / f"out-{index}.sd3p"
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
                        f"    pad_overrides: {{snareR: {{pvolume: {value}}}}}",
                        "expected_unique_notes: [32, 37]",
                    ]) + "\n",
                    encoding="utf-8",
                )
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite and in"):
                    build_megakit_preset(base, recipe, root, output)
                self.assertFalse(output.exists())

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

    def test_megakit_build_explicit_mic_override_wins_over_preserve_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base_payload = self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")])
            base.write_bytes(base_payload.replace(
                b"mastermics {\nnrmaster 0\n}",
                b'mastermics {\nnrmaster 1\n"X-Bus" "X Bus" 0 0\n}',
            ).replace(b"micmap {\nnrmaster 0\n}", b"micmap {\nnrmaster 1\n}"))
            source_payload = self._preset([self._instbox(2, "ALT", "SD30", "snareR", "5")])
            source.write_bytes(source_payload.replace(
                b"micmap {\nnrmaster 0\n}",
                b'micmap {\nnrmaster 1\n"Close" "Close" 0 -1\n}',
            ))
            recipe.write_text("\n".join([
                "schema_version: 1",
                "kind: sd3-preset-build",
                f"base_sha256: {scan_binary(base)['sha256']}",
                "clones:",
                "  - source: source.sd3p",
                f"    source_sha256: {scan_binary(source)['sha256']}",
                "    source_instbox: 2",
                "    target_instbox: 1",
                "    aliases: {snareR: [37]}",
                "    micmap_exact_match: false",
                "    micmap_preserve_disabled: true",
                "    micmap_overrides: {Close: X-Bus}",
                "expected_unique_notes: [32, 37]",
            ]), encoding="utf-8")

            build_megakit_preset(base, recipe, root, output)

            payload = output.read_text(encoding="latin-1")
            self.assertIn('"Close" "Close" 0 0', payload)
            self.assertNotIn('"Close" "Close" 0 -1', payload)

    def test_megakit_build_selects_one_xpad_and_adds_alias_to_its_real_pad(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base.write_bytes(self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")]))
            empty = self._instbox(2, "EMPTY", "NONE", "snareR", "5")
            selected = self._instbox(3, "SELECTED", "SD30", "Snare", "6")
            empty_xpad = empty[empty.index("xpad 0 "):-2]
            selected_xpad = selected[selected.index("xpad 0 "):-2]
            selected_xpad = selected_xpad.replace("xpad 0 SELECTED", "xpad 1 SELECTED")
            selected_xpad = selected_xpad.replace("alias Snare 6\n", "")
            multi = "instbox 2 {\n" + empty_xpad + selected_xpad + "}\n"
            source.write_bytes(self._preset([multi]))
            recipe.write_text("\n".join([
                "schema_version: 1",
                "kind: sd3-preset-build",
                f"base_sha256: {scan_binary(base)['sha256']}",
                "clones:",
                "  - source: source.sd3p",
                f"    source_sha256: {scan_binary(source)['sha256']}",
                "    source_instbox: 2",
                "    source_xpad: 1",
                "    target_instbox: 1",
                "    aliases: {Snare: [37]}",
                "expected_unique_notes: [32, 37]",
                "expected_mappings:",
                "  37: {instbox: 1, pad: Snare, library: SELECTED, drum_id: SD30}",
            ]), encoding="utf-8")

            build_megakit_preset(base, recipe, root, output)

            payload = output.read_text(encoding="latin-1")
            self.assertNotIn("EMPTY", payload)
            self.assertIn("xpad 0 SELECTED", payload)
            self.assertIn("alias Snare 37", payload)
            self.assertIn("}\nalias Snare 37\n}\n}\n", payload)

    def test_megakit_build_preserves_multi_xpad_alias_ownership_and_rewrites_every_mastermic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base_payload = self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")])
            base.write_bytes(base_payload.replace(
                b"mastermics {\nnrmaster 0\n}",
                b'mastermics {\nnrmaster 1\n"X-Bus" "X Bus" 0 0\n}',
            ).replace(b"micmap {\nnrmaster 0\n}", b"micmap {\nnrmaster 1\n}"))
            first = self._instbox(2, "FIRST", "SD02", "snareR", "5")
            second = self._instbox(3, "SECOND", "SD30", "Snare", "6")
            first_xpad = first[first.index("xpad 0 "):-2]
            second_xpad = second[second.index("xpad 0 "):-2].replace("xpad 0 SECOND", "xpad 1 SECOND")
            source.write_bytes(self._preset(["instbox 2 {\n" + first_xpad + second_xpad + "}\n"]))
            recipe.write_text("\n".join([
                "schema_version: 1",
                "kind: sd3-preset-build",
                f"base_sha256: {scan_binary(base)['sha256']}",
                "clones:",
                "  - source: source.sd3p",
                f"    source_sha256: {scan_binary(source)['sha256']}",
                "    source_instbox: 2",
                "    target_instbox: 1",
                "    xpad_aliases:",
                "      0: {snareR: [37]}",
                "      1: {Snare: [38]}",
                "expected_unique_notes: [32, 37, 38]",
                "expected_mappings:",
                "  37: {instbox: 1, xpad: 0, library: FIRST, drum_id: SD02, pad: snareR}",
                "  38: {instbox: 1, xpad: 1, library: SECOND, drum_id: SD30, pad: Snare}",
            ]), encoding="utf-8")

            build_megakit_preset(base, recipe, root, output)

            payload = output.read_text(encoding="latin-1")
            clone = payload[payload.index("instbox 1 {"):payload.index("mixer {")]
            self.assertEqual(clone.count("mastermics {"), 2)
            self.assertEqual(clone.count('"X-Bus" "X Bus" 0 0'), 2)
            self.assertIn("alias snareR 37", clone)
            self.assertIn("alias Snare 38", clone)

    def test_megakit_build_validates_used_mics_only_on_selected_xpads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base_payload = self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")])
            base.write_bytes(base_payload.replace(
                b"mastermics {\nnrmaster 0\n}",
                b'mastermics {\nnrmaster 1\n"X-Bus" "X Bus" 0 0\n}',
            ).replace(b"micmap {\nnrmaster 0\n}", b"micmap {\nnrmaster 1\n}"))
            unused = self._instbox(2, "UNUSED", "SD02", "Snare", "5")
            selected = self._instbox(3, "SELECTED", "SD30", "Snare", "6")
            unused_xpad = unused[unused.index("xpad 0 "):-2].replace(
                "micmap {\nnrmaster 0\n}",
                'micmap {\nnrmaster 1\n"UnusedMic" "Unused" 0 0\n}',
            ).replace("pad Snare {\n", 'pad Snare {\nusemic "UnusedMic"\n')
            selected_xpad = selected[selected.index("xpad 0 "):-2].replace(
                "xpad 0 SELECTED", "xpad 1 SELECTED",
            ).replace(
                "micmap {\nnrmaster 0\n}",
                'micmap {\nnrmaster 1\n"SelectedMic" "Selected" 0 0\n}',
            ).replace("pad Snare {\n", 'pad Snare {\nusemic "SelectedMic"\n')
            source.write_bytes(self._preset(["instbox 2 {\n" + unused_xpad + selected_xpad + "}\n"]))
            recipe.write_text("\n".join([
                "schema_version: 1",
                "kind: sd3-preset-build",
                f"base_sha256: {scan_binary(base)['sha256']}",
                "clones:",
                "  - source: source.sd3p",
                f"    source_sha256: {scan_binary(source)['sha256']}",
                "    source_instbox: 2",
                "    target_instbox: 1",
                "    xpad_aliases:",
                "      1: {Snare: [38]}",
                "    micmap_exact_match: false",
                "    micmap_require_used_explicit: true",
                "    micmap_overrides: {SelectedMic: X-Bus}",
                "expected_unique_notes: [32, 38]",
            ]), encoding="utf-8")

            build_megakit_preset(base, recipe, root, output)

            inventory = preset_inventory(output)
            self.assertEqual(inventory["notes"]["38"][0]["xpad"], 1)

    def test_megakit_build_rewrites_and_validates_one_native_stack_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base.write_bytes(self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")]))
            proxy = self._instbox(2, "STACKBASE", "SD11", "trigger", "5")
            target = self._instbox(3, "TARGET", "SD30", "Snare", "6")
            proxy_xpad = proxy[proxy.index("xpad 0 "):-2].replace(
                "pad trigger {\n", "pad trigger {\nblocksounds\n",
            )
            target_xpad = target[target.index("xpad 0 "):-2].replace("xpad 0 TARGET", "xpad 1 TARGET")
            source.write_bytes(self._preset([
                "instbox 2 {\n" + proxy_xpad + target_xpad + "stack 0 0 trigger 1 Snare active\n}\n",
            ]))
            recipe.write_text("\n".join([
                "schema_version: 1",
                "kind: sd3-preset-build",
                f"base_sha256: {scan_binary(base)['sha256']}",
                "clones:",
                "  - source: source.sd3p",
                f"    source_sha256: {scan_binary(source)['sha256']}",
                "    source_instbox: 2",
                "    target_instbox: 1",
                "    xpad_aliases:",
                "      0: {trigger: [37]}",
                "    stack_routes:",
                "      - {source_xpad: 0, source_pad: trigger, target_xpad: 1, target_pad: Snare}",
                "expected_unique_notes: [32, 37]",
                "expected_mappings:",
                "  37: {instbox: 1, xpad: 0, pad: trigger, library: STACKBASE, drum_id: SD11}",
                "expected_stack_mappings:",
                "  37: {instbox: 1, source_xpad: 0, source_pad: trigger, target_xpad: 1, target_pad: Snare, target_library: TARGET, target_drum_id: SD30}",
            ]), encoding="utf-8")

            result = build_megakit_preset(base, recipe, root, output)

            inventory = preset_inventory(output)
            self.assertEqual(result["validated_stack_mappings"], [37])
            self.assertEqual(inventory["instruments"][1]["stack_routes"], [{
                "index": 0, "source_xpad": 0, "source_pad": "trigger",
                "target_xpad": 1, "target_pad": "Snare", "active": True,
            }])

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

    def test_megakit_build_serializes_clone_instboxes_in_numeric_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base.write_bytes(self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")]))
            source.write_bytes(self._preset([self._instbox(2, "ALT", "SD30", "snareR", "5")]))
            recipe.write_text(
                "\n".join([
                    "schema_version: 1",
                    "kind: sd3-preset-build",
                    f"base_sha256: {scan_binary(base)['sha256']}",
                    "clones:",
                    "  - source: source.sd3p",
                    f"    source_sha256: {scan_binary(source)['sha256']}",
                    "    source_instbox: 2",
                    "    target_instbox: 2",
                    "    aliases: {snareR: [38]}",
                    "  - source: source.sd3p",
                    f"    source_sha256: {scan_binary(source)['sha256']}",
                    "    source_instbox: 2",
                    "    target_instbox: 1",
                    "    aliases: {snareR: [37]}",
                    "expected_unique_notes: [32, 37, 38]",
                ]) + "\n",
                encoding="utf-8",
            )

            build_megakit_preset(base, recipe, root, output)

            payload = output.read_text(encoding="latin-1")
            self.assertLess(payload.index("instbox 0 {"), payload.index("instbox 1 {"))
            self.assertLess(payload.index("instbox 1 {"), payload.index("instbox 2 {"))

    def test_megakit_build_rejects_duplicate_clone_instboxes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base.write_bytes(self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")]))
            source.write_bytes(self._preset([self._instbox(2, "ALT", "SD30", "snareR", "5")]))
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
                    "    aliases: {snareR: [36]}",
                    "  - source: source.sd3p",
                    f"    source_sha256: {scan_binary(source)['sha256']}",
                    "    source_instbox: 2",
                    "    target_instbox: 1",
                    "    aliases: {snareR: [37]}",
                    "expected_unique_notes: [32, 36, 37]",
                ]) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicate clone target instbox"):
                build_megakit_preset(base, recipe, root, output)

    def test_megakit_build_requires_each_used_clone_mic_to_be_mapped_or_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base.sd3p"
            source = root / "source.sd3p"
            output = root / "out.sd3p"
            recipe = root / "recipe.yaml"
            base_payload = self._preset([self._instbox(0, "BASE", "SD01", "snareR", "32")])
            base.write_bytes(base_payload.replace(
                b"mastermics {\nnrmaster 0\n}",
                b'mastermics {\nnrmaster 1\n"X-Bus" "X Bus" 0 0\n}',
            ).replace(b"micmap {\nnrmaster 0\n}", b"micmap {\nnrmaster 1\n}"))
            source_payload = self._preset([self._instbox(2, "ALT", "SD30", "snareR", "5")])
            source.write_bytes(source_payload.replace(
                b"micmap {\nnrmaster 0\n}",
                b'micmap {\nnrmaster 2\n"Close" "Close" 0 0\n"Room" "Room" 1 1\n}',
            ).replace(b"pad snareR {\n", b'pad snareR {\nusemic "Close" "Room" "RoomR"\n'))
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
                    "    micmap_exact_match: false",
                    "    micmap_require_used_explicit: true",
                    "    micmap_overrides: {Close: X-Bus}",
                    "expected_unique_notes: [32, 37]",
                ]) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "used micmap entries require explicit map or null:.*Room"):
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
            self.assertIn("92 (G#5)", report)
            self.assertIn("variation partagée", report)
            self.assertIn("BASE / CB01 / cowbell", report)
