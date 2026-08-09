"""Safe command-line entry point for planning sampler sessions.

This command deliberately creates metadata only. Audio capture is added as a
separate explicit operation so generating a plan can never trigger a VST or a
hardware module.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .library import library_from_plan
from .recorder import capture_pending, library_from_captures
from .session import CaptureRequest, CaptureSessionPlan


def _request(value: str) -> CaptureRequest:
    """Parse ``instrument:articulation:note:velocity,...:repetitions``."""
    try:
        instrument, articulation, note, velocities, repetitions = value.split(":")
        return CaptureRequest(instrument, articulation, int(note), tuple(int(item) for item in velocities.split(",")), int(repetitions))
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(
            "request must be instrument:articulation:note:velocity,...:repetitions"
        ) from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="drum-sampler", description="Create deterministic neutral sample-library plans.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fixture = subparsers.add_parser("fixture", help="write a small, hardware-free sample-library fixture")
    fixture.add_argument("--output", required=True, type=Path)
    fixture.add_argument("--id", default="fixture-snare")

    plan = subparsers.add_parser("plan", help="write a neutral sample-library plan")
    plan.add_argument("--output", required=True, type=Path)
    plan.add_argument("--id", required=True)
    plan.add_argument("--midi-output", required=True)
    plan.add_argument("--audio-input", required=True)
    plan.add_argument("--channels", required=True, help="comma-separated named capture channels")
    plan.add_argument("--request", required=True, action="append", type=_request)
    plan.add_argument("--session-output", type=Path, help="also write the versioned capture-session document")
    capture = subparsers.add_parser("capture", help="execute a saved capture session only with explicit confirmation")
    capture.add_argument("--session", required=True, type=Path)
    capture.add_argument("--raw-directory", required=True, type=Path)
    capture.add_argument("--library-output", required=True, type=Path)
    capture.add_argument("--id", required=True)
    capture.add_argument("--source", required=True)
    capture.add_argument("--license", required=True)
    capture.add_argument("--confirm-capture", action="store_true", help="required: sends MIDI and records the named audio input")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "fixture":
        request = CaptureRequest("snare_main", "head", 38, (32, 80, 127), 2)
        session = CaptureSessionPlan("fixture-midi", "fixture-audio", ("left", "right"), (request,))
    elif args.command == "plan":
        channels = tuple(item.strip() for item in args.channels.split(",") if item.strip())
        session = CaptureSessionPlan(args.midi_output, args.audio_input, channels, tuple(args.request))
    else:
        if not args.confirm_capture:
            raise ValueError("capture sends MIDI and records audio; pass --confirm-capture after checking the session")
        session = CaptureSessionPlan.read(args.session)
        captured = capture_pending(session, args.raw_directory)
        library_from_captures(args.id, session, args.raw_directory, source=args.source, license_statement=args.license).write(args.library_output)
        print(f"captured {len(captured)} new takes and wrote {args.library_output}")
        return 0
    library_from_plan(args.id, session.channels, session.takes()).write(args.output)
    if args.command == "plan" and args.session_output:
        session.write(args.session_output)
    print(f"wrote {len(session.takes())} planned takes to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
