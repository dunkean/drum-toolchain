from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from drum_domain import RigProjectError, load_rig_project


def valid_project() -> dict:
    return {
        "schema_version": 1,
        "kind": "rig-project",
        "project": "hybrid-demo",
        "rig": "profiles/physical/greg-hybrid-kit.yaml",
        "deployment": "simulation",
        "ddrum4_output_channel": 12,
        "sources": {
            "edrumin": {"endpoint": "usb-edrumin", "channel": 3, "primary": "usb", "connection_profile": "LIVE_USB"},
            "ddti": {"endpoint": "usb-ddti", "channel": 2, "primary": "usb", "connection_profile": "LIVE_USB"},
        },
        "connection_profiles": {"LIVE_USB": {"deduplicate_din_copies": True}},
        "source_decoders": [
            {"match": {"source": "edrumin", "type": "note", "note": 38}, "emit": {"physical": "snare1.head", "expressions": ["velocity"]}},
            {"match": {"source": "edrumin", "type": "note_range", "note_range": [48, 50]}, "emit": {"physical": "tom1.head", "expressions": ["velocity"]}},
            {"match": {"source": "ddti", "type": "cc", "cc": 4}, "emit": {"physical": "hh.opening", "normalize": "cc7"}},
            {"match": {"source": "ddti", "type": "poly_aftertouch", "active_note": True}, "emit": {"physical": "cymbal.choke", "correlate": "source_channel_note"}},
        ],
        "physical_events": ["snare1.head", "tom1.head", "hh.opening", "cymbal.choke"],
        "state": {"scenes": ["metalcore", "electronic"], "variables": ["vp1_snare"], "defaults": {"scene": "metalcore", "vp1_snare": 0}},
        "logical_control_protocol": {"scene": {"channels": [14, 15], "type": "program_change"}, "vp1_snare": {"channels": [14, 15], "type": "cc", "cc": 20}},
        "logical_routes": {
            "metalcore": {"snare1.head": "snare.metal.head", "tom1.head": "tom.metal.head", "hh.opening": "hh.metal.opening", "cymbal.choke": "cymbal.metal.choke"},
            "electronic": {"snare1.head": "snare.electronic.head", "tom1.head": "tom.electronic.head", "hh.opening": "hh.electronic.opening", "cymbal.choke": "cymbal.electronic.choke"},
        },
        "renderers": {"ddrum4": {}, "sd3": {}},
        "native_control_map": {"ddrum4_program_change": {"decode_to": "scene", "channel": 1, "type": "program_change", "program": 0, "value": 0}},
        "policies": {"echo": "measured_only", "unknown_message": "drop_and_count"},
    }


def fill_renderers(document: dict) -> None:
    sounds = set()
    for routes in document["logical_routes"].values():
        for route in routes.values():
            if isinstance(route, str):
                sounds.add(route)
            else:
                sounds.update(variant["logical_target"] for variant in route)
    document["renderers"] = {
        "ddrum4": {sound: {"note": index} for index, sound in enumerate(sorted(sounds))},
        "sd3": {sound: {"note": index + 32} for index, sound in enumerate(sorted(sounds))},
        "drumgizmo": {sound: {"note": index + 64, "instrument": sound.split(".")[0],
                               "articulation": sound.split(".")[-1]} for index, sound in enumerate(sorted(sounds))},
    }


class RigProjectTests(unittest.TestCase):
    def load(self, document: dict):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.yaml"
            path.write_text(yaml.safe_dump(document), encoding="utf-8")
            return load_rig_project(path)

    def test_loads_complete_project_with_all_decoder_kinds(self) -> None:
        document = valid_project()
        fill_renderers(document)
        project = self.load(document)
        self.assertEqual(project.defaults, {"scene": "metalcore", "vp1_snare": 0})
        self.assertEqual(project.sources["edrumin"].channel, 3)
        self.assertEqual({decoder.message_type for decoder in project.source_decoders}, {"note", "note_range", "cc", "poly_aftertouch"})

    def test_rejects_incomplete_state_route_or_renderer_coverage(self) -> None:
        document = valid_project()
        fill_renderers(document)
        del document["logical_routes"]["metalcore"]["cymbal.choke"]
        with self.assertRaisesRegex(RigProjectError, "physical events without route"):
            self.load(document)
        document = valid_project()
        fill_renderers(document)
        del document["renderers"]["sd3"]["snare.metal.head"]
        with self.assertRaisesRegex(RigProjectError, "logical sounds without renderer"):
            self.load(document)

    def test_rejects_ambiguous_or_invalid_control_and_defaults(self) -> None:
        document = valid_project()
        fill_renderers(document)
        document["source_decoders"].append(copy.deepcopy(document["source_decoders"][0]))
        with self.assertRaisesRegex(RigProjectError, "overlapping note decoder"):
            self.load(document)
        document = valid_project()
        fill_renderers(document)
        document["logical_control_protocol"]["vp1_snare"] = {"channels": [14, 15], "type": "program_change"}
        with self.assertRaisesRegex(RigProjectError, "must use a CC"):
            self.load(document)
        document = valid_project()
        fill_renderers(document)
        document["state"]["defaults"].pop("vp1_snare")
        with self.assertRaisesRegex(RigProjectError, "must define scene and every variable"):
            self.load(document)

    def test_rejects_velocity_as_cc_address_and_native_logical_channel_collision(self) -> None:
        document = valid_project()
        fill_renderers(document)
        document["source_decoders"][2]["emit"] = {"physical": "hh.opening", "expressions": ["velocity"]}
        with self.assertRaisesRegex(RigProjectError, "cc must use normalize"):
            self.load(document)

    def test_rejects_multiple_semantic_expressions_on_one_raw_expression_decoder(self) -> None:
        document = valid_project()
        fill_renderers(document)
        document["source_decoders"][2]["emit"] = {
            "physical": "hh.opening", "expressions": ["openness", "pressure"], "normalize": "cc7",
        }
        with self.assertRaisesRegex(RigProjectError, "exactly one semantic expression"):
            self.load(document)
        document = valid_project()
        fill_renderers(document)
        document["native_control_map"]["ddrum4_program_change"]["channel"] = 14
        with self.assertRaisesRegex(RigProjectError, "reserved for logical control"):
            self.load(document)

    def test_rejects_unpaired_aftertouch_correlation_contract(self) -> None:
        document = valid_project()
        fill_renderers(document)
        document["source_decoders"][3]["emit"].pop("correlate")
        with self.assertRaisesRegex(RigProjectError, "active_note and correlate"):
            self.load(document)

    def test_rejects_ambiguous_exact_note_position(self) -> None:
        document = valid_project()
        fill_renderers(document)
        document["source_decoders"][0]["emit"]["expressions"].append("position")
        with self.assertRaisesRegex(RigProjectError, "exact Note cannot carry position"):
            self.load(document)
        document = valid_project()
        fill_renderers(document)
        document["source_decoders"][3]["match"].pop("active_note")
        with self.assertRaisesRegex(RigProjectError, "active_note and correlate"):
            self.load(document)

    def test_native_controls_are_addressed_unambiguously(self) -> None:
        document = valid_project()
        fill_renderers(document)
        document["native_control_map"]["ddrum4_palette"] = {
            "decode_to": "vp1_snare", "source": "edrumin", "channel": 3,
            "type": "cc", "cc": 21, "value": 1,
        }
        self.load(document)

        document["native_control_map"]["duplicate"] = {
            "decode_to": "vp1_snare", "channel": 3, "type": "cc", "cc": 21, "value": 1,
        }
        with self.assertRaisesRegex(RigProjectError, "overlaps another native control"):
            self.load(document)

    def test_program_change_requires_an_exact_program_and_state_value(self) -> None:
        document = valid_project()
        fill_renderers(document)
        document["native_control_map"]["ddrum4_program_change"].pop("program")
        with self.assertRaisesRegex(RigProjectError, "program"):
            self.load(document)
        document = valid_project()
        fill_renderers(document)
        document["native_control_map"]["ddrum4_program_change"]["value"] = 2
        with self.assertRaisesRegex(RigProjectError, "scene value"):
            self.load(document)

    def test_routes_support_non_overlapping_scene_vp_variants_with_a_fallback(self) -> None:
        document = valid_project()
        document["logical_routes"]["metalcore"]["snare1.head"] = [
            {"logical_target": "snare.metal.alt", "when": {"vp1_snare": 1}},
            {"logical_target": "snare.metal.head"},
        ]
        fill_renderers(document)
        project = self.load(document)
        variants = project.logical_routes["metalcore"]["snare1.head"]
        self.assertEqual(variants[0]["when"], {"vp1_snare": 1})

        document["logical_routes"]["metalcore"]["snare1.head"] = [
            {"logical_target": "snare.metal.alt", "when": {"vp1_snare": 1}},
            {"logical_target": "snare.metal.head", "when": {"vp1_snare": 1}},
            {"logical_target": "snare.metal.head"},
        ]
        with self.assertRaisesRegex(RigProjectError, "overlapping route state predicates"):
            self.load(document)
