"""Safe command line interface.  Every command is read-only or offline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .capture import capture_dump
from .diff import diff_files, render_diff
from .discovery import discover_devices
from .monitor import monitor
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
    comparison = commands.add_parser("diff", help="offline byte-level diff of two complete .syx streams")
    comparison.add_argument("before", type=Path)
    comparison.add_argument("after", type=Path)
    decode = commands.add_parser("decode", help="inspect observed legacy DDTi packet structure offline")
    decode.add_argument("dump", type=Path)
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
        result = capture_dump(args.input, args.stem, seconds=args.seconds, idle_seconds=args.idle_seconds)
        print(json.dumps({"syx": str(result.syx_path), "hex": str(result.hex_path), "metadata": str(result.metadata_path), "sha256": result.sha256, "messages": result.message_count}, indent=2))
    elif args.command == "diff":
        print(render_diff(diff_files(args.before, args.after)), end="")
    else:
        print(json.dumps(decode_file(args.dump).to_document(), indent=2, sort_keys=True))
    return 0
