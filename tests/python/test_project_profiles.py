from pathlib import Path
import unittest

import yaml

from ddti.mappings import apply_role_template
from ddti.models import decode_configuration
from ddti.presets import load_document
from ddti.protocol import decode_dump
from drum_domain import load_rig_project


ROOT = Path(__file__).resolve().parents[2]


class ProjectProfileFixtureTests(unittest.TestCase):
    def test_every_platformio_hardware_environment_inherits_the_reviewed_upload_gate(self) -> None:
        text = (ROOT / "firmware/ddrum4-midi-bridge/platformio.ini").read_text(encoding="utf-8")
        shared = text.split("[env]", 1)[1].split("[env:", 1)[0]
        self.assertIn("extra_scripts = pre:scripts/enforce_reviewed_upload.py", shared)
        for environment in ("uno", "uno_tx_test", "uno_sd", "megaatmega2560"):
            self.assertIn(f"[env:{environment}]", text)

    def test_ddti_apply_always_captures_its_own_fresh_base_dump(self) -> None:
        text = (ROOT / "scripts/configure-greg-hybrid-ddti.ps1").read_text(encoding="utf-8")
        self.assertNotIn("$BaseDump", text)
        apply_start = text.index("if (-not $ConfirmWrite)")
        fresh_capture = text.index("ddti.cli dump $preWriteStem", apply_start)
        source_assignment = text.index("$source =", fresh_capture)
        write_call = text.index("ddti.cli write-config", source_assignment)
        self.assertLess(fresh_capture, source_assignment)
        self.assertLess(source_assignment, write_call)

    def test_flash_and_live_scripts_require_explicit_validation_stages(self) -> None:
        flash = (ROOT / "scripts/flash-ddrum4-bridge.ps1").read_text(encoding="utf-8")
        preflight = (ROOT / "scripts/live-preflight.ps1").read_text(encoding="utf-8")
        prepare = (ROOT / "scripts/prepare-greg-hybrid-live.ps1").read_text(encoding="utf-8")
        self.assertIn("'post-flash-validation-pending', 'hardware-verified'", flash)
        self.assertIn("$validationStage -ne 'hardware-verified'", preflight)
        self.assertIn("$report.validation_stage -ne 'hardware-verified'", prepare)

    def test_greg_hybrid_module_profiles_impose_the_canonical_raw_notes(self) -> None:
        project = load_rig_project(ROOT / "profiles/projects/metalcore-r15-chain-simulator.yaml")
        edrumin = yaml.safe_load(
            (ROOT / "profiles/physical/greg-hybrid-edrumin.yaml").read_text(encoding="utf-8")
        )
        ddti_layout = yaml.safe_load(
            (ROOT / "profiles/physical/greg-hybrid-ddti-layout.yaml").read_text(encoding="utf-8")
        )
        module_plan = yaml.safe_load(
            (ROOT / "profiles/physical/greg-hybrid-module-configuration.yaml").read_text(encoding="utf-8")
        )

        edrumin_notes = {
            row["physical"]: row["note"] for row in edrumin["notes"]
        }
        project_edrumin_notes = {
            decoder.physical: decoder.match["note"]
            for decoder in project.source_decoders
            if decoder.source == "edrumin" and decoder.message_type == "note"
        }
        self.assertEqual(edrumin_notes, project_edrumin_notes)
        self.assertEqual(edrumin["channel"], project.sources["edrumin"].channel)
        self.assertEqual(edrumin["socket_plan"]["snare1"]["hit_jack"]["input"], 1)
        self.assertEqual(edrumin["socket_plan"]["snare1"]["rim_jack"]["input"], 2)

        expected_ddti_roles = {
            decoder.physical
            for decoder in project.source_decoders
            if decoder.source == "ddti" and decoder.message_type == "note"
        }
        self.assertEqual(
            {binding["role"] for binding in ddti_layout["bindings"]},
            expected_ddti_roles,
        )
        self.assertEqual(ddti_layout["kits"], list(range(20)))
        golden = decode_configuration(decode_dump(
            (ROOT / "captures/factory_dump_002_full.golden.syx").read_bytes()
        ))
        staged = apply_role_template(
            golden,
            load_document(ROOT / "build/rig/metalcore-r15/ddti-role-template.yaml"),
            ddti_layout,
        )
        expected_notes = {
            (1, "tip"): 16, (1, "ring"): 17,
            (2, "tip"): 18, (2, "ring"): 19,
            (3, "tip"): 20, (4, "tip"): 21,
            (5, "tip"): 22, (6, "tip"): 23,
        }
        for kit in staged.kits[:20]:
            for (input_number, zone_name), note in expected_notes.items():
                zone = getattr(kit.inputs[input_number - 1], zone_name)
                self.assertEqual((zone.channel, zone.note), (2, note))
        self.assertFalse(module_plan["flash_policy"]["pads_required"])
        self.assertEqual(module_plan["modules"]["ddrum4"]["status"], "user-confirmed")

    def test_greg_hybrid_mvp_is_a_valid_rig_project_v1_fixture(self) -> None:
        project = load_rig_project(ROOT / "profiles/projects/greg-hybrid-mvp.yaml")

        self.assertEqual(project.project, "greg-hybrid-mvp")
        self.assertEqual(project.scenes, ("metalcore", "electronic-stack"))
        self.assertEqual(project.policies["echo"], "measured_only")
        self.assertTrue(project.connection_profiles["LIVE_USB_PRIMARY"]["deduplicate_din_copies"])
        self.assertFalse(project.connection_profiles["DIN_ONLY"]["usb_sources"])
        self.assertEqual(project.logical_routes["metalcore"]["snare_main.head"][0]["when"], {"vp1_snare1": 1})

    def test_every_r15_ddrum4_renderer_note_has_resident_audio(self) -> None:
        project = yaml.safe_load(
            (ROOT / "profiles/projects/metalcore-r15-chain-simulator.yaml").read_text(encoding="utf-8")
        )
        bank = yaml.safe_load(
            (ROOT / "profiles/banks/metalcore-r15-installed.yaml").read_text(encoding="utf-8")
        )
        occupied_notes = {
            sound["note_base"] + layer["position"] - 1
            for sound in bank["sounds"]
            for layer in sound.get("layers", [])
        }
        missing: dict[str, list[int]] = {}
        for logical, renderer in project["renderers"]["ddrum4"].items():
            notes = renderer.get("position_notes", [renderer["note"]])
            silent = [note for note in notes if note not in occupied_notes]
            if silent:
                missing[logical] = silent
        self.assertEqual(missing, {})
        self.assertEqual(project["renderers"]["ddrum4"]["stack.acoustic"]["note"], 43)
        self.assertEqual(project["renderers"]["ddrum4"]["crash3.edge"]["note"], 56)

    def test_r15_sd3_megakit_plan_covers_each_declared_sd3_logical_sound(self) -> None:
        project = load_rig_project(ROOT / "profiles/projects/metalcore-r15-chain-simulator.yaml")
        plan = yaml.safe_load((ROOT / "profiles/sd3/metalcore-r15-megakit-plan.yaml").read_text(encoding="utf-8"))

        planned = {entry["logical"]: entry for entry in plan["articulations"]}
        for entry in plan["articulations"]:
            instrument = entry["logical"].split(".", 1)[0]
            for variant in entry.get("capture_variants", []):
                logical = f"{instrument}.{variant['articulation']}"
                if logical in project.renderers["sd3"]:
                    planned[logical] = {**variant, "note": entry["note"]}
        self.assertEqual(set(planned), set(project.renderers["sd3"]))
        for logical, renderer in project.renderers["sd3"].items():
            self.assertEqual(planned[logical]["note"], renderer["note"])
        self.assertEqual(plan["status"], "captured-and-internally-validated")
        self.assertEqual(project.logical_routes["sleep_token"]["snare1.head"], "snare1.sleep")
        self.assertEqual(project.renderers["sd3"]["snare1.deftones"]["layers"], [100, 101])
        self.assertEqual(project.renderers["sd3"]["snare1.sleep"]["layers"], [103])
        sleep_flex = project.logical_routes["sleep_token"]["snare2.head"]
        self.assertEqual(sleep_flex[0], {"logical_target": "tom4.sleep", "when": {"vp2_flex": 6}})
        self.assertEqual(sleep_flex[1], {"logical_target": "snare2.sleep"})
        self.assertEqual(set(project.physical_bindings), set(project.physical_events))
        self.assertEqual(project.physical_bindings["hh.pedal_close"], {"instrument": "hihat_main", "zone": "chick"})
        self.assertEqual(project.physical_bindings["perc.hit"], {"instrument": "hihat_aux", "zone": "head"})


if __name__ == "__main__":
    unittest.main()
