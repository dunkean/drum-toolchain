from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


COMPILER_SOURCE = Path(__file__).resolve().parents[2] / "tools" / "rig-compiler" / "src"
DOMAIN_SOURCE = Path(__file__).resolve().parents[2] / "packages" / "drum-domain" / "src"
SAMPLER_SOURCE = Path(__file__).resolve().parents[2] / "apps" / "drum-sampler" / "src"
FIRMWARE_GENERATOR = Path(__file__).resolve().parents[2] / "firmware" / "ddrum4-midi-bridge" / "tools" / "generate_mapping.py"
if str(COMPILER_SOURCE) not in sys.path:
    sys.path.insert(0, str(COMPILER_SOURCE))
if str(DOMAIN_SOURCE) not in sys.path:
    sys.path.insert(0, str(DOMAIN_SOURCE))
if str(SAMPLER_SOURCE) not in sys.path:
    sys.path.insert(0, str(SAMPLER_SOURCE))

from rig_compiler import RigCompilerError, compile_project, validate_project
from rig_compiler.cli import main
from drum_sampler.offline import drumgizmo_note_overrides


class RigCompilerTests(unittest.TestCase):
    def _project(self, root: Path, *, duplicate: bool = False) -> Path:
        project = root / "kit.yaml"
        document = {
            "schema_version": 1, "kind": "rig-project", "project": "test-kit", "rig": "fixture", "deployment": "simulation", "ddrum4_output_channel": 10,
            "sources": {"brain": {"endpoint": "fixture", "channel": 10, "primary": "usb", "connection_profile": "LIVE"}},
            "connection_profiles": {"LIVE": {"usb_sources": True}},
            "source_decoders": [
                {"match": {"source": "brain", "type": "note", "note": 36}, "emit": {"physical": "kick.head", "expressions": ["velocity"]}},
                {"match": {"source": "brain", "type": "note", "note": 38}, "emit": {"physical": "snare.head", "expressions": ["velocity"]}},
            ],
            "physical_events": ["kick.head", "snare.head"],
            "state": {"scenes": ["metal"], "variables": [], "defaults": {"scene": "metal"}},
            "logical_control_protocol": {"scene": {"channels": [14, 15], "type": "program_change"}},
            "logical_routes": {"metal": {"kick.head": "kick.hit", "snare.head": "snare.head"}},
            "renderers": {"ddrum4": {"kick.hit": {"note": 36}, "snare.head": {"note": 36 if duplicate else 38}},
                          "sd3": {"kick.hit": {"note": 36}, "snare.head": {"note": 38}},
                          "drumgizmo": {"kick.hit": {"note": 36, "instrument": "kick", "articulation": "hit"},
                                         "snare.head": {"note": 38, "instrument": "snare", "articulation": "head"}}},
            "native_control_map": {}, "policies": {"echo": "disabled", "unknown_message": "drop"},
        }
        project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return project

    def test_validate_and_compile_golden_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, output = self._project(root), root / "out"
            validated = validate_project(project)
            self.assertEqual(validated.source_sha256, __import__("hashlib").sha256(project.read_bytes()).hexdigest())
            result = compile_project(project, output)
            self.assertEqual(len(result.artifacts), 10)
            report = json.loads((output / "project-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["format"], "rig-project-report/v1")
            self.assertEqual(report["source_sha256"], validated.source_sha256)
            self.assertEqual(dict((item["name"], item["status"]) for item in report["artifacts"])["ddti-preset"], "unresolved")
            self.assertFalse(yaml.safe_load((output / "ddti-preset.yaml").read_text(encoding="utf-8"))["transferable_dump"])
            runtime = yaml.safe_load((output / "runtime-profile.yaml").read_text(encoding="utf-8"))
            self.assertEqual(runtime["records"][1]["renderers"]["ddrum4"]["note"], 38)
            self.assertEqual(runtime["records"][0]["match"]["type"], "note")
            self.assertIn("source", runtime["records"][0])
            self.assertEqual(runtime["source_decoders"], validated.document["source_decoders"])
            self.assertEqual(runtime["sources"], validated.document["sources"])
            self.assertEqual(runtime["state"], validated.document["state"])
            self.assertEqual(runtime["source_sha256"], validated.source_sha256)
            firmware = json.loads((output / "firmware-project-mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(firmware["logical_control_protocol"], validated.document["logical_control_protocol"])
            self.assertEqual(firmware["native_control_map"], validated.document["native_control_map"])
            self.assertEqual(firmware["state"], validated.document["state"])
            self.assertEqual(firmware["ddrum_state_actions"], {})
            self.assertEqual(firmware["status"], "simulation-only")
            self.assertFalse((output / "firmware-project-mapping.h").exists())
            self.assertIn("rig-compiler/v1", (output / "sd3-megakit-map.md").read_text(encoding="utf-8"))
            drumgizmo = json.loads((output / "drumgizmo-midimap.json").read_text(encoding="utf-8"))
            self.assertEqual(drumgizmo["source_renderer"], "drumgizmo")
            self.assertEqual(drumgizmo["status"], "ready")
            self.assertEqual([item["note"] for item in drumgizmo["mappings"]], [36, 38])
            self.assertEqual(drumgizmo["mappings"][0]["instrument"], "kick")
            self.assertEqual(drumgizmo_note_overrides(output / "drumgizmo-midimap.json"),
                             {("kick", "hit"): 36, ("snare", "head"): 38})

    def test_compile_refuses_replace_without_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, output = self._project(root), root / "out"
            compile_project(project, output)
            with self.assertRaises(FileExistsError):
                compile_project(project, output)
            compile_project(project, output, replace=True)

    def test_compiler_keeps_distinct_records_when_two_modules_decode_one_pad(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            document["sources"]["ddti"] = {"endpoint": "ddti", "channel": 2, "primary": "usb", "connection_profile": "LIVE"}
            document["source_decoders"].append({
                "match": {"source": "ddti", "type": "note", "note": 38},
                "emit": {"physical": "snare.head", "expressions": ["velocity"]},
            })
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

            result = validate_project(project)

            ids = [record["id"] for record in result.artifacts["runtime-profile.yaml"]["records"]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertIn("metal.brain.snare.head", ids)
            self.assertIn("metal.ddti.snare.head", ids)

    def test_validation_rejects_domain_decoder_conflict_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            document["source_decoders"][1]["match"]["note"] = 36
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(RigCompilerError, "overlapping"):
                compile_project(project, root / "out")
            self.assertFalse((root / "out").exists())

    def test_cli_is_offline_and_base_dump_is_only_a_confirmation_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, output, dump = self._project(root), root / "out", root / "observed.syx"
            dump.write_bytes(b"not a generated dump")
            self.assertEqual(main(["validate", str(project)]), 0)
            self.assertEqual(main(["compile", str(project), "--output", str(output), "--base-dump", str(dump)]), 0)
            status = yaml.safe_load((output / "ddti-preset.yaml").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "planned")
            self.assertEqual(status["base_dump"]["path"], str(dump))
            self.assertEqual(status["base_dump"]["sha256"], __import__("hashlib").sha256(dump.read_bytes()).hexdigest())
            self.assertFalse(status["transferable_dump"])
            self.assertFalse(any(path.suffix == ".syx" for path in output.iterdir()))

    def test_runtime_preserves_range_cc_and_renderer_specific_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            document["source_decoders"][0]["match"] = {"source": "brain", "type": "note_range", "note_range": [36, 37]}
            document["source_decoders"][1]["match"] = {"source": "brain", "type": "cc", "cc": 4}
            document["source_decoders"][1]["emit"] = {"physical": "snare.head", "expressions": ["position"], "normalize": "cc7"}
            document["renderers"]["sd3"]["kick.hit"]["note"] = 99
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            result = compile_project(project, root / "out")
            runtime = result.artifacts["runtime-profile.yaml"]
            self.assertEqual(runtime["records"][0]["match"]["note_range"], [36, 37])
            self.assertEqual(runtime["records"][1]["match"]["cc"], 4)
            self.assertEqual(runtime["records"][0]["renderers"]["ddrum4"]["note"], 36)
            self.assertEqual(runtime["records"][0]["renderers"]["sd3"]["note"], 99)
            megakit = (root / "out" / "sd3-megakit-map.md").read_text(encoding="utf-8")
            self.assertIn("| metal.kick.head | 99 | kick.hit |", megakit)

    def test_validation_rejects_duplicate_measured_drumgizmo_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            document["renderers"]["drumgizmo"]["snare.head"]["note"] = 36
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(RigCompilerError, "drumgizmo renderer: note 36"):
                validate_project(project)

    def test_compiler_orders_scene_vp_variants_before_the_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            document["state"] = {"scenes": ["metal"], "variables": ["vp1"],
                                 "defaults": {"scene": "metal", "vp1": 0}}
            document["logical_control_protocol"] = {
                "scene": {"channels": [14, 15], "type": "program_change"},
                "vp1": {"channels": [14, 15], "type": "cc", "cc": 20},
            }
            document["native_control_map"] = {
                "brain_program": {"decode_to": "scene", "source": "brain", "channel": 10, "type": "program_change", "program": 0, "value": 0},
            }
            document["logical_routes"]["metal"]["snare.head"] = [
                {"logical_target": "snare.alt", "when": {"vp1": 1}},
                {"logical_target": "snare.head"},
            ]
            for renderer, note in (("ddrum4", 41), ("sd3", 51), ("drumgizmo", 61)):
                target = {"note": note}
                if renderer == "drumgizmo":
                    target.update({"instrument": "snare", "articulation": "alt"})
                document["renderers"][renderer]["snare.alt"] = target
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

            result = compile_project(project, root / "out")
            snare_records = [record for record in result.artifacts["runtime-profile.yaml"]["records"]
                             if record["physical"] == "snare.head"]
            self.assertEqual([record["state_predicates"] for record in snare_records], [{"vp1": 1}, {}])
            self.assertEqual([record["logical_target"] for record in snare_records], ["snare.alt", "snare.head"])

    def test_ready_firmware_plan_generates_scene_vp_progmem_header(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            document["state"] = {"scenes": ["metal"], "variables": ["vp1"],
                                 "defaults": {"scene": "metal", "vp1": 0}}
            document["logical_control_protocol"] = {
                "scene": {"channels": [14, 15], "type": "program_change"},
                "vp1": {"channels": [14, 15], "type": "cc", "cc": 20},
            }
            document["native_control_map"] = {
                "brain_program": {"decode_to": "scene", "source": "brain", "channel": 10, "type": "program_change", "program": 0, "value": 0},
            }
            document["logical_routes"]["metal"]["snare.head"] = [
                {"logical_target": "snare.alt", "when": {"vp1": 1}},
                {"logical_target": "snare.head"},
            ]
            for renderer, note in (("ddrum4", 41), ("sd3", 51), ("drumgizmo", 61)):
                target = {"note": note}
                if renderer == "drumgizmo":
                    target.update({"instrument": "snare", "articulation": "alt"})
                document["renderers"][renderer]["snare.alt"] = target
            document["deployment"] = "live"
            document["sources"]["ddrum4"] = document["sources"].pop("brain")
            for decoder in document["source_decoders"]:
                decoder["match"]["source"] = "ddrum4"
            document["native_control_map"]["brain_program"]["source"] = "ddrum4"
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            output = root / "out"
            compile_project(project, output)
            header = root / "generated_mapping.h"
            result = subprocess.run(
                [sys.executable, str(FIRMWARE_GENERATOR), "--project-mapping",
                 str(output / "firmware-project-mapping.json"), "--output-channel", "10",
                 "--output", str(header)], capture_output=True, text=True, check=False)

            self.assertEqual(result.returncode, 0, result.stderr)
            generated = header.read_text(encoding="utf-8")
            self.assertIn("const StateRoute STATE_ROUTES[] PROGMEM", generated)
            self.assertIn("const NativeControlRoute NATIVE_CONTROLS[] PROGMEM", generated)
            self.assertIn("{10, NativeControlType::ProgramChange, 0, 0, 0},", generated)
            self.assertIn("constexpr size_t NATIVE_CONTROL_COUNT = 1;", generated)
            self.assertIn("constexpr LogicalControlConfig LOGICAL_CONTROLS = {20, 255, 255, 255};", generated)
            self.assertIn("constexpr LogicalState INITIAL_LOGICAL_STATE = {0, 0, 0, 0, 0};", generated)

    def test_simulation_firmware_plan_is_rejected_by_generator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, output = self._project(root), root / "out"
            compile_project(project, output)
            result = subprocess.run(
                [sys.executable, str(FIRMWARE_GENERATOR), "--project-mapping",
                 str(output / "firmware-project-mapping.json"), "--output-channel", "10",
                 "--output", str(root / "generated_mapping.h")], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertIn("verified live flash plan", result.stderr)

    def test_placeholders_and_zero_notes_keep_artifacts_planned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            document["sources"]["brain"]["endpoint"] = "MEASURE_ME_ENDPOINT"
            document["renderers"]["ddrum4"]["kick.hit"]["note"] = 0
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            result = validate_project(project)
            statuses = {item["name"]: item["status"] for item in result.artifacts["project-report.json"]["artifacts"]}
            self.assertEqual(statuses["runtime-profile"], "planned")
            self.assertEqual(statuses["firmware-project-mapping"], "planned")
            self.assertEqual(statuses["ddrum4-bank-plan"], "planned")
            self.assertEqual(statuses["sd3-midimap"], "user-confirmed")
            self.assertEqual(statuses["drumgizmo-midimap"], "planned")
            self.assertEqual(main(["report", str(project)]), 0)
