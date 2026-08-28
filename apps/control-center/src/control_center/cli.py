"""Command-line fallback for the optional PySide Control Center."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys

from .service import CommandResult, ControlCenter
from .ddrum4_matrix import format_matrix, load_kit_matrix
from .simulator import RigSimulator, SimulationError
from .live_measurement import LiveMeasurementCampaign
from .campaign import Sd3CaptureCampaign, capture_rows_from_megakit_plan


def _print(result: CommandResult) -> int:
    print(shlex.join(result.command))
    if result.dry_run:
        return 0
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode or 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline rig-project Control Center; never opens MIDI ports.")
    parser.add_argument("--toolchain", default="drum-toolchain")
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("validate", "report", "compile"):
        command = commands.add_parser(name)
        command.add_argument("project", type=Path)
        command.add_argument("--dry-run", action="store_true")
        if name == "compile":
            command.add_argument("--output", required=True, type=Path)
            command.add_argument("--replace", action="store_true")
            command.add_argument("--base-dump", type=Path)
    ddti = commands.add_parser("launch-ddti")
    ddti.add_argument("--dry-run", action="store_true")
    ui = commands.add_parser("launch-ddrum4ui")
    ui.add_argument("--ddrum4ui", required=True, type=Path)
    ui.add_argument("--dry-run", action="store_true")
    converter = commands.add_parser("launch-converter")
    converter.add_argument("--converter", required=True, type=Path)
    converter.add_argument("--runtime-profile", required=True, type=Path,
                           help="compiled runtime-profile.yaml selected for this converter launch")
    converter.add_argument("--renderer", choices=("sd3", "drumgizmo"), default="sd3",
                           help="logical renderer emitted by the converter")
    converter.add_argument("--argument", dest="arguments", action="append", default=[],
                           help="one explicit converter argument; repeat as needed")
    converter.add_argument("--dry-run", action="store_true")
    for name in ("ddti-export-config", "ddti-apply-config", "ddti-diff"):
        command = commands.add_parser(name, help="offline DDTi decode/staging only; never sends MIDI")
        command.add_argument("dump", type=Path)
        command.add_argument("--dry-run", action="store_true")
        if name == "ddti-export-config":
            command.add_argument("--output", required=True, type=Path)
            command.add_argument("--name")
        else:
            command.add_argument("--preset", required=True, type=Path,
                                 help="configuration preset for apply, or second dump for diff")
            if name == "ddti-apply-config":
                command.add_argument("--output", required=True, type=Path)
    matrix = commands.add_parser("kit-matrix", help="show declared offline DDrum4 Sound/layer matrix")
    matrix.add_argument("manifest", type=Path)
    matrix.add_argument("--report", dest="reports", action="append", default=[], type=Path,
                        help="ddrum4-bank-builder report; repeat as needed")
    matrix.add_argument("--json", action="store_true", help="reserved for a future stable export")
    audition = commands.add_parser("audition-wav", help="explicitly open one local WAV in the OS default player")
    audition.add_argument("wav", type=Path)
    audition.add_argument("--dry-run", action="store_true")
    simulate = commands.add_parser("simulate", help="offline trace: pad event through DDrum4, SD3, and DrumGizmo")
    simulate.add_argument("project", type=Path)
    simulate.add_argument("--source", required=True, help="declared source module, for example edrumin, ddti, or ddrum4")
    simulate.add_argument("--note", required=True, type=int, help="raw Note On emitted by the selected source")
    simulate.add_argument("--velocity", type=int, default=100)
    simulate.add_argument("--scene", help="optional logical scene override")
    simulate.add_argument("--state", action="append", default=[], metavar="NAME=VALUE",
                          help="optional virtual-palette override; repeat as needed")
    simulate.add_argument("--json", action="store_true", help="print the complete machine-readable trace")
    expression = commands.add_parser("simulate-expression", help="offline trace: declared CC or poly-aftertouch through the logical chain")
    expression.add_argument("project", type=Path)
    expression.add_argument("--source", required=True)
    expression.add_argument("--type", dest="message_type", choices=("cc", "poly_aftertouch"), required=True)
    expression.add_argument("--data1", required=True, type=int, help="CC address or aftertouch note")
    expression.add_argument("--value", type=int, default=64)
    expression.add_argument("--scene")
    expression.add_argument("--state", action="append", default=[], metavar="NAME=VALUE")
    expression.add_argument("--json", action="store_true", help="print the complete machine-readable trace")
    control = commands.add_parser("simulate-control", help="offline trace: Scene/VP command through Arduino DDrum4 reconciliation")
    control.add_argument("project", type=Path)
    control.add_argument("--source", choices=("pc", "external", "simulator"), default="pc")
    control.add_argument("--channel", type=int, default=15)
    control.add_argument("--type", dest="message_type", choices=("program_change", "cc"), required=True)
    control.add_argument("--data1", required=True, type=int, help="Program number or CC address")
    control.add_argument("--value", type=int, default=0, help="CC value; ignored for Program Change")
    control.add_argument("--json", action="store_true", help="print the complete machine-readable trace")
    diagnose = commands.add_parser("diagnose", help="offline no-pad coverage test for every declared route and control")
    diagnose.add_argument("project", type=Path)
    diagnose.add_argument("--json", action="store_true", help="print the machine-readable coverage report")
    measurement = commands.add_parser("measurement-plan", help="write a no-I/O campaign for a later live promotion")
    measurement.add_argument("project", type=Path)
    measurement.add_argument("--output", required=True, type=Path)
    review = commands.add_parser("measurement-review", help="review isolated trace files without opening MIDI")
    review.add_argument("campaign", type=Path)
    review.add_argument("--json", action="store_true")
    promote = commands.add_parser("promote-live", help="create a new live YAML from a complete measurement campaign")
    promote.add_argument("campaign", type=Path)
    promote.add_argument("--output", required=True, type=Path)
    promote.add_argument("--endpoint", action="append", required=True, metavar="SOURCE=PORT")
    promote.add_argument("--control-endpoint", required=True, metavar="PORT")
    campaign = commands.add_parser("create-sd3-campaign", help="create a complete no-I/O SD3 capture campaign from a MegaKit plan")
    campaign.add_argument("plan", type=Path)
    campaign.add_argument("--output", required=True, type=Path)
    campaign.add_argument("--id", required=True)
    campaign.add_argument("--preset", required=True)
    campaign.add_argument("--midi-output", required=True)
    campaign.add_argument("--audio-input", required=True)
    campaign.add_argument("--channels", default="left,right")
    campaign.add_argument("--sample-rate", type=int, default=44100)
    campaign.add_argument("--tail-ms", type=int, default=5000)
    args = parser.parse_args(argv)
    center = ControlCenter(args.toolchain)
    if args.action == "kit-matrix":
        if args.json:
            parser.error("kit-matrix --json is not implemented; use the human-readable read-only matrix")
        print(format_matrix(load_kit_matrix(args.manifest, args.reports)))
        return 0
    if args.action == "audition-wav":
        return _print(center.audition_wav(args.wav, dry_run=args.dry_run))
    if args.action == "simulate":
        try:
            overrides: dict[str, int] = {}
            for item in args.state:
                name, separator, value = item.partition("=")
                if not separator or not name:
                    raise SimulationError("--state must use NAME=VALUE")
                try:
                    overrides[name] = int(value)
                except ValueError as error:
                    raise SimulationError(f"--state {name!r} must have an integer value") from error
            simulator = RigSimulator.from_path(args.project)
            simulator.set_state(scene=args.scene, values=overrides)
            result = simulator.simulate_pad(args.source, args.note, args.velocity)
        except (OSError, ValueError, SimulationError) as error:
            parser.error(str(error))
        print(json.dumps(result.to_document(), indent=2, ensure_ascii=False) if args.json else result.render_text())
        return 0
    if args.action == "simulate-control":
        try:
            simulator = RigSimulator.from_path(args.project)
            result = simulator.simulate_logical_control(
                args.source, args.channel, args.message_type, args.data1, args.value,
            )
        except (OSError, ValueError, SimulationError) as error:
            parser.error(str(error))
        print(json.dumps(result.to_document(), indent=2, ensure_ascii=False) if args.json else result.render_text())
        return 0
    if args.action == "simulate-expression":
        try:
            overrides: dict[str, int] = {}
            for item in args.state:
                name, separator, value = item.partition("=")
                if not separator or not name:
                    raise SimulationError("--state must use NAME=VALUE")
                overrides[name] = int(value)
            simulator = RigSimulator.from_path(args.project)
            simulator.set_state(scene=args.scene, values=overrides)
            result = simulator.simulate_expression(args.source, args.message_type, args.data1, args.value)
        except (OSError, ValueError, SimulationError) as error:
            parser.error(str(error))
        print(json.dumps(result.to_document(), indent=2, ensure_ascii=True) if args.json else result.render_text())
        return 0
    if args.action == "diagnose":
        try:
            report = RigSimulator.from_path(args.project).run_offline_diagnostic()
        except (OSError, ValueError, SimulationError) as error:
            parser.error(str(error))
        print(json.dumps(report.to_document(), indent=2, ensure_ascii=True) if args.json else report.render_text())
        return 0 if report.passed else 1
    if args.action == "measurement-plan":
        try:
            plan, guide = LiveMeasurementCampaign.from_path(args.project).write_new(args.output)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        print(json.dumps({"plan": str(plan), "guide": str(guide), "hardware_io": "disabled"}, indent=2))
        return 0
    if args.action == "create-sd3-campaign":
        try:
            channels = tuple(value.strip() for value in args.channels.split(",") if value.strip())
            capture_campaign = Sd3CaptureCampaign(
                identifier=args.id,
                sd3_preset=args.preset,
                midi_output=args.midi_output,
                audio_input=args.audio_input,
                channels=channels,
                rows=capture_rows_from_megakit_plan(args.plan),
                sample_rate=args.sample_rate,
                tail_ms=args.tail_ms,
            )
            capture_campaign.write_new(args.output)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        print(json.dumps({
            "campaign": str(args.output / "campaign.json"),
            "session": str(args.output / "capture-session.json"),
            "expected_take_count": capture_campaign.total_takes,
            "hardware_io": "disabled",
        }, indent=2))
        return 0
    if args.action == "measurement-review":
        try:
            result = LiveMeasurementCampaign.read(args.campaign).review_traces(args.campaign)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        print(json.dumps(result, indent=2, ensure_ascii=True) if args.json else result["status"])
        return 0 if result["status"] == "capture-complete-not-live" else 1
    if args.action == "promote-live":
        try:
            endpoints: dict[str, str] = {}
            for item in args.endpoint:
                source, separator, endpoint = item.partition("=")
                if not separator or not source or not endpoint or source in endpoints:
                    raise ValueError("--endpoint must use unique SOURCE=PORT values")
                endpoints[source] = endpoint
            campaign = LiveMeasurementCampaign.read(args.campaign)
            output = campaign.promote_live(args.campaign, args.output, endpoints=endpoints,
                                           control_endpoint=args.control_endpoint)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        print(json.dumps({"project": str(output), "hardware_io": "disabled", "next": "compile and satisfy the firmware flash gate"}, indent=2))
        return 0
    if args.action in {"validate", "report", "compile"}:
        return _print(center.run_rig(args.action, args.project, output=getattr(args, "output", None),
                                     replace=getattr(args, "replace", False), base_dump=getattr(args, "base_dump", None),
                                     dry_run=args.dry_run))
    if args.action == "launch-ddti":
        return _print(center.launch("ddti", dry_run=args.dry_run))
    if args.action.startswith("ddti-"):
        return _print(center.run_ddti(args.action.removeprefix("ddti-"), args.dump,
                                      preset=getattr(args, "preset", None), output=getattr(args, "output", None),
                                      name=getattr(args, "name", None), dry_run=args.dry_run))
    if args.action == "launch-ddrum4ui":
        return _print(center.launch("ddrum4ui", ddrum4ui=args.ddrum4ui, dry_run=args.dry_run))
    return _print(center.launch("converter", converter=args.converter, runtime_profile=args.runtime_profile,
                                converter_arguments=args.arguments, renderer_target=args.renderer,
                                dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
