from pathlib import Path
import unittest

from drum_domain import LogicalEvent, PhysicalKit, load_setup


ROOT = Path(__file__).resolve().parents[2]


class DomainTests(unittest.TestCase):
    def test_physical_kit_has_no_source_module_assignment(self) -> None:
        kit = PhysicalKit.load(ROOT / "profiles/physical/greg-hybrid-kit.yaml")
        snare = kit.instrument("snare_main")
        self.assertEqual(snare.zones, ("head", "rim"))
        self.assertIn("positional_sensing", snare.capabilities)

    def test_setup_resolves_composable_documents(self) -> None:
        setup = load_setup(ROOT / "profiles/setups/ddrum4-soundbank-development.yaml")
        self.assertEqual(setup.bank.name, "metalcore-main.yaml")
        self.assertEqual(len(setup.inputs()), 5)

    def test_logical_event_rejects_out_of_range_values(self) -> None:
        self.assertEqual(LogicalEvent("snare_main", "head", velocity=127).velocity, 127)
        with self.assertRaises(ValueError):
            LogicalEvent("snare_main", "head", velocity=0)
        with self.assertRaises(ValueError):
            LogicalEvent("snare_main", "head", openness=1.01)
