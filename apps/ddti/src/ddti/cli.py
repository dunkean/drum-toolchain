"""Safe command line interface.  Every command is read-only or offline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .capture import capture_dump, capture_series
from .diff import diff_files, render_diff
from .discovery import discover_devices
from .monitor import monitor
from .models import decode_configuration
from .protocol import decode_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ddti", description="Safe read-first tooling for the legacy ddrum DDTi")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("devices", help="list DDTi USB/MIDI candidates without opening a port")
    commands.add_parser("info", help="show the single DDTi candidate without opening a port")
    watch = commands.add_parser("monitor", help="display received MIDI; never sends MIDI")
    watch.add_argument("--input", required=True, help="unique DDTi MIDI input name or substring")
    watch.add_argument("--seconds", type=float, help="bounded duration; omit to monitor until Ctrl+C")
    watch.add_argument("--output", type=Path, help="new JSON Lines capture file")
    dump = commands.add_parser("dump", help="listen for a panel-initiated SysEx dump; never sends a request")
    dump.add_argument("stem", type=Path, help="output stem, without .syx/.hex/.json")
    dump.add_argument("--input", required=True, help="unique DDTi MIDI input name or substring")
    dump.add_argument("--listen", action="store_true", help="required acknowledgement that this command only waits for a manual panel dump")
    dump.add_argument("--seconds", type=float, default=90)
    dump.add_argument("--idle-seconds", type=float, default=5)
    dump.add_argument("--receiver", choices=("auto", "mido"), default="auto", help="auto uses Windows long-message capture; mido is an independent diagnostic receiver")
    session = commands.add_parser("session", help="capture several manual panel dumps in one receive-only session")
    session.add_argument("directory", type=Path, help="new capture artifact directory")
    session.add_argument("--input", required=True, help="unique DDTi MIDI input name or substring")
    session.add_argument("--listen", action="store_true", help="required acknowledgement that every snapshot waits for a manual panel dump")
    session.add_argument("--label", default="snapshot", help="safe output prefix for sequential captures")
    session.add_argument("--snapshots", type=int, required=True, help="number of manual dumps to collect")
    session.add_argument("--seconds-per-snapshot", type=float, default=300)
    session.add_argument("--idle-seconds", type=float, default=5)
    session.add_argument("--compare-to", type=Path, help="known baseline .syx; print an offline structural diff for every snapshot")
    comparison = commands.add_parser("diff", help="offline byte-level diff of two complete .syx streams")
    comparison.add_argument("before", type=Path)
    comparison.add_argument("after", type=Path)
    decode = commands.add_parser("decode", help="inspect observed legacy DDTi packet structure offline")
    decode.add_argument("dump", type=Path)
    export_preset = commands.add_parser("export-preset", help="export all confirmed MIDI notes to a new portable JSON preset")
    export_preset.add_argument("dump", type=Path)
    export_preset.add_argument("output", type=Path, help="new .json file; existing files are refused")
    apply_preset = commands.add_parser("apply-preset", help="apply a note preset to a dump and write a new staged SysEx file")
    apply_preset.add_argument("dump", type=Path)
    apply_preset.add_argument("preset", type=Path)
    apply_preset.add_argument("output", type=Path, help="new .syx file; existing files are refused")
    api = commands.add_parser("serve", help="run the optional local FastAPI service against a captured dump")
    api.add_argument("dump", type=Path)
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8765)
    gui = commands.add_parser("gui", help="run the optional offline PySide6 note editor")
    gui.add_argument("dump", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "devices":
        print(json.dumps([device.to_document() for device in discover_devices()], indent=2, sort_keys=True))
    elif args.command == "info":
        devices = discover_devices()
        if len(devices) != 1:
            raise RuntimeError(f"expected exactly one DDTi candidate; found {len(devices)}")
        print(json.dumps(devices[0].to_document(), indent=2, sort_keys=True))
    elif args.command == "monitor":
        print(f"monitoring {args.input!r}; this command never opens a MIDI output", flush=True)
        print(f"received {monitor(args.input, seconds=args.seconds, output=args.output)} message(s)")
    elif args.command == "dump":
        if not args.listen:
            raise ValueError("dump is receive-only; pass --listen after starting no other MIDI sender and preparing the panel export")
        print(
            f"listening on {args.input!r} for a panel-initiated SysEx dump; "
            "this command never opens a MIDI output",
            flush=True,
        )
        result = capture_dump(args.input, args.stem, seconds=args.seconds, idle_seconds=args.idle_seconds, receiver=args.receiver)
        print(json.dumps({"syx": str(result.syx_path), "hex": str(result.hex_path), "metadata": str(result.metadata_path), "sha256": result.sha256, "messages": result.message_count}, indent=2))
    elif args.command == "session":
        if not args.listen:
            raise ValueError("session is receive-only; pass --listen after preparing the panel dump sequence")
        def announce(number: int, stem: Path) -> None:
            print(
                f"snapshot {number}/{args.snapshots}: listening on {args.input!r} for a panel-initiated dump; "
                "this command never opens a MIDI output",
                flush=True,
            )
        results = capture_series(
            args.input,
            args.directory,
            label=args.label,
            snapshots=args.snapshots,
            seconds_per_snapshot=args.seconds_per_snapshot,
            idle_seconds=args.idle_seconds,
            on_listening=announce,
        )
        summary = [
            {"syx": str(result.syx_path), "sha256": result.sha256, "messages": result.message_count}
            for result in results
        ]
        print(json.dumps(summary, indent=2))
        if args.compare_to:
            print(f"offline comparisons against {args.compare_to}:")
            for number, result in enumerate(results, start=1):
                differences = diff_files(args.compare_to, result.syx_path)
                print(f"\nsnapshot {number}: {result.syx_path}")
                print(render_diff(differences), end="")
    elif args.command == "diff":
        print(render_diff(diff_files(args.before, args.after)), end="")
    elif args.command == "decode":
        dump = decode_file(args.dump)
        document = dump.to_document()
        document["configuration"] = decode_configuration(dump).to_document()
        print(json.dumps(document, indent=2, sort_keys=True))
    elif args.command == "export-preset":
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite existing file: {args.output}")
        configuration = decode_configuration(decode_file(args.dump))
        args.output.write_text(json.dumps(configuration.to_note_preset(), indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"preset": str(args.output), "hardware_write": "disabled"}, indent=2))
    elif args.command == "apply-preset":
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite existing file: {args.output}")
        document = json.loads(args.preset.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("preset root must be an object")
        configuration = decode_configuration(decode_file(args.dump)).with_note_preset(document)
        args.output.write_bytes(configuration.raw)
        print(json.dumps({"staged_syx": str(args.output), "hardware_write": "disabled"}, indent=2))
    elif args.command == "serve":
        from .api import create_app
        try:
            import uvicorn
        except ImportError as error:
            raise RuntimeError("install the 'ddti[api]' extra to run the local API") from error
        uvicorn.run(create_app(args.dump), host=args.host, port=args.port)
    else:
        from .gui import launch
        return launch(args.dump)
    return 0
