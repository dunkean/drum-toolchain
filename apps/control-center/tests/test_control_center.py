from __future__ import annotations

from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import json
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from control_center import ControlCenter
from control_center.ddrum4_matrix import UNKNOWN, audition_command, load_kit_matrix
from control_center.live_measurement import LiveMeasurementCampaign, discover_midi_port_inventory
from control_center.simulator import RigSimulator
from control_center.virtual_kit import build_virtual_kit
from control_center.campaign import (CaptureRow, Sd3CaptureCampaign, capture_rows_from_megakit_plan,
                                     fingerprint_sd3_preset,
                                     STARTER_ROWS, METALCORE_ELECTRONIC_V1_ADDITIONS)
from midi_lab.traces import MidiTrace, TraceEvent


class ControlCenterTests(unittest.TestCase):
    def test_midi_port_inventory_is_read_only_and_keeps_input_output_direction(self) -> None:
        inventory = discover_midi_port_inventory(lambda: ("UMC MIDI In", "eDrumIn BLACK"),
                                                 lambda: ("UMC MIDI Out", "TriggerIO"))

        self.assertEqual(inventory, {"inputs": ("UMC MIDI In", "eDrumIn BLACK"),
                                     "outputs": ("UMC MIDI Out", "TriggerIO")})

    def test_live_measurement_campaign_records_requirements_without_promoting_simulation_addresses(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "metalcore-r15-chain-simulator.yaml"
        campaign = LiveMeasurementCampaign.from_path(project)
        with tempfile.TemporaryDirectory() as temporary:
            plan, guide = campaign.write_new(Path(temporary))
            document = json.loads(plan.read_text(encoding="utf-8"))
            guide_text = guide.read_text(encoding="utf-8")

        self.assertEqual(document["kind"], "drum-live-measurement-campaign/v1")
        self.assertEqual(document["hardware_io"], "disabled")
        self.assertTrue(document["do_not_copy_simulation_addresses"])
        self.assertEqual(document["target_deployment"], "live")
        self.assertEqual({item["id"] for item in document["inputs"]}, {"ddrum4", "ddti", "edrumin"})
        self.assertIn("edrumin.hh.bow.cc-004", {item["id"] for item in document["trace_requests"]})
        self.assertIn("SIM_", document["inputs"][0]["declared_endpoint"])
        self.assertIn("Do not copy any `SIM_*`", guide_text)

    def test_live_measurement_campaign_reviews_only_unambiguous_isolated_note_traces(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "metalcore-r15-chain-simulator.yaml"
        campaign = LiveMeasurementCampaign.from_path(project)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign.write_new(root)
            first = next(decoder for decoder in campaign.project.source_decoders if decoder.message_type == "note")
            first_path = root / campaign.trace_relative_path(first)
            first_path.parent.mkdir()
            MidiTrace("captured source", (TraceEvent(0, "note_on", 12, 36, 100),)).write(first_path)
            initial = LiveMeasurementCampaign.read(root).review_traces(root)
            observed = next(row for row in initial["rows"] if row["id"] == campaign.trace_identifier(first))
            self.assertEqual(observed, {"id": campaign.trace_identifier(first),
                                        "trace": campaign.trace_relative_path(first),
                                        "message_type": "note", "status": "observed", "channel": 12,
                                        "data1": 36, "note": 36})
            self.assertEqual(initial["status"], "incomplete")
            for index, decoder in enumerate((item for item in campaign.project.source_decoders if item.message_type == "note"), start=1):
                path = root / campaign.trace_relative_path(decoder)
                path.parent.mkdir(exist_ok=True)
                MidiTrace("captured source", (TraceEvent(0, "note_on", 1, index, 100),)).write(path)
            expression = next(item for item in campaign.project.source_decoders if item.message_type == "cc")
            expression_path = root / campaign.trace_relative_path(expression)
            MidiTrace("captured source", (TraceEvent(0, "control_change", 1, 4, 0),
                                            TraceEvent(1, "control_change", 1, 4, 127))).write(expression_path)
            complete = campaign.review_traces(root)

        self.assertEqual(complete["status"], "capture-complete-not-live")
        self.assertTrue(all(row["status"] == "observed" for row in complete["rows"]))

    def test_live_measurement_campaign_promotes_only_complete_traces_to_a_new_non_sim_profile(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "metalcore-r15-chain-simulator.yaml"
        campaign = LiveMeasurementCampaign.from_path(project)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign.write_new(root)
            per_source = {"ddrum4": (12, 40), "ddti": (2, 60), "edrumin": (3, 80)}
            for offset, decoder in enumerate((item for item in campaign.project.source_decoders if item.message_type == "note")):
                path = root / campaign.trace_relative_path(decoder)
                path.parent.mkdir(exist_ok=True)
                channel, note = per_source[decoder.source]
                MidiTrace("captured source", (TraceEvent(0, "note_on", channel, note + offset, 100),)).write(path)
            expression = next(item for item in campaign.project.source_decoders if item.message_type == "cc")
            channel, _note = per_source[expression.source]
            expression_path = root / campaign.trace_relative_path(expression)
            MidiTrace("captured source", (TraceEvent(0, "control_change", channel, 4, 0),
                                            TraceEvent(1, "control_change", channel, 4, 127))).write(expression_path)
            destination = root / "metalcore-r15-live.yaml"
            result = campaign.promote_live(
                root, destination,
                endpoints={"ddrum4": "UMC MIDI In", "ddti": "TriggerIO", "edrumin": "eDrumIn BLACK"},
                control_endpoint="UMC MIDI Out",
            )
            live = yaml.safe_load(result.read_text(encoding="utf-8"))

        self.assertEqual(live["deployment"], "live")
        self.assertEqual(live["sources"]["ddrum4"]["endpoint"], "UMC MIDI In")
        self.assertEqual(live["sources"]["ddti"]["channel"], 2)
        self.assertEqual(live["control_bus"], {"endpoint": "UMC MIDI Out", "channel": 15, "status": "user-confirmed"})
        self.assertEqual(next(item for item in live["source_decoders"] if item["match"]["type"] == "cc")["match"]["cc"], 4)
        self.assertTrue(all(not source["endpoint"].startswith("SIM_") for source in live["sources"].values()))

    def test_live_measurement_keeps_two_raw_notes_for_one_physical_pad_distinct(self) -> None:
        source = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "two-zone-snare.yaml"
            document = yaml.safe_load(source.read_text(encoding="utf-8"))
            document["source_decoders"].append({
                "match": {"source": "edrumin", "type": "note", "note": 39},
                "emit": {"physical": "snare.head", "expressions": ["velocity"]},
            })
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            campaign = LiveMeasurementCampaign.from_path(project)
            campaign.write_new(root / "campaign")
            campaign_root = root / "campaign"
            snare_decoders = [decoder for decoder in campaign.project.source_decoders
                              if decoder.source == "edrumin" and decoder.physical == "snare.head"]
            self.assertEqual(len(snare_decoders), 2)
            self.assertEqual(len({campaign.trace_identifier(decoder) for decoder in snare_decoders}), 2)
            self.assertEqual(len({campaign.trace_relative_path(decoder) for decoder in snare_decoders}), 2)
            captured_notes: dict[str, int] = {}
            for offset, decoder in enumerate(campaign.project.source_decoders, start=70):
                path = campaign_root / campaign.trace_relative_path(decoder)
                path.parent.mkdir(exist_ok=True)
                captured_notes[campaign.trace_identifier(decoder)] = offset
                channel = {"edrumin": 3, "ddti": 2, "ddrum4": 12}[decoder.source]
                MidiTrace("captured source", (TraceEvent(0, "note_on", channel, offset, 100),)).write(path)
            output = campaign.promote_live(
                campaign_root, root / "measured-live.yaml",
                endpoints={"edrumin": "eDrumIn BLACK", "ddti": "TriggerIO", "ddrum4": "UMC MIDI In"},
                control_endpoint="UMC MIDI Out",
            )
            live = yaml.safe_load(output.read_text(encoding="utf-8"))

        promoted = [item["match"]["note"] for item in live["source_decoders"]
                    if item["match"]["source"] == "edrumin" and item["emit"]["physical"] == "snare.head"]
        expected = [captured_notes[campaign.trace_identifier(decoder)] for decoder in snare_decoders]
        self.assertEqual(promoted, expected)

    def test_live_measurement_refuses_to_auto_promote_a_note_range(self) -> None:
        source = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "range.yaml"
            document = yaml.safe_load(source.read_text(encoding="utf-8"))
            document["source_decoders"][0]["match"] = {"source": "edrumin", "type": "note_range", "note_range": [38, 39]}
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            campaign = LiveMeasurementCampaign.from_path(project)
            plan = campaign.to_document()
            review = campaign.review_traces(Path(temporary))

        request = next(item for item in plan["trace_requests"] if item["message_type"] == "note_range")
        row = next(item for item in review["rows"] if item["message_type"] == "note_range")
        self.assertEqual(request["status"], "manual-range-measurement-required")
        self.assertIsNone(request["trace"])
        self.assertEqual(row["status"], "manual-range-measurement-required")
        self.assertEqual(review["status"], "incomplete")

    def test_sd3_campaign_writes_resumable_sampler_session_and_reports_file_progress(self) -> None:
        campaign = Sd3CaptureCampaign(
            identifier="sd3_test_kit", sd3_preset="Test MegaKit", midi_output="SD3 input",
            audio_input="UMC404HD input 1-2", channels=("left", "right"),
            rows=(CaptureRow("snare_main", "rimshot", 40, (40, 80), 2),),
        )
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / campaign.identifier
            campaign.write_new(run)
            session = json.loads((run / "capture-session.json").read_text(encoding="utf-8"))
            self.assertEqual(session["kind"], "capture-session")
            self.assertEqual(session["requests"][0]["note"], 40)
            self.assertEqual(session["requests"][0]["velocities"], [40, 80])
            self.assertEqual(session["requests"][0]["controllers"], [])
            self.assertEqual(campaign.progress(run).captured_takes, 0)
            self.assertFalse(campaign.progress(run).calibration_report_exists)
            raw = run / "raw-wav"; raw.mkdir()
            (raw / "snare_main__rimshot__v040__rr01_raw.wav").write_bytes(b"raw")
            progress = Sd3CaptureCampaign.read(run).progress(run)
            self.assertEqual((progress.captured_takes, progress.total_takes, progress.missing_takes), (1, 4, 3))
            with self.assertRaisesRegex(FileExistsError, "campaign directory"):
                campaign.write_new(run)

            reports = run / "reports"; reports.mkdir()
            (reports / "calibration.json").write_text(
                json.dumps({
                    "session_sha256": hashlib.sha256((run / "capture-session.json").read_bytes()).hexdigest(),
                    "summary": {"status": "technical-fail"},
                }), encoding="utf-8",
            )
            failed = campaign.progress(run)
            self.assertEqual(failed.calibration_status, "technical-fail")
            self.assertIn("failed", failed.stage)

    def test_campaign_commands_are_ordered_and_capture_is_explicit(self) -> None:
        run = Path("D:/Studio/drum-runs/sd3_test_kit")
        center = ControlCenter()
        with self.assertRaisesRegex(ValueError, "explicit confirmation"):
            center.sampler_command("capture", run)
        capture = center.sampler_command("capture", run, confirm_capture=True)
        self.assertIn("--confirm-capture", capture)
        self.assertEqual(capture[1:4], ("-m", "drum_sampler.cli", "capture"))
        with self.assertRaisesRegex(ValueError, "explicit confirmation"):
            center.sampler_command("calibrate", run)
        with self.assertRaisesRegex(ValueError, "valid campaign"):
            center.sampler_command("calibrate", run, confirm_capture=True)
        quality = center.sampler_command("audit-quality", run)
        self.assertEqual(quality[1:4], ("-m", "drum_sampler.cli", "audit-quality"))
        with self.assertRaisesRegex(ValueError, "note map"):
            center.sampler_command("export-drumgizmo", run)
        with self.assertRaisesRegex(ValueError, "MegaKit plan"):
            center.sampler_command("export-drumgizmo", run, note_map=Path("drumgizmo-midimap.json"))

    def test_full_campaign_is_gated_by_passing_signal_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preset = root / "MegaKit.sd3p"; preset.write_bytes(b"fingerprinted-preset")
            preset_file, preset_sha = fingerprint_sd3_preset(preset)
            campaign = Sd3CaptureCampaign(
                identifier="sd3_gate", sd3_preset="MegaKit", midi_output="virtual",
                audio_input="loopback:output", channels=("left", "right"),
                rows=(CaptureRow("kick", "acoustic", 24, (120,), 1),),
                sd3_preset_file=preset_file, sd3_preset_sha256=preset_sha,
            )
            run = root / "sd3_gate"
            campaign.write_new(run)
            with self.assertRaisesRegex(ValueError, "exact current session"):
                ControlCenter.sampler_command("capture", run, confirm_capture=True)
            report = run / "reports" / "calibration.json"
            report.parent.mkdir()
            report.write_text(json.dumps({
                "format": "sd3-calibration-report/v1",
                "session_sha256": hashlib.sha256((run / "capture-session.json").read_bytes()).hexdigest(),
                "preset": {"sha256": preset_sha, "loaded_confirmed": True},
                "summary": {"status": "technical-pass-user-mix-review-required"},
            }), encoding="utf-8")
            command = ControlCenter.sampler_command("capture", run, confirm_capture=True)
            self.assertEqual(command[3], "capture")
            calibration = ControlCenter.sampler_command("calibrate", run, confirm_capture=True)
            self.assertIn("--confirm-preset-loaded", calibration)
            self.assertIn(preset_sha, calibration)

            document = json.loads(report.read_text(encoding="utf-8"))
            document["session_sha256"] = "0" * 64
            report.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exact current session"):
                ControlCenter.sampler_command("capture", run, confirm_capture=True)

    def test_v1_electronic_additions_have_unique_raw_capture_cells(self) -> None:
        filenames = [filename for row in METALCORE_ELECTRONIC_V1_ADDITIONS for filename in row.raw_filenames()]
        self.assertEqual(len(filenames), len(set(filenames)))
        self.assertEqual({row.note for row in METALCORE_ELECTRONIC_V1_ADDITIONS} & {26, 47, 68, 85, 93},
                         {26, 47, 68, 85, 93})

    def test_r15_megakit_plan_generates_complete_nonduplicated_capture_rows(self) -> None:
        plan = Path(__file__).resolve().parents[3] / "profiles" / "sd3" / "metalcore-r15-megakit-plan.yaml"
        rows = capture_rows_from_megakit_plan(plan)

        self.assertGreater(len(rows), len(STARTER_ROWS))
        self.assertEqual(len({row.raw_filenames() for row in rows}), len(rows))
        self.assertIn(CaptureRow("snare1", "deftones", 37, (24, 40, 56, 72, 88, 104, 120), 3), rows)
        self.assertIn(CaptureRow("tom4", "sleep", 63, (24, 48, 72, 96, 120), 2), rows)
        bow = [row for row in rows if row.instrument == "hh" and row.articulation.startswith("bow_")]
        edge = [row for row in rows if row.instrument == "hh" and row.articulation.startswith("edge_")]
        self.assertEqual((len(bow), len(edge)), (5, 4))
        self.assertEqual({row.controllers for row in bow}, {((4, 127),), ((4, 96),), ((4, 64),), ((4, 32),), ((4, 0),)})
        self.assertEqual({row.drumgizmo_note for row in bow + edge}, set(range(112, 121)))
        self.assertNotIn("perc_cowbell", {row.instrument for row in rows})
        self.assertNotIn("stack_metallic", {row.instrument for row in rows})

    def test_cli_creates_complete_sd3_campaign_from_megakit_plan(self) -> None:
        repository = Path(__file__).resolve().parents[3]
        plan = repository / "profiles" / "sd3" / "metalcore-r15-megakit-plan.yaml"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "campaign"
            preset = root / "MegaKit.sd3p"; preset.write_bytes(b"preset")
            command = [
                sys.executable, "-m", "control_center.cli", "create-sd3-campaign", str(plan),
                "--output", str(output), "--id", "greg_hybrid_r15_full",
                "--preset", "Greg_Hybrid_r15_MegaKit_v2", "--midi-output", "SD3_MEGA_INPUT",
                "--preset-file", str(preset), "--audio-input", "SD3_PRINT_LOOPBACK",
            ]
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            campaign = Sd3CaptureCampaign.read(output)
            self.assertEqual(len(campaign.rows), len(capture_rows_from_megakit_plan(plan)))
            self.assertGreater(campaign.total_takes, 500)
            self.assertEqual(campaign.sd3_preset_sha256, hashlib.sha256(b"preset").hexdigest())

    def test_complete_chain_simulator_traces_ddrum4_return_and_both_software_renderers(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        simulator = RigSimulator.from_path(project)
        simulator.set_state(scene="dnb")

        result = simulator.simulate_pad("ddrum4", 85, 106)

        self.assertEqual(result.physical, "stack.hit")
        self.assertEqual(result.logical_target, "perc.glitch")
        messages = {step.stage: step.message for step in result.steps}
        self.assertEqual(messages["Arduino DDrum4 renderer"]["note"], 86)
        self.assertEqual(messages["SD3 renderer"]["note"], 89)
        self.assertEqual(messages["DrumGizmo renderer"]["instrument"], "percussion")
        self.assertIn("hardware_io", result.to_document())
        self.assertTrue(result.to_document()["route_resolved"])
        self.assertFalse(result.renders_audio)

    def test_complete_chain_simulator_accepts_each_declared_module(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        simulator = RigSimulator.from_path(project)
        raw_notes = {"edrumin": 38, "ddti": 38, "ddrum4": 40}

        results = {source: simulator.simulate_pad(source, note) for source, note in raw_notes.items()}

        self.assertEqual({result.physical for result in results.values()}, {"snare.head"})
        self.assertEqual({result.logical_target for result in results.values()}, {"snare.metalcore"})

    def test_complete_chain_simulator_traces_logical_scene_to_declared_ddrum_program(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        simulator = RigSimulator.from_path(project)

        result = simulator.simulate_logical_control("pc", 15, "program_change", 1)

        self.assertEqual(result.state["scene"], "dnb")
        action = next(step for step in result.steps if step.stage == "Arduino DDrum4 state")
        self.assertEqual(action.message, {"type": "program_change", "channel": 12, "program": 1,
                                          "status": "user-confirmed"})
        self.assertTrue(result.to_document()["hardware_io"] == "disabled")

    def test_complete_chain_simulator_rejects_undeclared_logical_control(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        with self.assertRaisesRegex(ValueError, "not a declared"):
            RigSimulator.from_path(project).simulate_logical_control("pc", 15, "cc", 99, 1)

    def test_offline_diagnostic_covers_declared_pads_scenes_and_native_controls(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        report = RigSimulator.from_path(project).run_offline_diagnostic()

        self.assertTrue(report.passed)
        self.assertGreater(len(report.cases), 20)
        identifiers = {case.identifier for case in report.cases}
        self.assertIn("logical.scene.pc000", identifiers)
        self.assertIn("logical.scene.pc001", identifiers)
        self.assertIn("logical.scene.pc000.ch15", identifiers)
        self.assertIn("pad.edrumin.n038.v001.metalcore.vp1_snare0", identifiers)
        self.assertIn("pad.edrumin.n038.v127.metalcore.vp1_snare0", identifiers)
        self.assertIn("native.ddrum_program_metalcore", identifiers)
        self.assertEqual(report.to_document()["hardware_io"], "disabled")

    def test_native_control_simulation_changes_state_without_native_echo(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        result = RigSimulator.from_path(project).simulate_native_control("ddrum_program_dnb")

        self.assertEqual(result.state["scene"], "dnb")
        self.assertEqual(result.message, {"type": "program_change", "channel": 12, "data1": 1, "value": 1})
        self.assertFalse(any(step.stage == "Arduino DDrum4 state" for step in result.steps))

    def test_offline_diagnostic_fails_expression_paths_without_shared_renderer_support(self) -> None:
        source = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "cc-and-aftertouch.yaml"
            document = yaml.safe_load(source.read_text(encoding="utf-8"))
            document["source_decoders"].extend((
                {"match": {"source": "edrumin", "type": "cc", "cc": 4},
                 "emit": {"physical": "kick.hit", "expressions": ["position"], "normalize": "cc7"}},
                {"match": {"source": "ddti", "type": "poly_aftertouch", "note": 38},
                 "emit": {"physical": "snare.head", "expressions": ["pressure"]}},
            ))
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            simulator = RigSimulator.from_path(project)
            report = simulator.run_offline_diagnostic()
            cc = simulator.simulate_expression("edrumin", "cc", 4, 64)

        self.assertFalse(report.passed)
        failed = {case.identifier for case in report.cases if not case.passed}
        self.assertIn("cc.edrumin.n004.metalcore.vp1_snare0", failed)
        self.assertIn("poly_aftertouch.ddti.n038.metalcore.vp1_snare0", failed)
        self.assertFalse(cc.renders_audio)
        self.assertEqual(cc.to_document()["raw"], {"type": "control_change", "data1": 4, "value": 64})

    def test_simulator_traces_a_measured_sd3_openness_cc_without_claiming_ddrum_or_drumgizmo_support(self) -> None:
        source = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "sd3-openness.yaml"
            document = yaml.safe_load(source.read_text(encoding="utf-8"))
            document["source_decoders"].append({
                "match": {"source": "edrumin", "type": "cc", "cc": 4},
                "emit": {"physical": "kick.hit", "expressions": ["openness"], "normalize": "cc7"},
            })
            for logical in ("kick.acoustic", "kick.electronic"):
                document["renderers"]["sd3"][logical]["cc"] = 4
            document["expression_routing"] = [{
                "source": "edrumin", "physical": "kick.hit", "expression": "openness", "correlation": "none",
                "targets": {
                    "ddrum4": {"status": "planned", "event": {"type": "quantized_note_p"}},
                    "sd3": {"status": "user-confirmed", "event": {"type": "cc", "channel": 10, "cc": 4, "transform": "passthrough"}},
                    "drumgizmo": {"status": "unsupported", "reason": "note-only MVP", "event": {"type": "unsupported"}},
                },
            }]
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            result = RigSimulator.from_path(project).simulate_expression("edrumin", "cc", 4, 91)

        steps = {step.stage: step for step in result.steps}
        self.assertEqual(steps["SD3 renderer"].message, {"type": "control_change", "channel": 10, "cc": 4, "value": 91})
        self.assertEqual(steps["Arduino DDrum4 renderer"].message["status"], "planned")
        self.assertFalse(result.renders_audio)

    def test_simulator_previews_declared_pressure_on_the_correlated_active_hit(self) -> None:
        source = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "complete-chain-simulator.yaml"
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "pressure.yaml"
            document = yaml.safe_load(source.read_text(encoding="utf-8"))
            document["source_decoders"].append({
                "match": {"source": "edrumin", "type": "poly_aftertouch", "active_note": True},
                "emit": {"physical": "snare.head", "expressions": ["pressure"], "correlate": "source_channel_note"},
            })
            document["expression_routing"] = [{
                "source": "edrumin", "physical": "snare.head", "expression": "pressure", "correlation": "source_channel_note",
                "targets": {
                    "ddrum4": {"status": "user-confirmed", "event": {"type": "poly_aftertouch", "note_from": "active_rendered_hit"}},
                    "sd3": {"status": "user-confirmed", "event": {"type": "poly_aftertouch", "note_from": "active_rendered_hit"}},
                    "drumgizmo": {"status": "unsupported", "reason": "no measured choke behavior", "event": {"type": "unsupported"}},
                },
            }]
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            simulator = RigSimulator.from_path(project)
            simulator.simulate_pad("edrumin", 38, 100)
            # The active hit was rendered in metalcore. Pressure must retain
            # that result after the current Scene changes to DnB.
            simulator.set_state(scene="dnb")
            result = simulator.simulate_expression("edrumin", "poly_aftertouch", 38, 91)
            report = simulator.run_offline_diagnostic()

        steps = {step.stage: step for step in result.steps}
        self.assertEqual(steps["Arduino DDrum4 renderer"].message,
                         {"type": "poly_aftertouch", "channel": 12, "note": 38, "value": 91, "correlated_raw_note": 38})
        self.assertEqual(steps["SD3 renderer"].message,
                         {"type": "poly_aftertouch", "channel": 10, "note": 38, "value": 91, "correlated_raw_note": 38})
        self.assertEqual(steps["active hit ledger"].message["hit_state"]["scene"], "metalcore")
        self.assertTrue(report.passed, report.render_text())

    def test_simulator_previews_reviewed_cc4_note_p_for_the_next_hihat_hit(self) -> None:
        source = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "metalcore-r15-chain-simulator.yaml"
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "reviewed-hihat.yaml"
            document = yaml.safe_load(source.read_text(encoding="utf-8"))
            document["ddrum4_bank"]["manifest"] = str((source.parent.parent / "banks" / "metalcore-r15-installed.yaml").resolve())
            target = document["expression_routing"][0]["targets"]["ddrum4"]
            target["status"] = "user-confirmed"
            target["event"].update({"input_closed": 127, "input_open": 0})
            target["event"]["articulations"][0]["upper_boundaries"] = [25, 50, 75, 100]
            target["event"]["articulations"][1]["upper_boundaries"] = [31, 63, 95]
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            result = RigSimulator.from_path(project).simulate_expression("edrumin", "cc", 4, 0)

        step = next(item for item in result.steps if item.stage == "Arduino DDrum4 renderer")
        self.assertEqual(step.message["next_hit_note"], 76)
        self.assertEqual(step.message["zone"], 5)
        self.assertFalse(result.renders_audio)

    def test_simulator_previews_reviewed_cc4_drumgizmo_hihat_note_for_the_next_hit(self) -> None:
        source = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "metalcore-r15-chain-simulator.yaml"
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "reviewed-drumgizmo-hihat.yaml"
            document = yaml.safe_load(source.read_text(encoding="utf-8"))
            document["ddrum4_bank"]["manifest"] = str((source.parent.parent / "banks" / "metalcore-r15-installed.yaml").resolve())
            document["expression_routing"][0]["targets"]["sd3"] = {
                "status": "unsupported", "reason": "fixture isolates the DrumGizmo vertical", "event": {"type": "unsupported"},
            }
            target = document["expression_routing"][0]["targets"]["drumgizmo"]
            target.update({
                "status": "user-confirmed",
                "event": {
                    "type": "quantized_note", "input_closed": 127, "input_open": 0,
                    "articulations": [
                        {"physical": "hh.bow", "notes": [64, 100], "upper_boundaries": [63]},
                        {"physical": "hh.edge", "notes": [65, 101], "upper_boundaries": [63]},
                    ],
                },
            })
            project.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            result = RigSimulator.from_path(project).simulate_expression("edrumin", "cc", 4, 0)

        step = next(item for item in result.steps if item.stage == "DrumGizmo renderer")
        self.assertEqual(step.message["next_hit_note"], 100)
        self.assertEqual(step.message["zone"], 2)
        self.assertFalse(result.renders_audio)

    def test_r15_simulator_models_the_declared_module_ownership(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "metalcore-r15-chain-simulator.yaml"
        simulator = RigSimulator.from_path(project)
        self.assertEqual(simulator.project.ddrum4_bank["manifest"], "../banks/metalcore-r15-installed.yaml")
        self.assertEqual(simulator.project.ddrum4_bank_facts.bank_id, "metalcore-r15-installed")
        ddrum = simulator.simulate_pad("ddrum4", 0, 100)
        edrumin = simulator.simulate_pad("edrumin", 3, 100)
        ddti = simulator.simulate_pad("ddti", 16, 100)
        self.assertEqual((ddrum.physical, edrumin.physical, ddti.physical),
                         ("kick.hit", "hh.bow", "crash1.bow"))
        self.assertEqual(
            tuple(next(step.message["note"] for step in result.steps if step.stage == "Arduino DDrum4 renderer")
                  for result in (ddrum, edrumin, ddti)),
            (0, 72, 56),
        )
        self.assertTrue(all(
            next(step.message["channel"] for step in result.steps if step.stage == "Arduino DDrum4 renderer") == 12
            for result in (ddrum, edrumin, ddti)
        ))
        with self.assertRaisesRegex(ValueError, "no declared physical-pad decoder"):
            simulator.simulate_pad("ddti", 0, 100)

    def test_virtual_kit_is_complete_for_installed_r15_topology(self) -> None:
        project = Path(__file__).resolve().parents[3] / "profiles" / "projects" / "metalcore-r15-chain-simulator.yaml"
        rows = build_virtual_kit(RigSimulator.from_path(project))

        self.assertEqual(len(rows), 29)
        self.assertTrue(all(row.complete for row in rows))
        self.assertEqual(rows[0].physical, "kick.hit")
        self.assertEqual((rows[0].physical_instrument, rows[0].physical_zone), ("kick_main", "head"))
        self.assertEqual(rows[0].hardware_summary, "DDrum4 · kick_main / head")
        self.assertEqual(rows[0].raw_note_summary, "DDrum4 N0")
        self.assertEqual(rows[0].raw_notes, {"ddrum4": 0})
        self.assertEqual((rows[0].ddrum4_slot, rows[0].ddrum4_sound_id, rows[0].ddrum4_note_p),
                         (1, "KICK_981", 1))
        self.assertEqual([(layer.index, layer.velocity, layer.sample) for layer in rows[0].ddrum4_layer_candidates],
                         [(1, 84, 1), (2, 124, 2)])
        self.assertIn("Candidates (declared, not selected)", rows[0].ddrum4_content_summary)
        self.assertIn("variation 1/2", rows[0].ddrum4_content_summary)

    def test_installed_r15_matrix_exposes_shared_crash_variations_without_extra_samples(self) -> None:
        manifest = Path(__file__).resolve().parents[3] / "profiles" / "banks" / "metalcore-r15-installed.yaml"
        matrix = load_kit_matrix(manifest)
        crash = next(sound for sound in matrix.sounds if sound.sound_id == "CYMB_982")
        self.assertEqual((matrix.bank_id, matrix.capacity_blocks, matrix.free_blocks),
                         ("metalcore-r15-installed", 8120, 83))
        self.assertEqual(crash.encoded_blocks, 1038)
        self.assertEqual((crash.physical_channel, crash.note_base, crash.note_p), ("CYMBAL_1", 56, 8))
        self.assertEqual(crash.variations, ((1, "Crash"), (2, "Crash High"), (3, "Crash Low")))
        self.assertEqual(crash.layers[2].variation, (2,))
        self.assertEqual((crash.layers[2].pitch, crash.layers[2].source, crash.layers[2].velocity, crash.layers[2].sample),
                         (3, "crash high shared", 68, 1))

    def test_kit_matrix_keeps_unmeasured_memory_unknown_and_marks_missing_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "kit.yaml"
            manifest.write_text("""sounds:
  - sound_id: SNRE_998
    source: snare-main
    status: prepared
    provenance: capture-2026-08-10
    layers:
      - wav: absent.wav
""", encoding="utf-8")
            matrix = load_kit_matrix(manifest)
            sound = matrix.sound(1)
            self.assertEqual(sound.sound_id, "SNRE_998")
            self.assertIsNone(sound.mem_left_delta_blocks)
            self.assertEqual(sound.layers[0].resource_status, "missing")
            self.assertEqual(matrix.sound(2).status, "missing")

    def test_kit_matrix_merges_builder_report_without_inventing_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "kit.json").write_text(json.dumps({"sounds": [{"sound_id": "KICK_997"}]}), encoding="utf-8")
            (root / "build.json").write_text(json.dumps({
                "kind": "ddrum4-flagship-cymbal-build", "sound_id": "KICK_997",
                "instrument": "kick", "encoded_blocks": 124,
                "layers": [{"prepared_file": "KICK_997_s01.wav"}],
            }), encoding="utf-8")
            sound = load_kit_matrix(root / "kit.json", [root / "build.json"]).sound(1)
            self.assertEqual(sound.encoded_blocks, 124)
            self.assertIsNone(sound.mem_left_delta_blocks)
            self.assertEqual(sound.layers[0].resource_status, "missing")

    def test_kit_matrix_rejects_inconsistent_bank_capacity_or_variation_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "kit.yaml"
            manifest.write_text("""bank: {capacity_blocks: 10, used_blocks: 7, free_blocks: 2, midi_channel: 12}
sounds:
  - sound_id: KICK_981
    variations: [{number: 1}, {number: 1}]
""", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "variation numbers"):
                load_kit_matrix(manifest)
            manifest.write_text("""bank: {capacity_blocks: 10, used_blocks: 7, free_blocks: 2, midi_channel: 12}
sounds: []
""", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "capacity_blocks"):
                load_kit_matrix(manifest)

    def test_kit_matrix_keeps_shared_sample_mappings_distinct_from_unique_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "kit.yaml"
            manifest.write_text("""sounds:
  - sound_id: CYMB_981
    layers:
      - {sample: 1, variation: [1]}
      - {sample: 1, variation: [2], pitch: 3}
      - {sample: 2, variation: [1, 2]}
""", encoding="utf-8")
            sound = load_kit_matrix(manifest).sound(1)
            self.assertEqual((sound.layer_count, sound.unique_sample_count), (3, 2))

    def test_default_player_command_is_platform_specific_and_wav_only(self) -> None:
        self.assertEqual(audition_command(Path("take.wav"), "win32"),
                         ("cmd", "/c", "start", "", "take.wav"))
        self.assertEqual(audition_command(Path("take.wav"), "darwin"), ("open", "take.wav"))
        self.assertEqual(audition_command(Path("take.wav"), "linux"), ("xdg-open", "take.wav"))
        with self.assertRaisesRegex(ValueError, "WAV"):
            audition_command(Path("take.mid"), "linux")

    def test_offline_command_construction(self) -> None:
        center = ControlCenter("drum-toolchain")
        command = center.rig_command("compile", Path("profiles/projects/kit.yaml"), output=Path("build/kit"),
                                     replace=True, base_dump=Path("captures/base.syx"))
        self.assertEqual(command, (sys.executable, "-m", "rig_compiler.cli", "compile", str(Path("profiles/projects/kit.yaml")), "--output",
                                   str(Path("build/kit")), "--replace", "--base-dump", str(Path("captures/base.syx"))))

    def test_custom_rig_compiler_executable_remains_supported(self) -> None:
        center = ControlCenter("custom-drum-toolchain")
        self.assertEqual(
            center.rig_command("validate", Path("project.yaml")),
            ("custom-drum-toolchain", "validate", "project.yaml"),
        )

    def test_ddti_commands_are_offline_export_diff_or_stage_only(self) -> None:
        center = ControlCenter()
        prefix = (sys.executable, "-m", "ddti.cli")
        self.assertEqual(center.ddti_command("export-config", Path("base.syx"), output=Path("preset.yaml")),
                         (*prefix, "export-config", "base.syx", "preset.yaml"))
        self.assertEqual(center.ddti_command("apply-config", Path("base.syx"), preset=Path("preset.yaml"), output=Path("staged.syx")),
                         (*prefix, "apply-config", "base.syx", "preset.yaml", "staged.syx"))
        with self.assertRaisesRegex(ValueError, "unsupported"):
            center.ddti_command("write-config", Path("base.syx"))

    def test_dry_run_never_invokes_runner_or_launcher(self) -> None:
        def forbidden(*args: object, **kwargs: object) -> object:
            raise AssertionError("a dry run must not start a process")
        center = ControlCenter(runner=forbidden, launcher=forbidden)
        result = center.run_rig("validate", Path("project.yaml"), dry_run=True)
        self.assertTrue(result.dry_run)
        self.assertIsNone(result.returncode)
        launch = center.launch("converter", converter=Path("converter.exe"), runtime_profile=Path("runtime-profile.yaml"), dry_run=True)
        self.assertEqual(launch.command, ("converter.exe",))

    def test_run_collects_logs_without_hardware(self) -> None:
        def runner(command: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            self.assertEqual(tuple(command), (sys.executable, "-m", "rig_compiler.cli", "report", "project.yaml"))
            self.assertTrue(kwargs["capture_output"])
            return subprocess.CompletedProcess(command, 0, "report\n", "")
        result = ControlCenter(runner=runner).run_rig("report", Path("project.yaml"))
        self.assertEqual(result.text, "report\n")

    def test_offline_runners_hide_windows_console_without_using_shell(self) -> None:
        calls: list[dict[str, object]] = []
        project = Path("project.yaml")
        base_dump = Path("base.syx")
        preset = Path("next.syx")

        def runner(command: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(dict(kwargs))
            return subprocess.CompletedProcess(command, 0, "ok\n", "")

        with patch("control_center.service.os.name", "nt"):
            control_center = ControlCenter(runner=runner)
            control_center.run_rig("report", project)
            control_center.run_ddti("diff", base_dump, preset=preset)

        self.assertEqual(len(calls), 2)
        expected_flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        for kwargs in calls:
            self.assertIs(kwargs["capture_output"], True)
            self.assertIs(kwargs["text"], True)
            self.assertIs(kwargs["check"], False)
            self.assertIs(kwargs["shell"], False)
            self.assertEqual(kwargs["creationflags"], expected_flag)

    def test_launchers_are_explicit(self) -> None:
        center = ControlCenter()
        with self.assertRaisesRegex(ValueError, "explicit executable"):
            center.launch_command("ddrum4ui")
        self.assertEqual(center.launch_command("ddti"), (sys.executable, "-m", "ddti.gui"))

    def test_control_center_lists_and_stops_only_processes_it_started(self) -> None:
        class Process:
            def __init__(self) -> None:
                self.running = True
                self.terminated = False
            def poll(self) -> None:
                return None if self.running else 0
            def terminate(self) -> None:
                self.terminated = True
                self.running = False
        process = Process()
        center = ControlCenter(launcher=lambda *args, **kwargs: process)
        center.launch("external", external=Path("sd3-host.exe"))
        self.assertEqual(center.launched_processes(), (("external:sd3-host.exe:None", True),))
        self.assertEqual(center.stop_launched_processes(), ("external:sd3-host.exe:None",))
        self.assertTrue(process.terminated)

    def test_converter_launch_sets_profile_environment_and_blocks_duplicate(self) -> None:
        class Process:
            def poll(self) -> None:
                return None
        calls: list[tuple[object, object]] = []
        def launcher(command: object, **kwargs: object) -> Process:
            calls.append((command, kwargs.get("env")))
            return Process()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        center = ControlCenter(launcher=launcher, lock_directory=Path(temporary.name))
        center.launch("converter", converter=Path("converter.exe"), runtime_profile=Path("build/runtime-profile.yaml"))
        self.assertEqual(calls[0][1]["DDRUM4_RUNTIME_PROFILE"], str(Path("build/runtime-profile.yaml")))
        self.assertEqual(calls[0][1]["DDRUM4_RENDERER_TARGET"], "sd3")
        with self.assertRaisesRegex(RuntimeError, "already running"):
            center.launch("converter", converter=Path("converter.exe"), runtime_profile=Path("build/runtime-profile.yaml"))

    def test_stale_cross_process_lock_is_cleaned_before_launch(self) -> None:
        class Process:
            pid = 424242
            def poll(self) -> None:
                return None
        with tempfile.TemporaryDirectory() as temporary:
            center = ControlCenter(launcher=lambda *args, **kwargs: Process(), lock_directory=Path(temporary))
            converter, profile = Path("converter.exe"), Path("build/runtime-profile.yaml")
            lock = center.converter_lock_path(converter, profile)
            lock.parent.mkdir(parents=True)
            lock.write_text('{"pid": -1}', encoding="utf-8")
            center.launch("converter", converter=converter, runtime_profile=profile)
            self.assertEqual(lock.read_text(encoding="utf-8"), '{"pid": 424242}')

    def test_live_cross_process_lock_blocks_a_second_controller(self) -> None:
        class Process:
            def poll(self) -> None:
                return None
        with tempfile.TemporaryDirectory() as temporary:
            converter, profile = Path("converter.exe"), Path("build/runtime-profile.yaml")
            first = ControlCenter(launcher=lambda *args, **kwargs: Process(), lock_directory=Path(temporary))
            first.launch("converter", converter=converter, runtime_profile=profile)
            second = ControlCenter(launcher=lambda *args, **kwargs: Process(), lock_directory=Path(temporary))
            with self.assertRaisesRegex(RuntimeError, "another Control Center"):
                second.launch("converter", converter=converter, runtime_profile=profile)

    def test_converter_requires_runtime_profile(self) -> None:
        with self.assertRaisesRegex(ValueError, "runtime profile"):
            ControlCenter().launch_command("converter", converter=Path("converter.exe"))

    def test_converter_rejects_unknown_renderer_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "renderer target"):
            ControlCenter().launch_command("converter", converter=Path("converter.exe"),
                                           runtime_profile=Path("runtime-profile.yaml"), renderer_target="unknown")
