from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .compiler import RigCompilerError, compile_project, validate_project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rig-compiler", description="Offline rig-project validator and compiler (never opens hardware ports).")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("project", type=Path)
    report = commands.add_parser("report", help="Print the declarative project report without writing artifacts")
    report.add_argument("project", type=Path)
    compile_ = commands.add_parser("compile")
    compile_.add_argument("project", type=Path)
    compile_.add_argument("--output", required=True, type=Path, help="Explicit directory for generated artifacts")
    compile_.add_argument("--replace", action="store_true", help="Allow replacement of existing generated artifacts")
    compile_.add_argument("--base-dump", type=Path, help="Record its path and SHA-256 for a planned DDTi staging request; no dump is generated")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            result = validate_project(args.project)
            print(f"valid: {result.source} ({result.source_sha256})")
        elif args.command == "report":
            result = validate_project(args.project)
            print(json.dumps(result.artifacts["project-report.json"], indent=2, sort_keys=True))
        else:
            result = compile_project(args.project, args.output, replace=args.replace, base_dump=args.base_dump)
            print(f"compiled {len(result.artifacts)} offline artifacts to {args.output}")
        return 0
    except (RigCompilerError, FileExistsError) as error:
        print(f"rig-compiler: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
