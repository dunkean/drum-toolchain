from pathlib import Path
import unittest

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


if __name__ == "__main__":
    unittest.main()
