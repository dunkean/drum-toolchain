from pathlib import Path
import unittest

import yaml

from drum_domain import LogicalEvent, PhysicalKit, load_setup, validate_document, validate_yaml


ROOT = Path(__file__).resolve().parents[2]


class DomainTests(unittest.TestCase):
    def test_physical_kit_records_pad_owner_without_a_midi_address(self) -> None:
        kit = PhysicalKit.load(ROOT / "profiles/physical/greg-hybrid-kit.yaml")
        snare = kit.instrument("snare_main")
        self.assertEqual(snare.zones, ("head", "rim"))
        self.assertIn("positional_sensing", snare.capabilities)
        self.assertEqual(snare.source_owner, "edrumin")

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

    def test_current_composable_profiles_validate_against_contract_schemas(self) -> None:
        schemas = ROOT / "contracts/schemas"
        validate_yaml(ROOT / "profiles/physical/greg-hybrid-kit.yaml", schemas / "physical-kit.schema.json")
        validate_yaml(ROOT / "profiles/wiring/snare-via-edrumin.yaml", schemas / "wiring-profile.schema.json")
        validate_yaml(ROOT / "profiles/targets/ddrum4-standalone.yaml", schemas / "target-profile.schema.json")
        validate_yaml(ROOT / "profiles/banks/metalcore-main.yaml", schemas / "ddrum4-bank.schema.json")

    def test_composable_edrumin_wiring_matches_the_canonical_manual_profile(self) -> None:
        wiring = yaml.safe_load((ROOT / "profiles/wiring/snare-via-edrumin.yaml").read_text(encoding="utf-8"))
        manual = yaml.safe_load((ROOT / "profiles/physical/greg-hybrid-edrumin.yaml").read_text(encoding="utf-8"))
        project = yaml.safe_load((ROOT / "profiles/projects/metalcore-r15-chain-simulator.yaml").read_text(encoding="utf-8"))
        self.assertEqual(wiring["sources"]["edrumin"]["channel"], manual["channel"])
        self.assertEqual({row["event"]["note"] for row in wiring["bindings"]}, {0, 1, 2})
        project_snare_notes = {
            row["match"]["note"]
            for row in project["source_decoders"]
            if row["match"]["source"] == "edrumin" and row["emit"]["physical"].startswith("snare1.")
        }
        self.assertEqual(project_snare_notes, {0, 1, 2})

    def test_schema_validation_rejects_invalid_midi_channel(self) -> None:
        document = {"profile": "invalid", "status": "template", "midi": {"output_channel": 17}, "module": {"memory_blocks": 1}, "notes": []}
        with self.assertRaises(ValueError):
            validate_document(document, ROOT / "contracts/schemas/target-profile.schema.json")
