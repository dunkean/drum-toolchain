"""Non-destructive ddrum4 backend inspection commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ddrum4edit_backend import Ddrum4EditBackend
from .ddrum4ui import discover


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "discover":
        tools = discover(args.root)
        print(json.dumps({"ddrum4ui": str(tools.ddrum4ui) if tools.ddrum4ui else None, "ddrum4edit": str(tools.ddrum4edit) if tools.ddrum4edit else None}, indent=2))
        return 0 if tools.ddrum4edit else 2
    backend = _backend(args.ddrum4edit)
    if args.command == "inspect":
        print(backend.inspect(args.sound), end="")
    else:
        print(backend.encoded_blocks(args.sound))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
