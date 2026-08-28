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
            "control_bus": {"endpoint": "SIM_control", "channel": 15, "status": "planned"},
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
            self.assertEqual(len(result.artifacts), 14)
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
            self.assertEqual(runtime["control_bus"], validated.document["control_bus"])
            self.assertEqual(runtime["hardware_io"], "disabled")
            self.assertEqual(runtime["source_sha256"], validated.source_sha256)
            firmware = json.loads((output / "firmware-project-mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(firmware["logical_control_protocol"], validated.document["logical_control_protocol"])
            self.assertEqual(firmware["native_control_map"], validated.document["native_control_map"])
            self.assertEqual(firmware["state"], validated.document["state"])
            self.assertEqual(firmware["ddrum_state_actions"], {})
            self.assertEqual(firmware["status"], "simulation-only")
            self.assertFalse((output / "firmware-project-mapping.h").exists())
            self.assertNotIn("bank_reference", yaml.safe_load((output / "ddrum4-bank-plan.yaml").read_text(encoding="utf-8")))
            self.assertIn("rig-compiler/v1", (output / "sd3-megakit-map.md").read_text(encoding="utf-8"))
            drumgizmo = json.loads((output / "drumgizmo-midimap.json").read_text(encoding="utf-8"))
            self.assertEqual(drumgizmo["source_renderer"], "drumgizmo")
            self.assertEqual(drumgizmo["status"], "ready")
            self.assertEqual([item["note"] for item in drumgizmo["mappings"]], [36, 38])
            self.assertEqual(drumgizmo["mappings"][0]["instrument"], "kick")
            self.assertEqual(drumgizmo_note_overrides(output / "drumgizmo-midimap.json"),
                             {("kick", "hit"): 36, ("snare", "head"): 38})
            virtual_kit = json.loads((output / "virtual-kit-map.json").read_text(encoding="utf-8"))
            self.assertEqual(virtual_kit["format"], "virtual-kit-map/v1")
            self.assertEqual(virtual_kit["status"], "ready")
            self.assertEqual(virtual_kit["rows"][0]["ddrum4"], {"channel": 10, "note": 36})
            self.assertEqual(virtual_kit["rows"][1]["drumgizmo"]["articulation"], "head")
            expressions = json.loads((output / "expression-capability-report.json").read_text(encoding="utf-8"))
            self.assertEqual(expressions["summary"], {
                "declared_expressions": 0, "supported_expressions": 0, "firmware_unlowerable_routes": 0,
            })

    def test_expression_decoder_keeps_runtime_and_firmware_planned_with_explicit_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            document["source_decoders"].append({
                "match": {"source": "brain", "type": "cc", "cc": 4},
                "emit": {"physical": "kick.head", "expressions": ["openness"], "normalize": "cc7"},
            })
            document["renderers"]["sd3"]["kick.hit"]["cc"] = 4
            document["expression_routing"] = [{
                "source": "brain", "physical": "kick.head", "expression": "openness", "correlation": "none",
                "targets": {
                    "ddrum4": {"status": "planned", "event": {"type": "quantized_note_p"}},
                    "sd3": {"status": "user-confirmed", "event": {"type": "cc", "channel": 10, "cc": 4, "transform": "passthrough"}},
                    "drumgizmo": {"status": "unsupported", "reason": "note-only MVP", "event": {"type": "unsupported"}},
                },
            }]
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            result = compile_project(project, root / "out")

            statuses = {entry["name"]: entry["status"] for entry in result.artifacts["project-report.json"]["artifacts"]}
            self.assertEqual(statuses["runtime-profile"], "planned")
            self.assertEqual(statuses["firmware-project-mapping"], "planned")
            self.assertEqual(statuses["expression-capability-report"], "planned")
            self.assertEqual(statuses["virtual-kit-map"], "planned")
            report = json.loads((root / "out" / "expression-capability-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["expressions"][0]["targets"]["arduino_ddrum4"]["status"], "unsupported")
            self.assertEqual(report["expressions"][0]["targets"]["sd3"]["status"], "supported")
            runtime = yaml.safe_load((root / "out" / "runtime-profile.yaml").read_text(encoding="utf-8"))
            self.assertEqual(runtime["target_status"], {"sd3": "ready", "drumgizmo": "planned"})
            virtual_kit = json.loads((root / "out" / "virtual-kit-map.json").read_text(encoding="utf-8"))
            expression_row = next(row for row in virtual_kit["rows"] if row["raw_match"]["type"] == "cc")
            self.assertEqual(expression_row["coverage"], "unsupported")
            sd3_map = json.loads((root / "out" / "sd3-midimap.json").read_text(encoding="utf-8"))
            self.assertEqual(sd3_map["status"], "user-confirmed")
            self.assertEqual(sd3_map["mappings"][-1]["event"], {"type": "cc", "channel": 10, "cc": 4, "transform": "passthrough"})
            self.assertEqual(sd3_map["unsupported_source_expressions"], [])

    def test_reviewed_drumgizmo_hihat_quantization_is_a_runtime_profile_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            document["source_decoders"].append({
                "match": {"source": "brain", "type": "cc", "cc": 4},
                "emit": {"physical": "kick.head", "expressions": ["openness"], "normalize": "cc7"},
            })
            document["renderers"]["sd3"]["kick.hit"]["cc"] = 4
            document["expression_routing"] = [{
                "source": "brain", "physical": "kick.head", "expression": "openness", "correlation": "none",
                "targets": {
                    "ddrum4": {"status": "planned", "event": {"type": "quantized_note_p"}},
                    "sd3": {"status": "user-confirmed", "event": {"type": "cc", "channel": 10, "cc": 4, "transform": "passthrough"}},
                    "drumgizmo": {"status": "user-confirmed", "event": {
                        "type": "quantized_note", "input_closed": 127, "input_open": 0,
                        "articulations": [{"physical": "kick.head", "notes": [36, 44], "upper_boundaries": [63]}],
                    }},
                },
            }]
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            compile_project(project, root / "out")

            runtime = yaml.safe_load((root / "out" / "runtime-profile.yaml").read_text(encoding="utf-8"))
            self.assertEqual(runtime["target_status"], {"sd3": "ready", "drumgizmo": "ready"})
            report = json.loads((root / "out" / "expression-capability-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["expressions"][0]["targets"]["drumgizmo"]["status"], "supported")

    def test_reviewed_pressure_route_uses_the_active_rendered_hit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            document["source_decoders"].append({
                "match": {"source": "brain", "type": "poly_aftertouch", "active_note": True},
                "emit": {"physical": "kick.head", "expressions": ["pressure"], "correlate": "source_channel_note"},
            })
            document["expression_routing"] = [{
                "source": "brain", "physical": "kick.head", "expression": "pressure", "correlation": "source_channel_note",
                "targets": {
                    "ddrum4": {"status": "user-confirmed", "event": {"type": "poly_aftertouch", "note_from": "active_rendered_hit"}},
                    "sd3": {"status": "user-confirmed", "event": {"type": "poly_aftertouch", "note_from": "active_rendered_hit"}},
                    "drumgizmo": {"status": "unsupported", "reason": "no measured choke behavior", "event": {"type": "unsupported"}},
                },
            }]
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            compile_project(project, root / "out")

            runtime = yaml.safe_load((root / "out" / "runtime-profile.yaml").read_text(encoding="utf-8"))
            self.assertEqual(runtime["target_status"], {"sd3": "ready", "drumgizmo": "planned"})
            report = json.loads((root / "out" / "expression-capability-report.json").read_text(encoding="utf-8"))
            targets = report["expressions"][0]["targets"]
            self.assertEqual(targets["arduino_ddrum4"]["status"], "supported")
            self.assertEqual(targets["sd3"]["status"], "supported")

    def test_live_non_exact_note_route_never_creates_a_flashable_firmware_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            document["deployment"] = "live"
            document["control_bus"] = {"endpoint": "reviewed-control-bus", "channel": 15, "status": "user-confirmed"}
            document["sources"]["ddrum4"] = document["sources"].pop("brain")
            for decoder in document["source_decoders"]:
                decoder["match"]["source"] = "ddrum4"
            document["source_decoders"][0]["match"] = {"source": "brain", "type": "note_range", "note_range": [36, 37]}
            document["source_decoders"][0]["match"]["source"] = "ddrum4"
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            output = root / "out"

            result = compile_project(project, output)

            statuses = {entry["name"]: entry["status"] for entry in result.artifacts["project-report.json"]["artifacts"]}
            self.assertEqual(statuses["runtime-profile"], "ready")
            self.assertEqual(statuses["firmware-project-mapping"], "planned")
            self.assertEqual(statuses["virtual-kit-map"], "planned")
            firmware = json.loads((output / "firmware-project-mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(firmware["hardware_flash"], "disabled")
            capability = json.loads((output / "expression-capability-report.json").read_text(encoding="utf-8"))
            self.assertEqual(capability["summary"]["firmware_unlowerable_routes"], 1)
            virtual_kit = json.loads((output / "virtual-kit-map.json").read_text(encoding="utf-8"))
            self.assertEqual(virtual_kit["rows"][0]["coverage"], "planned")
            generator = subprocess.run(
                [sys.executable, str(FIRMWARE_GENERATOR), "--project-mapping", str(output / "firmware-project-mapping.json"),
                 "--output-channel", "10", "--output", str(root / "generated_mapping.h")],
                capture_output=True, text=True, check=False)
            self.assertEqual(generator.returncode, 2)
            self.assertIn("verified live flash plan", generator.stderr)

    def test_live_planned_or_sysex_state_action_never_creates_a_flashable_firmware_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            document["deployment"] = "live"
            document["control_bus"] = {"endpoint": "reviewed-control-bus", "channel": 15, "status": "user-confirmed"}
            document["sources"]["ddrum4"] = document["sources"].pop("brain")
            for decoder in document["source_decoders"]:
                decoder["match"]["source"] = "ddrum4"
            for action, expected in (
                ({"type": "program_change", "status": "planned", "channel": 10, "program": 0}, "action status is 'planned'"),
                ({"type": "sysex", "status": "measured", "data": [1, 2, 3]}, "Uno mapping supports reviewed Program Change actions only"),
            ):
                document["ddrum_state_actions"] = {"metal": [action]}
                project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
                output = root / f"out-{action['type']}-{action['status']}"
                result = compile_project(project, output)
                statuses = {entry["name"]: entry["status"] for entry in result.artifacts["project-report.json"]["artifacts"]}
                self.assertEqual(statuses["firmware-project-mapping"], "planned")
                firmware = json.loads((output / "firmware-project-mapping.json").read_text(encoding="utf-8"))
                self.assertEqual(firmware["hardware_flash"], "disabled")
                self.assertEqual(firmware["lowering_blockers"], [{"id": "ddrum_state_actions.metal[0]", "reason": expected}])
                generator = subprocess.run(
                    [sys.executable, str(FIRMWARE_GENERATOR), "--project-mapping", str(output / "firmware-project-mapping.json"),
                     "--output-channel", "10", "--output", str(root / "generated_mapping.h")],
                    capture_output=True, text=True, check=False)
                self.assertEqual(generator.returncode, 2)
                self.assertIn("verified live flash plan", generator.stderr)

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
            document["physical_events"].append("hh.bow")
            document["source_decoders"].extend([
                {"match": {"source": "brain", "type": "note", "note": 42},
                 "emit": {"physical": "hh.bow", "expressions": ["velocity"]}},
                {"match": {"source": "brain", "type": "cc", "cc": 4},
                 "emit": {"physical": "hh.bow", "expressions": ["openness"], "normalize": "cc7"}},
            ])
            document["logical_routes"]["metal"]["hh.bow"] = "hh.bow"
            document["renderers"]["ddrum4"]["hh.bow"] = {"note": 72}
            document["renderers"]["sd3"]["hh.bow"] = {"note": 64, "channel": 10, "cc": 4}
            document["renderers"]["drumgizmo"]["hh.bow"] = {"note": 64, "instrument": "hihat", "articulation": "bow"}
            document["expression_routing"] = [{
                "source": "brain", "physical": "hh.bow", "expression": "openness", "correlation": "none",
                "targets": {
                    "ddrum4": {"status": "user-confirmed", "event": {
                        "type": "quantized_note_p", "note_from": "active_rendered_hit",
                        "input_closed": 127, "input_open": 0,
                        "articulations": [{"physical": "hh.bow", "notes": [72, 73, 74, 75, 76],
                                           "upper_boundaries": [25, 50, 75, 100]}],
                    }},
                    "sd3": {"status": "user-confirmed", "event": {"type": "cc", "channel": 10, "cc": 4, "transform": "passthrough"}},
                    "drumgizmo": {"status": "unsupported", "reason": "note-only", "event": {"type": "unsupported"}},
                },
            }]
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
            document["physical_events"].append("hh.bow")
            document["source_decoders"].extend([
                {"match": {"source": "brain", "type": "note", "note": 42},
                 "emit": {"physical": "hh.bow", "expressions": ["velocity"]}},
                {"match": {"source": "brain", "type": "cc", "cc": 4},
                 "emit": {"physical": "hh.bow", "expressions": ["openness"], "normalize": "cc7"}},
            ])
            document["logical_routes"]["metal"]["hh.bow"] = "hh.bow"
            document["renderers"]["ddrum4"]["hh.bow"] = {"note": 72}
            document["renderers"]["sd3"]["hh.bow"] = {"note": 64, "channel": 10, "cc": 4}
            document["renderers"]["drumgizmo"]["hh.bow"] = {"note": 64, "instrument": "hihat", "articulation": "bow"}
            document["expression_routing"] = [{
                "source": "brain", "physical": "hh.bow", "expression": "openness", "correlation": "none",
                "targets": {
                    "ddrum4": {"status": "user-confirmed", "event": {
                        "type": "quantized_note_p", "note_from": "active_rendered_hit",
                        "input_closed": 127, "input_open": 0,
                        "articulations": [{"physical": "hh.bow", "notes": [72, 73, 74, 75, 76],
                                           "upper_boundaries": [25, 50, 75, 100]}],
                    }},
                    "sd3": {"status": "user-confirmed", "event": {"type": "cc", "channel": 10, "cc": 4, "transform": "passthrough"}},
                    "drumgizmo": {"status": "unsupported", "reason": "note-only", "event": {"type": "unsupported"}},
                },
            }]
            for renderer, note in (("ddrum4", 41), ("sd3", 51), ("drumgizmo", 61)):
                target = {"note": note}
                if renderer == "drumgizmo":
                    target.update({"instrument": "snare", "articulation": "alt"})
                document["renderers"][renderer]["snare.alt"] = target
            document["deployment"] = "live"
            document["control_bus"] = {"endpoint": "verified-control-bus", "channel": 15,
                                       "status": "user-confirmed"}
            bank = root / "bank.yaml"
            bank.write_text(yaml.safe_dump({"bank": {"id": "fixture-bank", "midi_channel": 10}, "sounds": [
                {"note_base": 36, "note_p": 1}, {"note_base": 38, "note_p": 1}, {"note_base": 41, "note_p": 1},
                {"note_base": 72, "note_p": 8},
            ]}, sort_keys=False), encoding="utf-8")
            document["ddrum4_bank"] = {"manifest": "bank.yaml", "bank_id": "fixture-bank"}
            document["sources"]["ddrum4"] = document["sources"].pop("brain")
            for decoder in document["source_decoders"]:
                decoder["match"]["source"] = "ddrum4"
            document["expression_routing"][0]["source"] = "ddrum4"
            document["source_decoders"].append({
                "match": {"source": "ddrum4", "type": "poly_aftertouch", "active_note": True},
                "emit": {"physical": "snare.head", "expressions": ["pressure"], "correlate": "source_channel_note"},
            })
            document["expression_routing"].append({
                "source": "ddrum4", "physical": "snare.head", "expression": "pressure", "correlation": "source_channel_note",
                "targets": {
                    "ddrum4": {"status": "user-confirmed", "event": {"type": "poly_aftertouch", "note_from": "active_rendered_hit"}},
                    "sd3": {"status": "user-confirmed", "event": {"type": "poly_aftertouch", "note_from": "active_rendered_hit"}},
                    "drumgizmo": {"status": "unsupported", "reason": "fixture has no measured choke behavior", "event": {"type": "unsupported"}},
                },
            })
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
            self.assertIn("constexpr LogicalControlConfig LOGICAL_CONTROLS = {20, 255, 255, 255, 1};", generated)
            self.assertIn("constexpr LogicalState INITIAL_LOGICAL_STATE = {0, 0, 0, 0, 0};", generated)
            self.assertIn("constexpr HihatQuantizedConfig HIHAT_QUANTIZED = {10, 4, 127, 0, true};", generated)
            self.assertIn("{10, 42, 72, 5, {25, 50, 75, 100, 0, 0, 0}, {72, 73, 74, 75, 76, 0, 0, 0}}", generated)
            self.assertIn("const PressureRoute PRESSURE_ROUTES[] PROGMEM", generated)
            self.assertIn("{10, 38},", generated)
            self.assertIn("constexpr size_t PRESSURE_ROUTE_COUNT = 1;", generated)
            wrong_channel = subprocess.run(
                [sys.executable, str(FIRMWARE_GENERATOR), "--project-mapping",
                 str(output / "firmware-project-mapping.json"), "--output-channel", "11",
                 "--output", str(root / "wrong-channel.h")], capture_output=True, text=True, check=False)
            self.assertEqual(wrong_channel.returncode, 2)
            self.assertIn("differs from the reviewed project", wrong_channel.stderr)
            runtime = yaml.safe_load((output / "runtime-profile.yaml").read_text(encoding="utf-8"))
            self.assertEqual(runtime["hardware_io"], "logical-control-only")

    def test_mvp_logical_protocol_is_limited_to_midi_and_firmware_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            document["state"]["scenes"] = [f"scene-{index}" for index in range(129)]
            document["state"]["defaults"]["scene"] = "scene-0"
            document["logical_routes"] = {scene: document["logical_routes"]["metal"]
                                          for scene in document["state"]["scenes"]}
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(RigCompilerError, "too long|128 scenes"):
                validate_project(project)

            document["state"] = {"scenes": ["metal"], "variables": ["vp1", "vp2", "vp3", "vp4", "vp5"],
                                 "defaults": {"scene": "metal", "vp1": 0, "vp2": 0, "vp3": 0, "vp4": 0, "vp5": 0}}
            document["logical_control_protocol"] = {"scene": {"channels": [14, 15], "type": "program_change"},
                                                    **{f"vp{index}": {"channels": [14, 15], "type": "cc", "cc": index}
                                                       for index in range(1, 6)}}
            document["logical_routes"] = {"metal": document["logical_routes"]["scene-0"]}
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(RigCompilerError, "too long|4 variables"):
                validate_project(project)

    def test_runtime_omits_absent_control_bus(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            document.pop("control_bus")
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            compile_project(project, root / "out")
            runtime = yaml.safe_load((root / "out" / "runtime-profile.yaml").read_text(encoding="utf-8"))
            self.assertNotIn("control_bus", runtime)
            self.assertEqual(runtime["hardware_io"], "disabled")

    def test_compiler_preserves_optional_ddrum4_bank_reference_in_bank_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            manifest = root / "bank.yaml"
            manifest.write_text(yaml.safe_dump({"bank": {"id": "fixture-bank", "midi_channel": 10},
                                                "sounds": [{"note_base": 36, "note_p": 1,
                                                            "variations": [{"number": 1, "name": "Main"}],
                                                            "layers": [{"position": 1, "velocity": 100, "sample": 1}]},
                                                           {"note_base": 38, "note_p": 1}]}, sort_keys=False), encoding="utf-8")
            document["ddrum4_bank"] = {"manifest": "bank.yaml", "bank_id": "fixture-bank",
                                       "reports": ["reports/actual-bank.json"]}
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            compile_project(project, root / "out")
            bank = yaml.safe_load((root / "out" / "ddrum4-bank-plan.yaml").read_text(encoding="utf-8"))
            self.assertEqual(bank["bank_reference"]["manifest"], "bank.yaml")
            self.assertEqual(Path(bank["bank_reference"]["manifest_resolved_path"]), manifest.resolve())
            self.assertEqual(bank["bank_reference"]["bank_id"], "fixture-bank")
            self.assertEqual(bank["bank_reference"]["midi_channel"], 10)
            self.assertEqual(bank["bank_reference"]["playable_notes"], [36, 38])
            virtual_kit = json.loads((root / "out" / "virtual-kit-map.json").read_text(encoding="utf-8"))
            self.assertEqual(virtual_kit["rows"][0]["ddrum4"],
                             {"channel": 10, "note": 36, "slot": 1, "sound_id": None, "note_p": 1,
                              "variations": [{"number": 1, "name": "Main"}],
                              "layer_candidates": [{"layer": 1, "velocity": 100, "sample": 1}]})

    def test_linked_bank_rejects_bad_hash_channel_and_renderer_note(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            manifest = root / "bank.yaml"
            manifest.write_text(yaml.safe_dump({"bank": {"id": "fixture-bank", "midi_channel": 9},
                                                "sounds": [{"note_base": 36, "note_p": 1}]}, sort_keys=False), encoding="utf-8")
            document["ddrum4_bank"] = {"manifest": "bank.yaml", "bank_id": "fixture-bank", "sha256": "0" * 64}
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(RigCompilerError, "midi_channel"):
                validate_project(project)

            manifest.write_text(yaml.safe_dump({"bank": {"id": "fixture-bank", "midi_channel": 10},
                                                "sounds": [{"note_base": 36, "note_p": 1}]}, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(RigCompilerError, "sha256"):
                validate_project(project)

            document["ddrum4_bank"].pop("sha256")
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(RigCompilerError, "outside the linked bank"):
                validate_project(project)

    def test_linked_bank_facts_survive_base_dump_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self._project(root)
            document = yaml.safe_load(project.read_text(encoding="utf-8"))
            manifest = root / "bank.yaml"
            manifest.write_text(yaml.safe_dump({"bank": {"id": "fixture-bank", "midi_channel": 10},
                                                "sounds": [{"note_base": 36, "note_p": 1},
                                                           {"note_base": 38, "note_p": 1}]}, sort_keys=False), encoding="utf-8")
            document["ddrum4_bank"] = {"manifest": "bank.yaml", "bank_id": "fixture-bank"}
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            dump = root / "base.syx"; dump.write_bytes(b"fixture dump")
            compile_project(project, root / "out", base_dump=dump)
            bank = yaml.safe_load((root / "out" / "ddrum4-bank-plan.yaml").read_text(encoding="utf-8"))
            reference = bank["bank_reference"]
            self.assertEqual((reference["bank_id"], reference["midi_channel"], reference["playable_notes"]),
                             ("fixture-bank", 10, [36, 38]))
            self.assertEqual(reference["sha256"], __import__("hashlib").sha256(manifest.read_bytes()).hexdigest())

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
