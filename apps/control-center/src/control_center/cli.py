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
from .live_measurement import HihatCalibration, LiveMeasurementCampaign, PressureConfirmation
from .campaign import (Sd3CaptureCampaign, capture_rows_from_megakit_plan,
                       drumgizmo_composite_filenames, fingerprint_sd3_preset)


def _print(result: CommandResult) -> int:
    print(shlex.join(result.command))
    if result.dry_run:
        return 0
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode or 0


def _hihat_calibration_from_args(args: argparse.Namespace) -> HihatCalibration | None:
    supplied = (args.hihat_input_closed is not None or args.hihat_input_open is not None
                or bool(args.hihat_boundaries))
    if not supplied:
        return None
    if args.hihat_input_closed is None or args.hihat_input_open is None or not args.hihat_boundaries:
        raise ValueError("hi-hat calibration requires both endpoints and every --hihat-boundaries entry")
    boundaries: dict[str, dict[str, tuple[int, ...]]] = {}
    for item in args.hihat_boundaries:
        address, separator, values_text = item.partition("=")
        target, target_separator, physical = address.partition(":")
        if not separator or not target_separator or not target or not physical or not values_text:
            raise ValueError("--hihat-boundaries must use TARGET:PHYSICAL=B1,B2,...")
        try:
            values = tuple(int(value.strip()) for value in values_text.split(",") if value.strip())
        except ValueError as error:
            raise ValueError("--hihat-boundaries values must be integers") from error
        target_boundaries = boundaries.setdefault(target, {})
        if physical in target_boundaries:
            raise ValueError(f"duplicate hi-hat boundaries for {target}:{physical}")
        target_boundaries[physical] = values
    return HihatCalibration(args.hihat_input_closed, args.hihat_input_open, boundaries)


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
    for name in ("ddti-export-config", "ddti-apply-config", "ddti-apply-role-preset", "ddti-diff"):
        command = commands.add_parser(name, help="offline DDTi decode/staging only; never sends MIDI")
        command.add_argument("dump", type=Path)
        command.add_argument("--dry-run", action="store_true")
        if name == "ddti-export-config":
            command.add_argument("--output", required=True, type=Path)
            command.add_argument("--name")
        else:
            command.add_argument("--preset", required=True, type=Path,
                                 help="configuration preset for apply, or second dump for diff")
            if name in {"ddti-apply-config", "ddti-apply-role-preset"}:
                command.add_argument("--output", required=True, type=Path)
            if name == "ddti-apply-role-preset":
                command.add_argument("--layout", required=True, type=Path,
                                     help="explicit DDTi Input/Tip/Ring layout")
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
    diagnose.add_argument("--output", type=Path,
                          help="atomically write the machine-readable report without changing hardware")
    measurement = commands.add_parser("measurement-plan", help="write a no-I/O campaign for a later live promotion")
    measurement.add_argument("project", type=Path)
    measurement.add_argument("--output", required=True, type=Path)
    review = commands.add_parser("measurement-review", help="review isolated trace files without opening MIDI")
    review.add_argument("campaign", type=Path)
    review.add_argument("--json", action="store_true")
    native_sequence = commands.add_parser(
        "measurement-import-native-sequence",
        help="atomically split one receive-only Scene/Palette sequence into isolated campaign traces",
    )
    native_sequence.add_argument("campaign", type=Path)
    native_sequence.add_argument("trace", type=Path)
    promote = commands.add_parser("promote-live", help="create a new live YAML from a complete measurement campaign")
    promote.add_argument("campaign", type=Path)
    promote.add_argument("--output", required=True, type=Path)
    promote.add_argument("--endpoint", action="append", required=True, metavar="SOURCE=PORT")
    promote.add_argument("--transport", action="append", default=[], metavar="SOURCE=din|usb",
                         help="explicit physical path for each source; use din for the shared Arduino/UMC THRU")
    promote.add_argument("--control-endpoint", required=True, metavar="PORT")
    promote.add_argument("--hihat-input-closed", type=int, metavar="0..127",
                         help="closed endpoint observed in the isolated CC4 trace")
    promote.add_argument("--hihat-input-open", type=int, metavar="0..127",
                         help="open endpoint observed in the isolated CC4 trace")
    promote.add_argument("--hihat-boundaries", action="append", default=[],
                         metavar="TARGET:PHYSICAL=B1,B2,...",
                         help="explicit ascending normalized zone boundaries; repeat for every planned articulation")
    promote.add_argument("--confirm-pressure-target", action="append", default=[],
                         choices=("ddrum4", "sd3"),
                         help="explicitly accept active-hit aftertouch for this renderer; raw traces alone do not prove it")
    configured = commands.add_parser(
        "promote-configured",
        help="create a live YAML from prescribed module maps and verified configuration receipts, without pads",
    )
    configured.add_argument("project", type=Path)
    configured.add_argument("--output", required=True, type=Path)
    configured.add_argument("--source-contract", required=True, type=Path)
    configured.add_argument("--ddti-receipt", required=True, type=Path)
    configured.add_argument("--edrumin-receipt", required=True, type=Path)
    configured.add_argument("--endpoint", action="append", required=True, metavar="SOURCE=PORT")
    configured.add_argument("--transport", action="append", required=True, metavar="SOURCE=din|usb")
    configured.add_argument("--control-endpoint", required=True, metavar="PORT")
    configured.add_argument("--hihat-input-closed", type=int, required=True, metavar="0..127")
    configured.add_argument("--hihat-input-open", type=int, required=True, metavar="0..127")
    configured.add_argument("--hihat-boundaries", action="append", required=True,
                            metavar="TARGET:PHYSICAL=B1,B2,...")
    configured.add_argument("--confirm-pressure-target", action="append", required=True,
                            choices=("ddrum4", "sd3"))
    campaign = commands.add_parser("create-sd3-campaign", help="create a complete no-I/O SD3 capture campaign from a MegaKit plan")
    campaign.add_argument("plan", type=Path)
    campaign.add_argument("--output", required=True, type=Path)
    campaign.add_argument("--id", required=True)
    campaign.add_argument("--preset", required=True)
    campaign.add_argument("--preset-file", required=True, type=Path)
    campaign.add_argument("--midi-map", default="Kit_Metalcore_MidiMapping_Capture_V1")
    campaign.add_argument("--midi-output", required=True)
    campaign.add_argument("--audio-input", required=True)
    campaign.add_argument("--channels", default="left,right")
    campaign.add_argument("--sample-rate", type=int, default=48000)
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
        if args.output is not None:
            document = json.dumps(report.to_document(), indent=2, ensure_ascii=True) + "\n"
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_suffix(args.output.suffix + ".tmp")
            temporary.write_text(document, encoding="utf-8", newline="\n")
            temporary.replace(args.output)
        if args.output is not None and not args.json:
            print(f"wrote offline diagnostic {args.output}: {report.passed_count}/{len(report.cases)} passed")
        else:
            print(json.dumps(report.to_document(), indent=2, ensure_ascii=True) if args.json else report.render_text())
        return 0 if report.passed else 1
    if args.action == "measurement-plan":
        try:
            plan, guide = LiveMeasurementCampaign.from_path(args.project).write_new(args.output)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        print(json.dumps({"plan": str(plan), "guide": str(guide), "hardware_io": "disabled"}, indent=2))
        return 0
    if args.action == "measurement-import-native-sequence":
        try:
            campaign = LiveMeasurementCampaign.read(args.campaign)
            outputs = campaign.import_native_control_sequence(args.campaign, args.trace)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        print(json.dumps({
            "status": "imported", "hardware_io": "disabled", "trace_count": len(outputs),
            "traces": [str(path) for path in outputs],
        }, indent=2))
        return 0
    if args.action == "create-sd3-campaign":
        try:
            channels = tuple(value.strip() for value in args.channels.split(",") if value.strip())
            preset_file, preset_sha256 = fingerprint_sd3_preset(args.preset_file)
            capture_campaign = Sd3CaptureCampaign(
                identifier=args.id,
                sd3_preset=args.preset,
                sd3_midi_map=args.midi_map,
                midi_output=args.midi_output,
                audio_input=args.audio_input,
                channels=channels,
                rows=capture_rows_from_megakit_plan(args.plan),
                megakit_plan_file=str(args.plan.expanduser().resolve()),
                sd3_preset_file=preset_file,
                sd3_preset_sha256=preset_sha256,
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
            "expected_composite_take_count": len(drumgizmo_composite_filenames(args.plan)),
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
            transports: dict[str, str] | None = None
            if args.transport:
                transports = {}
                for item in args.transport:
                    source, separator, transport = item.partition("=")
                    if not separator or not source or transport not in {"din", "usb"} or source in transports:
                        raise ValueError("--transport must use unique SOURCE=din|usb values")
                    transports[source] = transport
            campaign = LiveMeasurementCampaign.read(args.campaign)
            hihat_calibration = _hihat_calibration_from_args(args)
            pressure_confirmation = (PressureConfirmation(frozenset(args.confirm_pressure_target))
                                     if args.confirm_pressure_target else None)
            output = campaign.promote_live(args.campaign, args.output, endpoints=endpoints,
                                           control_endpoint=args.control_endpoint, transports=transports,
                                           hihat_calibration=hihat_calibration,
                                           pressure_confirmation=pressure_confirmation)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        print(json.dumps({"project": str(output), "hardware_io": "disabled", "next": "compile and satisfy the firmware flash gate"}, indent=2))
        return 0
    if args.action == "promote-configured":
        try:
            endpoints: dict[str, str] = {}
            for item in args.endpoint:
                source, separator, endpoint = item.partition("=")
                if not separator or not source or not endpoint or source in endpoints:
                    raise ValueError("--endpoint must use unique SOURCE=PORT values")
                endpoints[source] = endpoint
            transports: dict[str, str] = {}
            for item in args.transport:
                source, separator, transport = item.partition("=")
                if not separator or not source or transport not in {"din", "usb"} or source in transports:
                    raise ValueError("--transport must use unique SOURCE=din|usb values")
                transports[source] = transport
            calibration = _hihat_calibration_from_args(args)
            if calibration is None:
                raise ValueError("configured promotion requires the complete hi-hat contract")
            pressure = PressureConfirmation(frozenset(args.confirm_pressure_target))
            campaign = LiveMeasurementCampaign.from_path(args.project)
            output = campaign.promote_configured(
                args.output, endpoints=endpoints, control_endpoint=args.control_endpoint,
                transports=transports, source_contract=args.source_contract,
                ddti_receipt=args.ddti_receipt, edrumin_receipt=args.edrumin_receipt,
                hihat_calibration=calibration, pressure_confirmation=pressure,
            )
        except (OSError, ValueError) as error:
            parser.error(str(error))
        print(json.dumps({"project": str(output), "hardware_io": "disabled",
                          "next": "compile, review receipts, then use the gated flash script"}, indent=2))
        return 0
    if args.action in {"validate", "report", "compile"}:
        return _print(center.run_rig(args.action, args.project, output=getattr(args, "output", None),
                                     replace=getattr(args, "replace", False), base_dump=getattr(args, "base_dump", None),
                                     dry_run=args.dry_run))
    if args.action == "launch-ddti":
        return _print(center.launch("ddti", dry_run=args.dry_run))
    if args.action.startswith("ddti-"):
        return _print(center.run_ddti(args.action.removeprefix("ddti-"), args.dump,
                                      preset=getattr(args, "preset", None), layout=getattr(args, "layout", None),
                                      output=getattr(args, "output", None),
                                      name=getattr(args, "name", None), dry_run=args.dry_run))
    if args.action == "launch-ddrum4ui":
        return _print(center.launch("ddrum4ui", ddrum4ui=args.ddrum4ui, dry_run=args.dry_run))
    return _print(center.launch("converter", converter=args.converter, runtime_profile=args.runtime_profile,
                                converter_arguments=args.arguments, renderer_target=args.renderer,
                                dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
