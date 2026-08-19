"""Non-destructive ddrum4 backend inspection commands."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

from .ddrum4edit_backend import Ddrum4EditBackend
from .ddrum4ui import discover
from .backup import inspect_settings_backup, validate_settings_backup
from .transport import receive_midi_dump
from .plan import compare_plan, render_comparison
from .b0 import B0Fixture, verify_b0_build, write_fixture_manifest
from .compiler import compile_nested_file, write_compilation
from .actual_bank import report_actual_bank
from .hardware import transfer_one_sound
from .render_compare import compare_renders


def _backend(value: str | None) -> Ddrum4EditBackend:
    executable = Path(value) if value else discover().ddrum4edit
    if executable is None:
        raise RuntimeError("ddrum4edit was not found; pass --ddrum4edit PATH")
    return Ddrum4EditBackend(executable)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ddrum4-bank", description="Inspect ddrum4edit without sending data to a module.")
    parser.add_argument("--ddrum4edit", help="explicit ddrum4edit executable path")
    subparsers = parser.add_subparsers(dest="command", required=True)
    discover_parser = subparsers.add_parser("discover", help="locate ddrum4UI and ddrum4edit")
    discover_parser.add_argument("--root", type=Path, help="optional directory to search first")
    for command, help_text in (("inspect", "print ddrum4edit metadata for a sound"), ("blocks", "print encoded block count for a sound")):
        subparser = subparsers.add_parser(command, help=help_text)
        subparser.add_argument("sound", type=Path)
    backup = subparsers.add_parser("receive-settings-backup", help="listen for a dump manually initiated from the module/UI")
    backup.add_argument("--input", required=True, help="unique MIDI input name")
    backup.add_argument("--output", required=True, type=Path)
    backup.add_argument("--seconds", type=float, default=30.0)
    backup.add_argument("--confirm-listening", action="store_true", help="required: open the selected MIDI input and wait for a dump")
    record_sysex = subparsers.add_parser("record-sysex", help="record a manually initiated SysEx stream without interpreting it as module settings")
    record_sysex.add_argument("--input", required=True, help="unique MIDI input name")
    record_sysex.add_argument("--output", required=True, type=Path)
    record_sysex.add_argument("--seconds", type=float, default=30.0)
    record_sysex.add_argument("--confirm-listening", action="store_true", help="required: open the selected MIDI input and wait for a manually initiated stream")
    inspect_backup = subparsers.add_parser("inspect-settings-backup", help="print read-only structural facts for a saved settings dump")
    inspect_backup.add_argument("backup", type=Path)
    fixture = subparsers.add_parser("create-b0-fixture", help="write a non-overwriting synthetic WAV for the offline B0 transfer bench")
    fixture.add_argument("--wav", required=True, type=Path)
    fixture.add_argument("--manifest", required=True, type=Path)
    verify_b0 = subparsers.add_parser("verify-b0-build", help="inspect and record a local B0 sound build; never transfers MIDI")
    verify_b0.add_argument("--fixture-manifest", required=True, type=Path)
    verify_b0.add_argument("--sound", required=True, type=Path)
    verify_b0.add_argument("--output", required=True, type=Path)
    nested = subparsers.add_parser("compile-nested", help="compile declared nested layouts into routing-contract JSON and coverage report")
    nested.add_argument("plan", type=Path)
    nested.add_argument("--routing-contract", required=True, type=Path)
    nested.add_argument("--report", required=True, type=Path)
    nested.add_argument("--firmware-header", type=Path, help="optional generated Arduino mapping header; refuses to overwrite")
    snare = subparsers.add_parser("select-snare", help="select evenly distributed captured snare layers for the B1 source plan")
    snare.add_argument("--library", required=True, type=Path)
    snare.add_argument("--output", required=True, type=Path)
    snare.add_argument("--instrument", default="snare_main")
    snare.add_argument("--head-layers", default=7, type=int)
    snare.add_argument("--rim-layers", default=2, type=int)
    cymbal = subparsers.add_parser("build-flagship-cymbal", help="prepare and locally build an auditable flagship cymbal; never sends MIDI")
    cymbal.add_argument("--library", required=True, type=Path)
    cymbal.add_argument("--raw-directory", required=True, type=Path)
    cymbal.add_argument("--output-directory", required=True, type=Path)
    cymbal.add_argument("--sound-id", required=True)
    cymbal.add_argument("--instrument", required=True)
    cymbal.add_argument("--template", required=True, type=Path)
    cymbal.add_argument("--quality-profile", required=True, type=Path)
    cymbal.add_argument("--quality-name", default="ddrum4_cymbal_flagship")
    cymbal.add_argument("--velocities", type=int, nargs="+", default=[24, 40, 56, 72, 88, 110, 127])
    cymbal.add_argument(
        "--layer-durations", type=float, nargs="+",
        help="one maximum duration per velocity; preserves long hard tails without bloating soft layers",
    )
    cymbal.add_argument("--max-duration-seconds", type=float)
    cymbal.add_argument("--trim-threshold-db", type=float)
    cymbal.add_argument("--report", required=True, type=Path)
    positional_snare = subparsers.add_parser(
        "build-positional-snare",
        help="prepare and locally build a five-velocity by two-position snare; never sends MIDI",
    )
    positional_snare.add_argument("--library", required=True, type=Path)
    positional_snare.add_argument("--raw-directory", required=True, type=Path)
    positional_snare.add_argument("--output-directory", required=True, type=Path)
    positional_snare.add_argument("--sound-id", required=True)
    positional_snare.add_argument("--instrument", default="snare_main")
    positional_snare.add_argument(
        "--positions", nargs=2, default=["head_position_000", "head_position_127"]
    )
    positional_snare.add_argument(
        "--velocities", nargs=5, type=int, default=[24, 48, 72, 96, 120]
    )
    positional_snare.add_argument("--template", required=True, type=Path)
    positional_snare.add_argument("--quality-profile", required=True, type=Path)
    positional_snare.add_argument("--quality-name", default="ddrum4_snare_flagship")
    positional_snare.add_argument("--report", required=True, type=Path)
    hihat = subparsers.add_parser(
        "build-flagship-hihat",
        help="prepare and locally build the audited eight-position flagship hi-hat; never sends MIDI",
    )
    hihat.add_argument("--library", required=True, type=Path)
    hihat.add_argument("--raw-directory", required=True, type=Path)
    hihat.add_argument("--output-directory", required=True, type=Path)
    hihat.add_argument("--sound-id", required=True)
    hihat.add_argument("--instrument", default="hi_hat")
    hihat.add_argument("--template", required=True, type=Path)
    hihat.add_argument("--quality-profile", required=True, type=Path)
    hihat.add_argument("--quality-name", default="ddrum4_hihat_flagship")
    hihat.add_argument(
        "--layout", choices=("bow", "edge"), default="bow",
        help="bow/pedal primary sound or edge/open-4 nested companion",
    )
    hihat.add_argument("--report", required=True, type=Path)
    allocation = subparsers.add_parser("compare-plan", help="compare offline quality-first and compact soundbank allocation plans")
    allocation.add_argument("plan", type=Path)
    allocation.add_argument("--output", type=Path, help="optional Markdown report path")
    actual = subparsers.add_parser("report-encoded-bank", help="inspect encoded sounds and report their real cumulative block cost")
    actual.add_argument("--capacity-blocks", required=True, type=int, help="live free-memory value read from the module before this batch")
    actual.add_argument("--output", required=True, type=Path, help="non-overwriting JSON report path")
    actual.add_argument("sounds", nargs="+", type=Path)
    transfer = subparsers.add_parser("transfer-sound", help="send exactly one built sound to hardware after an explicit confirmation")
    transfer.add_argument("sound", type=Path)
    transfer.add_argument("--output", required=True, help="unique MIDI output name or unambiguous substring")
    transfer.add_argument("--receipt", required=True, type=Path, help="non-overwriting JSON receipt written only after success")
    transfer.add_argument("--sysex-pause", type=float, default=0.4)
    transfer.add_argument("--sysex-chunk-bytes", type=int, help="Windows diagnostic fragmentation, e.g. 255 for Midiface")
    transfer.add_argument("--confirm-hardware-write", action="store_true", help="required after verifying backup, Sound ID and live memory")
    render = subparsers.add_parser("compare-render", help="write objective source-versus-module WAV measurements; never records or transfers")
    render.add_argument("--source", required=True, type=Path)
    render.add_argument("--module", required=True, type=Path)
    render.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "discover":
        tools = discover(args.root)
        print(json.dumps({"ddrum4ui": str(tools.ddrum4ui) if tools.ddrum4ui else None, "ddrum4edit": str(tools.ddrum4edit) if tools.ddrum4edit else None}, indent=2))
        return 0 if tools.ddrum4edit else 2
    if args.command == "receive-settings-backup":
        if not args.confirm_listening:
            raise ValueError("this opens a live MIDI input; pass --confirm-listening after starting a module/UI dump")
        count = receive_midi_dump(args.input, args.output, seconds=args.seconds)
        record = validate_settings_backup(args.output)
        metadata = args.output.with_suffix(args.output.suffix + ".json")
        record.write_metadata(metadata)
        print(f"received {count} messages; verified backup metadata at {metadata}")
        return 0
    if args.command == "record-sysex":
        if not args.confirm_listening:
            raise ValueError("this opens a live MIDI input; pass --confirm-listening before manually initiating the stream")
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite recorded SysEx output: {args.output}")
        count = receive_midi_dump(args.input, args.output, seconds=args.seconds)
        print(f"recorded {count} long MIDI/SysEx messages at {args.output}")
        return 0
    if args.command == "compare-plan":
        report = render_comparison(compare_plan(args.plan))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(report, encoding="utf-8")
            print(f"wrote {args.output}")
        else:
            print(report)
        return 0
    if args.command == "report-encoded-bank":
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite actual bank report: {args.output}")
        backend = _backend(args.ddrum4edit)
        report = report_actual_bank(args.capacity_blocks, ((sound, backend.encoded_blocks(sound)) for sound in args.sounds))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report.to_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.output}; {report.used_blocks}/{report.capacity_blocks} blocks")
        return 0
    if args.command == "transfer-sound":
        if args.receipt.exists():
            raise FileExistsError(f"refusing to overwrite transfer receipt: {args.receipt}")
        receipt = transfer_one_sound(
            args.sound, args.output, confirmed=args.confirm_hardware_write,
            sound_id=_backend(args.ddrum4edit).sound_id(args.sound),
            sysex_pause_seconds=args.sysex_pause, sysex_chunk_bytes=args.sysex_chunk_bytes,
        )
        receipt.write(args.receipt)
        print(f"sent {receipt.sound_id} ({receipt.messages_sent} messages) to {receipt.midi_output}; wrote {args.receipt}")
        return 0
    if args.command == "compare-render":
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite render comparison: {args.output}")
        comparison = compare_renders(args.source, args.module)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(comparison.to_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {args.output}; onset delta {comparison.onset_delta_ms:.2f} ms")
        return 0
    if args.command == "inspect-settings-backup":
        print(json.dumps(inspect_settings_backup(args.backup).to_document(), indent=2, sort_keys=True))
        return 0
    if args.command == "create-b0-fixture":
        print(json.dumps(write_fixture_manifest(B0Fixture(), args.wav, args.manifest), indent=2, sort_keys=True))
        return 0
    if args.command == "verify-b0-build":
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite B0 build record: {args.output}")
        blocks = _backend(args.ddrum4edit).encoded_blocks(args.sound)
        record = verify_b0_build(args.fixture_manifest, args.sound, blocks)
        record.write(args.output)
        print(f"verified {blocks} encoded blocks; wrote {args.output}")
        return 0
    if args.command == "compile-nested":
        compilation = compile_nested_file(args.plan)
        if args.firmware_header and args.firmware_header.exists():
            raise FileExistsError(f"refusing to overwrite firmware header: {args.firmware_header}")
        write_compilation(compilation, args.routing_contract, args.report)
        if args.firmware_header:
            generator = Path(__file__).resolve().parents[4] / "firmware/ddrum4-midi-bridge/tools/generate_mapping.py"
            result = subprocess.run([sys.executable, str(generator), str(args.routing_contract), "--output", str(args.firmware_header)], text=True, capture_output=True, check=False)
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "firmware mapping generation failed")
        print(f"wrote {args.routing_contract} and {args.report}")
        return 0
    if args.command == "select-snare":
        # Keep all non-sampler bank commands usable with the documented
        # bank-builder-only PYTHONPATH.
        from .selection import select_snare
        from drum_sampler.library import SampleLibrary
        selection = select_snare(SampleLibrary.read(args.library), args.instrument, args.head_layers, args.rim_layers)
        selection.write(args.output)
        print(f"wrote {args.output} with {len(selection.head)} head and {len(selection.rim)} rim layers")
        return 0
    if args.command == "build-flagship-cymbal":
        from drum_sampler.audio import load_quality_profile
        from drum_sampler.library import SampleLibrary
        from .cymbal_build import materialize_flagship_cymbal
        if args.report.exists():
            raise FileExistsError(f"refusing to overwrite build report: {args.report}")
        profile = load_quality_profile(args.quality_profile, args.quality_name)
        overrides = {
            key: value for key, value in {
                "max_duration_seconds": args.max_duration_seconds,
                "trim_threshold_db": args.trim_threshold_db,
            }.items() if value is not None
        }
        build = materialize_flagship_cymbal(
            SampleLibrary.read(args.library), raw_directory=args.raw_directory,
            output_directory=args.output_directory, sound_id=args.sound_id,
            instrument=args.instrument, template=args.template,
            profile=replace(profile, **overrides), velocities=args.velocities,
            layer_durations=args.layer_durations,
        )
        backend = _backend(args.ddrum4edit)
        backend.build(build.config, build.sound)
        blocks = backend.encoded_blocks(build.sound)
        build.write_report(args.report, blocks)
        print(f"built {build.sound_id}: {blocks} blocks / {len(build.layers)} layers; wrote {args.report}")
        return 0
    if args.command == "build-positional-snare":
        from drum_sampler.audio import load_quality_profile
        from drum_sampler.library import SampleLibrary
        from .snare_build import materialize_positional_snare
        if args.report.exists():
            raise FileExistsError(f"refusing to overwrite build report: {args.report}")
        profile = load_quality_profile(args.quality_profile, args.quality_name)
        build = materialize_positional_snare(
            SampleLibrary.read(args.library),
            raw_directory=args.raw_directory,
            output_directory=args.output_directory,
            sound_id=args.sound_id,
            instrument=args.instrument,
            positions=args.positions,
            velocities=args.velocities,
            template=args.template,
            profile=profile,
        )
        backend = _backend(args.ddrum4edit)
        backend.build(build.config, build.sound)
        blocks = backend.encoded_blocks(build.sound)
        build.write_report(args.report, blocks)
        print(f"built {build.sound_id}: {blocks} blocks, 5 velocities x 2 positions; wrote {args.report}")
        return 0
    if args.command == "build-flagship-hihat":
        from drum_sampler.audio import load_quality_profile
        from drum_sampler.library import SampleLibrary
        from .hihat_build import (
            FLAGSHIP_HIHAT_BRANCHES,
            FLAGSHIP_HIHAT_EDGE_BRANCHES,
            materialize_flagship_hihat,
        )
        if args.report.exists():
            raise FileExistsError(f"refusing to overwrite build report: {args.report}")
        profile = load_quality_profile(args.quality_profile, args.quality_name)
        build = materialize_flagship_hihat(
            SampleLibrary.read(args.library),
            raw_directory=args.raw_directory,
            output_directory=args.output_directory,
            sound_id=args.sound_id,
            instrument=args.instrument,
            template=args.template,
            profile=profile,
            branches=(
                FLAGSHIP_HIHAT_BRANCHES
                if args.layout == "bow"
                else FLAGSHIP_HIHAT_EDGE_BRANCHES
            ),
        )
        backend = _backend(args.ddrum4edit)
        backend.build(build.config, build.sound)
        blocks = backend.encoded_blocks(build.sound)
        build.write_report(args.report, blocks)
        print(f"built {build.sound_id}: {blocks} blocks, 8 positions / {len(build.layers)} layers; wrote {args.report}")
        return 0
    backend = _backend(args.ddrum4edit)
    if args.command == "inspect":
        print(backend.inspect(args.sound), end="")
    else:
        print(backend.encoded_blocks(args.sound))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
