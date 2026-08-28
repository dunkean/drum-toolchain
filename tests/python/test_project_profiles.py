from pathlib import Path
import unittest

import yaml

from drum_domain import load_rig_project


ROOT = Path(__file__).resolve().parents[2]


class ProjectProfileFixtureTests(unittest.TestCase):
    def test_greg_hybrid_mvp_is_a_valid_rig_project_v1_fixture(self) -> None:
        project = load_rig_project(ROOT / "profiles/projects/greg-hybrid-mvp.yaml")

        self.assertEqual(project.project, "greg-hybrid-mvp")
        self.assertEqual(project.scenes, ("metalcore", "electronic-stack"))
        self.assertEqual(project.policies["echo"], "measured_only")
        self.assertTrue(project.connection_profiles["LIVE_USB_PRIMARY"]["deduplicate_din_copies"])
        self.assertFalse(project.connection_profiles["DIN_ONLY"]["usb_sources"])
        self.assertEqual(project.logical_routes["metalcore"]["snare_main.head"][0]["when"], {"vp1_snare1": 1})

    def test_r15_sd3_megakit_plan_covers_each_declared_sd3_logical_sound(self) -> None:
        project = load_rig_project(ROOT / "profiles/projects/metalcore-r15-chain-simulator.yaml")
        plan = yaml.safe_load((ROOT / "profiles/sd3/metalcore-r15-megakit-plan.yaml").read_text(encoding="utf-8"))

        planned = {entry["logical"]: entry for entry in plan["articulations"]}
        self.assertEqual(set(planned), set(project.renderers["sd3"]))
        for logical, renderer in project.renderers["sd3"].items():
            self.assertEqual(planned[logical]["note"], renderer["note"])
        self.assertEqual(plan["status"], "generated-local-validation-required")
        self.assertEqual(project.logical_routes["sleep_token"]["snare1.head"], "snare1.sleep")
        sleep_flex = project.logical_routes["sleep_token"]["snare2.head"]
        self.assertEqual(sleep_flex[0], {"logical_target": "tom4.sleep", "when": {"vp2_flex": 6}})
        self.assertEqual(sleep_flex[1], {"logical_target": "snare2.sleep"})
        self.assertEqual(set(project.physical_bindings), set(project.physical_events))
        self.assertEqual(project.physical_bindings["hh.pedal_close"], {"instrument": "hihat_main", "zone": "chick"})
        self.assertEqual(project.physical_bindings["perc.hit"], {"instrument": "hihat_aux", "zone": "head"})


if __name__ == "__main__":
    unittest.main()
