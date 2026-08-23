"""Safe command-line entry point for planning sampler sessions.

This command deliberately creates metadata only. Audio capture is added as a
separate explicit operation so generating a plan can never trigger a VST or a
hardware module.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .library import library_from_plan
from .recorder import capture_pending, library_from_captures
from .exporters import export_drumgizmo
from .library import SampleLibrary
from .session import CaptureRequest, CaptureSessionPlan
from .quality import CaptureQualityPolicy, audit_library
from .audio import load_quality_profile
from .offline import (drumgizmo_note_overrides, export_report, merge_library_files,
                      prepare_selected_takes, run_offline_recipe, verify_drumgizmo_kit)


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
    drumgizmo = subparsers.add_parser("export-drumgizmo", help="export a captured neutral library as a DrumGizmo 2.0 kit")
    drumgizmo.add_argument("--library", required=True, type=Path)
    drumgizmo.add_argument("--audio-root", required=True, type=Path)
    drumgizmo.add_argument("--output-directory", required=True, type=Path)
    drumgizmo.add_argument("--title")
    drumgizmo.add_argument("--reference-audio", action="store_true", help="reference source WAV paths instead of copying them into the kit")
    drumgizmo.add_argument("--note-map", type=Path, help="generated drumgizmo-midimap.json artifact")
    drumgizmo.add_argument("--report", type=Path, help="write an offline export report")
    verify_drumgizmo = subparsers.add_parser("verify-drumgizmo", help="validate a kit XML and record DrumGizmo version/backend without starting audio")
    verify_drumgizmo.add_argument("--kit-directory", required=True, type=Path)
    verify_drumgizmo.add_argument("--report", required=True, type=Path)
    verify_drumgizmo.add_argument("--drumgizmo", default="drumgizmo", help="DrumGizmo executable")
    verify_drumgizmo.add_argument("--backend", default="jackmidi", help="declared MIDI backend for the future live load")
    prepare = subparsers.add_parser("prepare-offline", help="non-destructively prepare existing raw takes")
    prepare.add_argument("--library", required=True, type=Path); prepare.add_argument("--audio-root", required=True, type=Path)
    prepare.add_argument("--output-root", required=True, type=Path); prepare.add_argument("--profile", required=True, type=Path)
    prepare.add_argument("--profile-name", required=True); prepare.add_argument("--output-library", required=True, type=Path)
    merge = subparsers.add_parser("merge-libraries", help="merge offline library manifests")
    merge.add_argument("--id", required=True); merge.add_argument("--source", required=True, action="append", help="library.json:relative-prefix")
    merge.add_argument("--output", required=True, type=Path)
    recipe = subparsers.add_parser("offline-recipe", help="write a resumable offline export report")
    recipe.add_argument("--recipe", required=True, type=Path); recipe.add_argument("--report", required=True, type=Path)
    audit = subparsers.add_parser("audit-quality", help="classify captured WAVs without changing them")
    audit.add_argument("--library", required=True, type=Path)
    audit.add_argument("--audio-root", required=True, type=Path)
    audit.add_argument("--output", required=True, type=Path)
    audit.add_argument("--minimum-duration-ms", type=int, default=80)
    audit.add_argument("--silence-rms-dbfs", type=float, default=-75.0)
    audit.add_argument("--allow-clipped", action="store_true")
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
        if args.command == "export-drumgizmo":
            library = SampleLibrary.read(args.library)
            overrides = drumgizmo_note_overrides(args.note_map) if args.note_map else {}
            export = export_drumgizmo(library, audio_root=args.audio_root, output_directory=args.output_directory, title=args.title, copy_audio=not args.reference_audio, midi_notes=overrides)
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(export_report(library, overrides=overrides, output_directory=args.output_directory), indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"wrote DrumGizmo kit {export.drumkit} with {len(export.instruments)} instruments")
            return 0
        if args.command == "verify-drumgizmo":
            report = verify_drumgizmo_kit(args.kit_directory, args.report, executable=args.drumgizmo,
                                           backend=args.backend)
            print(f"verified DrumGizmo {report['drumgizmo']['version']} for {report['backend']}")
            return 0
        if args.command == "prepare-offline":
            prepared = prepare_selected_takes(SampleLibrary.read(args.library), audio_root=args.audio_root, output_root=args.output_root,
                                              profile=load_quality_profile(args.profile, args.profile_name))
            prepared.write(args.output_library); print(f"wrote prepared library {args.output_library}"); return 0
        if args.command == "merge-libraries":
            sources = []
            for value in args.source:
                path, separator, prefix = value.rpartition(":")
                if not separator: raise ValueError("--source must be library.json:relative-prefix")
                sources.append((Path(path), prefix))
            merge_library_files(args.id, tuple(sources)).write(args.output); print(f"wrote merged library {args.output}"); return 0
        if args.command == "offline-recipe":
            run_offline_recipe(args.recipe, args.report); print(f"wrote offline recipe report {args.report}"); return 0
        if args.command == "audit-quality":
            policy = CaptureQualityPolicy(args.minimum_duration_ms, args.silence_rms_dbfs, not args.allow_clipped)
            report = audit_library(SampleLibrary.read(args.library), args.audio_root, policy)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"wrote quality report {args.output}: {report['summary']}")
            return 0
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
