"""Non-destructive ddrum4 backend inspection commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ddrum4edit_backend import Ddrum4EditBackend
from .ddrum4ui import discover
from .backup import validate_settings_backup
from .transport import receive_midi_dump


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
    backend = _backend(args.ddrum4edit)
    if args.command == "inspect":
        print(backend.inspect(args.sound), end="")
    else:
        print(backend.encoded_blocks(args.sound))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
