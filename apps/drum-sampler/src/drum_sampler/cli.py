"""Safe command-line entry point for planning sampler sessions.

This command deliberately creates metadata only. Audio capture is added as a
separate explicit operation so generating a plan can never trigger a VST or a
hardware module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .library import library_from_plan
from .recorder import capture_pending, library_from_captures
from .exporters import export_drumgizmo
from .library import SampleLibrary
from .session import CaptureRequest, CaptureSessionPlan
from .quality import CaptureQualityPolicy, audit_library
from .audio import load_quality_profile
from .calibration import calibrate_session_file
from .offline import (apply_captured_drumgizmo_composites, audit_drumgizmo_composites, capture_drumgizmo_composites, drumgizmo_note_overrides, expand_shared_variations, export_report, merge_library_files,
                      prepare_selected_takes, run_offline_recipe, verify_drumgizmo_kit)
from .offline import (validate_drumgizmo_composite_report, verify_drumgizmo_validation_report,
                      write_drumgizmo_validation_report)
from .offline import drumgizmo_instrument_groups, resolved_drumgizmo_note_overrides


def _request(value: str) -> CaptureRequest:
    """Parse ``instrument:articulation:note:velocity,...:repetitions``."""
    try:
        instrument, articulation, note, velocities, repetitions = value.split(":")
        return CaptureRequest(instrument, articulation, int(note), tuple(int(item) for item in velocities.split(",")), int(repetitions))
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(
            "request must be instrument:articulation:note:velocity,...:repetitions"
        ) from error


def _write_json_atomic(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _validate_megakit_export_inputs(library: SampleLibrary, *, library_path: Path,
                                    audio_root: Path, plan_path: Path,
                                    output_directory: Path) -> None:
    """Make the direct CLI obey the same immutable campaign gates as the GUI."""
    campaign_path = library_path.parent / "campaign.json"
    quality_path = library_path.parent / "reports" / "quality.json"
    session_path = library_path.parent / "capture-session.json"
    composite_report = library_path.parent / "reports" / "composite-quality.json"
    composite_root = output_directory.parent / "drumgizmo-composite-wav"
    try:
        campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("MegaKit export requires its complete campaign and quality reports") from error
    expected = campaign.get("expected_take_count")
    summary = quality.get("summary")
    if (not isinstance(expected, int) or len(library.takes) != expected
            or any(take.status != "captured" for take in library.takes)
            or campaign.get("capture_session_sha256")
            != hashlib.sha256(session_path.read_bytes()).hexdigest()
            or quality.get("kind") != "capture-quality-report"
            or quality.get("library_sha256") != hashlib.sha256(library_path.read_bytes()).hexdigest()
            or quality.get("session_sha256") != hashlib.sha256(session_path.read_bytes()).hexdigest()
            or not isinstance(summary, dict) or summary.get("accepted") != expected
            or summary.get("rejected") != 0 or summary.get("missing") != 0
            or summary.get("round_robin_duplicate_cells") != 0):
        raise ValueError("MegaKit export requires a complete, passing, current full-capture quality report")
    declared_plan = campaign.get("megakit_plan_file")
    declared_preset = campaign.get("sd3_preset_file")
    declared_preset_sha256 = campaign.get("sd3_preset_sha256")
    if (not isinstance(declared_plan, str) or not Path(declared_plan).is_file()
            or hashlib.sha256(Path(declared_plan).read_bytes()).hexdigest()
            != hashlib.sha256(plan_path.read_bytes()).hexdigest()):
        raise ValueError("MegaKit export plan differs from the plan frozen in the campaign")
    if (not isinstance(declared_preset, str) or not Path(declared_preset).is_file()
            or not isinstance(declared_preset_sha256, str)
            or hashlib.sha256(Path(declared_preset).read_bytes()).hexdigest() != declared_preset_sha256):
        raise ValueError("campaign SD3 preset is missing or no longer matches its approved fingerprint")
    records = quality.get("takes")
    if not isinstance(records, list) or len(records) != expected:
        raise ValueError("full-capture quality report does not contain the exact take grid")
    indexed: dict[tuple[str, str, int, int], dict[str, object]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("full-capture quality report contains an invalid take")
        try:
            key = (str(record["instrument"]), str(record["articulation"]),
                   int(record["velocity"]), int(record["repetition"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("full-capture quality report contains an invalid take identity") from error
        if key in indexed:
            raise ValueError(f"full-capture quality report duplicates take {key}")
        indexed[key] = record
    for take in library.takes:
        key = (take.instrument, take.articulation, take.velocity, take.repetition)
        record = indexed.get(key)
        path = audio_root / take.raw_file
        facts = record.get("facts") if record is not None else None
        if (record is None or record.get("automatic_status") != "accepted"
                or not isinstance(facts, dict) or not path.is_file()
                or facts.get("sha256") != take.sha256
                or facts.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest()):
            raise ValueError(f"raw take changed or is not quality-approved: {key}")
    validate_drumgizmo_composite_report(
        composite_report, session_path=session_path, composite_root=composite_root,
        plan_path=plan_path,
    )


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
    composites = subparsers.add_parser("capture-composites", help="capture simultaneous SD3 layer chords for DrumGizmo")
    composites.add_argument("--session", required=True, type=Path)
    composites.add_argument("--megakit-plan", required=True, type=Path)
    composites.add_argument("--output-directory", required=True, type=Path)
    composites.add_argument("--quality-report", required=True, type=Path)
    composites.add_argument("--confirm-capture", action="store_true")
    audit_composites = subparsers.add_parser(
        "audit-composites",
        help="re-audit existing simultaneous layer WAVs without MIDI or audio I/O",
    )
    audit_composites.add_argument("--session", required=True, type=Path)
    audit_composites.add_argument("--megakit-plan", required=True, type=Path)
    audit_composites.add_argument("--input-directory", required=True, type=Path)
    audit_composites.add_argument("--quality-report", required=True, type=Path)
    calibrate = subparsers.add_parser("calibrate", help="capture one bounded representative hit per articulation before a full campaign")
    calibrate.add_argument("--session", required=True, type=Path)
    calibrate.add_argument("--preset-file", required=True, type=Path)
    calibrate.add_argument("--expected-preset-sha256")
    calibrate.add_argument("--output-directory", required=True, type=Path)
    calibrate.add_argument("--report", required=True, type=Path)
    calibrate.add_argument("--preferred-velocity", type=int, default=110)
    calibrate.add_argument("--duration-seconds", type=float, default=1.5)
    calibrate.add_argument("--relative-outlier-db", type=float, default=12.0)
    calibrate.add_argument(
        "--only", action="append", default=[], metavar="INSTRUMENT.ARTICULATION",
        help="capture only an exact articulation selector; repeat as needed (probes are reused by the later full run)",
    )
    calibrate.add_argument("--confirm-capture", action="store_true", help="required: sends bounded MIDI notes and records the named audio input")
    calibrate.add_argument("--confirm-preset-loaded", action="store_true", help="required: confirms the exact fingerprinted SD3 preset is loaded")
    drumgizmo = subparsers.add_parser("export-drumgizmo", help="export a captured neutral library as a DrumGizmo 2.0 kit")
    drumgizmo.add_argument("--library", required=True, type=Path)
    drumgizmo.add_argument("--audio-root", required=True, type=Path)
    drumgizmo.add_argument("--output-directory", required=True, type=Path)
    drumgizmo.add_argument("--title")
    drumgizmo.add_argument("--reference-audio", action="store_true", help="reference source WAV paths instead of copying them into the kit")
    drumgizmo.add_argument("--note-map", type=Path, help="generated drumgizmo-midimap.json artifact")
    drumgizmo.add_argument("--megakit-plan", type=Path, help="expand metadata-only shared variations without recapturing or duplicating WAVs")
    drumgizmo.add_argument("--report", type=Path, help="write an offline export report")
    verify_drumgizmo = subparsers.add_parser("verify-drumgizmo", help="validate a kit XML and record DrumGizmo version/backend without starting audio")
    verify_drumgizmo.add_argument("--kit-directory", required=True, type=Path)
    verify_drumgizmo.add_argument("--report", required=True, type=Path)
    verify_drumgizmo.add_argument("--drumgizmo", default="drumgizmo", help="DrumGizmo executable")
    verify_drumgizmo.add_argument("--backend", default="jackmidi", help="declared MIDI backend for the future live load")
    validate_drumgizmo = subparsers.add_parser("validate-drumgizmo", help="validate and fingerprint a self-contained DrumGizmo kit without requiring DrumGizmo")
    validate_drumgizmo.add_argument("--kit-directory", required=True, type=Path)
    validate_drumgizmo.add_argument("--report", required=True, type=Path)
    verify_manifest = subparsers.add_parser("verify-drumgizmo-manifest", help="reject any kit byte changed after internal validation")
    verify_manifest.add_argument("--kit-directory", required=True, type=Path)
    verify_manifest.add_argument("--report", required=True, type=Path)
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
    audit.add_argument("--session", type=Path, help="bind the report to the exact capture-session file")
    audit.add_argument("--minimum-duration-ms", type=int, default=80)
    audit.add_argument("--silence-rms-dbfs", type=float, default=-75.0)
    audit.add_argument("--allow-clipped", action="store_true")
    audit.add_argument("--expected-sample-rate", type=int)
    audit.add_argument("--expected-channels", type=int)
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
            adjacent_campaign = args.library.parent / "campaign.json"
            if adjacent_campaign.is_file() and not args.megakit_plan:
                try:
                    adjacent_document = json.loads(adjacent_campaign.read_text(encoding="utf-8"))
                except json.JSONDecodeError as error:
                    raise ValueError("adjacent capture campaign is invalid") from error
                if adjacent_document.get("megakit_plan_file"):
                    raise ValueError(
                        "this campaign is a MegaKit export; --megakit-plan is required so its quality gates cannot be bypassed"
                    )
            if args.megakit_plan:
                _validate_megakit_export_inputs(
                    library, library_path=args.library, audio_root=args.audio_root,
                    plan_path=args.megakit_plan, output_directory=args.output_directory,
                )
                library = apply_captured_drumgizmo_composites(
                    library,
                    composite_root=args.output_directory.parent / "drumgizmo-composite-wav",
                    plan_path=args.megakit_plan,
                )
                library = expand_shared_variations(library, args.megakit_plan)
            overrides = resolved_drumgizmo_note_overrides(args.note_map, args.megakit_plan)
            groups = drumgizmo_instrument_groups(args.megakit_plan) if args.megakit_plan else {}
            export = export_drumgizmo(
                library, audio_root=args.audio_root, output_directory=args.output_directory,
                title=args.title, copy_audio=not args.reference_audio,
                midi_notes=overrides, instrument_groups=groups,
            )
            if args.report:
                report = export_report(library, overrides=overrides, output_directory=args.output_directory)
                report["inputs"] = {
                    "library": str(args.library.resolve()),
                    "library_sha256": hashlib.sha256(args.library.read_bytes()).hexdigest(),
                    "audio_root": str(args.audio_root.resolve()),
                    "note_map": str(args.note_map.resolve()) if args.note_map else None,
                    "note_map_sha256": hashlib.sha256(args.note_map.read_bytes()).hexdigest() if args.note_map else None,
                    "megakit_plan": str(args.megakit_plan.resolve()) if args.megakit_plan else None,
                    "megakit_plan_sha256": hashlib.sha256(args.megakit_plan.read_bytes()).hexdigest() if args.megakit_plan else None,
                    "composite_root": str((args.output_directory.parent / "drumgizmo-composite-wav").resolve()) if args.megakit_plan else None,
                    "composite_mode": "simultaneous-midi-chord" if args.megakit_plan else None,
                }
                campaign_path = args.library.parent / "campaign.json"
                if campaign_path.is_file():
                    campaign_document = json.loads(campaign_path.read_text(encoding="utf-8"))
                    report["inputs"]["campaign"] = str(campaign_path.resolve())
                    report["inputs"]["campaign_sha256"] = hashlib.sha256(campaign_path.read_bytes()).hexdigest()
                    report["inputs"]["sd3_preset_file"] = campaign_document.get("sd3_preset_file")
                    report["inputs"]["sd3_preset_sha256"] = campaign_document.get("sd3_preset_sha256")
                for name in ("quality.json", "composite-quality.json"):
                    quality_path = args.library.parent / "reports" / name
                    if quality_path.is_file():
                        key = name.removesuffix(".json").replace("-", "_")
                        report["inputs"][f"{key}_report"] = str(quality_path.resolve())
                        report["inputs"][f"{key}_report_sha256"] = hashlib.sha256(quality_path.read_bytes()).hexdigest()
                _write_json_atomic(
                    args.report, report,
                )
            print(f"wrote DrumGizmo kit {export.drumkit} with {len(export.instruments)} instruments")
            return 0
        if args.command == "capture-composites":
            if not args.confirm_capture:
                raise ValueError("composite capture sends MIDI and records audio; pass --confirm-capture")
            captured = capture_drumgizmo_composites(
                CaptureSessionPlan.read(args.session),
                plan_path=args.megakit_plan,
                output_root=args.output_directory,
            )
            report = audit_drumgizmo_composites(
                CaptureSessionPlan.read(args.session),
                plan_path=args.megakit_plan,
                composite_root=args.output_directory,
            )
            report["session_sha256"] = hashlib.sha256(args.session.read_bytes()).hexdigest()
            _write_json_atomic(args.quality_report, report)
            if (report["summary"]["rejected"] or report["summary"]["missing"]
                    or report["summary"]["round_robin_duplicate_cells"]):
                print(f"composite quality failed: {report['summary']}")
                return 2
            print(f"captured {len(captured)} new simultaneous DrumGizmo layer takes")
            return 0
        if args.command == "audit-composites":
            report = audit_drumgizmo_composites(
                CaptureSessionPlan.read(args.session),
                plan_path=args.megakit_plan,
                composite_root=args.input_directory,
            )
            report["session_sha256"] = hashlib.sha256(args.session.read_bytes()).hexdigest()
            _write_json_atomic(args.quality_report, report)
            summary = report["summary"]
            print(f"wrote composite quality report {args.quality_report}: {summary}")
            return 0 if (summary["rejected"] == 0
                         and summary["missing"] == 0
                         and summary["round_robin_duplicate_cells"] == 0) else 2
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
            policy = CaptureQualityPolicy(
                args.minimum_duration_ms, args.silence_rms_dbfs, not args.allow_clipped,
                args.expected_sample_rate, args.expected_channels,
            )
            report = audit_library(SampleLibrary.read(args.library), args.audio_root, policy)
            report["library_sha256"] = hashlib.sha256(args.library.read_bytes()).hexdigest()
            if args.session:
                report["session_sha256"] = hashlib.sha256(args.session.read_bytes()).hexdigest()
            _write_json_atomic(args.output, report)
            print(f"wrote quality report {args.output}: {report['summary']}")
            return 0 if (report["summary"]["rejected"] == 0
                         and report["summary"]["missing"] == 0
                         and report["summary"]["round_robin_duplicate_cells"] == 0) else 2
        if args.command == "validate-drumgizmo":
            report = write_drumgizmo_validation_report(args.kit_directory, args.report)
            print(f"validated {len(report['files'])} DrumGizmo files: {report['kit']}")
            return 0
        if args.command == "verify-drumgizmo-manifest":
            report = verify_drumgizmo_validation_report(args.kit_directory, args.report)
            print(f"verified {len(report['files'])} immutable DrumGizmo files")
            return 0
        if args.command == "calibrate":
            if not args.confirm_capture:
                raise ValueError("calibration sends MIDI and records audio; pass --confirm-capture after checking the session")
            if not args.confirm_preset_loaded:
                raise ValueError("calibration requires confirmation that the exact SD3 preset is loaded")
            report = calibrate_session_file(
                args.session, args.preset_file, args.output_directory, args.report,
                expected_preset_sha256=args.expected_preset_sha256,
                preset_loaded_confirmed=True,
                preferred_velocity=args.preferred_velocity,
                duration_seconds=args.duration_seconds,
                relative_outlier_db=args.relative_outlier_db,
                only=tuple(args.only),
                progress=lambda index, total, row: print(
                    f"[{index}/{total}] {row['instrument']}.{row['articulation']} "
                    f"note={row['note']} velocity={row['velocity']} "
                    f"peak={row['peak_dbfs']} dBFS findings={row['findings']}",
                    flush=True,
                ),
            )
            print(f"wrote calibration report {args.report}: {report['summary']}")
            return 0 if not str(report["summary"]["status"]).endswith("-fail") else 2
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
