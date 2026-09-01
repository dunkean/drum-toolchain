"""Reproducible, hardware-safe SD3 capture campaign records.

The Control Center owns the operator-facing campaign document.  It writes the
same ``capture-session`` JSON consumed by drum-sampler, but never opens MIDI or
audio devices itself.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

import yaml


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class CaptureRow:
    """One SD3 instrument articulation to capture completely."""

    instrument: str
    articulation: str
    note: int
    velocities: tuple[int, ...]
    repetitions: int
    channel: int = 10
    controllers: tuple[tuple[int, int], ...] = ()
    drumgizmo_note: int | None = None

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.instrument):
            raise ValueError("instrument must use a lowercase English identifier")
        if not _IDENTIFIER.fullmatch(self.articulation):
            raise ValueError("articulation must use a lowercase English identifier")
        if not 0 <= self.note <= 127 or not 1 <= self.channel <= 16:
            raise ValueError("MIDI note must be 0..127 and channel must be 1..16")
        if not self.velocities or tuple(sorted(set(self.velocities))) != self.velocities:
            raise ValueError("velocities must be a non-empty, unique ascending list")
        if any(value < 1 or value > 127 for value in self.velocities):
            raise ValueError("velocities must be in 1..127")
        if self.repetitions < 1:
            raise ValueError("repetitions must be positive")
        if any(not 0 <= controller <= 127 or not 0 <= value <= 127
               for controller, value in self.controllers):
            raise ValueError("controller numbers and values must be in 0..127")
        if len({controller for controller, _ in self.controllers}) != len(self.controllers):
            raise ValueError("one capture row cannot set the same controller twice")
        if self.drumgizmo_note is not None and not 0 <= self.drumgizmo_note <= 127:
            raise ValueError("DrumGizmo note must be in 0..127")

    def to_document(self) -> dict[str, object]:
        document: dict[str, object] = {
            "instrument": self.instrument,
            "articulation": self.articulation,
            "note": self.note,
            "channel": self.channel,
            "controllers": [list(pair) for pair in self.controllers],
            "velocities": list(self.velocities),
            "repetitions": self.repetitions,
        }
        if self.drumgizmo_note is not None:
            document["drumgizmo_note"] = self.drumgizmo_note
        return document

    def raw_filenames(self) -> tuple[str, ...]:
        return tuple(
            f"{self.instrument}__{self.articulation}__v{velocity:03d}__rr{repetition:02d}_raw.wav"
            for velocity in self.velocities for repetition in range(1, self.repetitions + 1)
        )


@dataclass(frozen=True)
class CalibrationLevelGroup:
    """One musically comparable family from an SD3 calibration report."""

    name: str
    articulations: int
    peak_span_db: float
    quietest_peak_dbfs: float
    loudest_peak_dbfs: float
    outliers: tuple[str, ...]


@dataclass(frozen=True)
class CampaignProgress:
    """File-backed progress only; it never claims an audio take is approved."""

    total_takes: int
    captured_takes: int
    composite_takes: int
    captured_composite_takes: int
    calibration_status: str | None
    calibration_outliers: tuple[str, ...]
    calibration_technical_failures: int
    calibration_level_groups: tuple[CalibrationLevelGroup, ...]
    library_exists: bool
    quality_report_exists: bool
    quality_report_passed: bool
    quality_accepted: int
    quality_rejected: int
    quality_missing: int
    composite_quality_passed: bool
    drumgizmo_export_exists: bool
    drumgizmo_validation_passed: bool

    @property
    def missing_takes(self) -> int:
        return self.total_takes - self.captured_takes

    @property
    def missing_composite_takes(self) -> int:
        return self.composite_takes - self.captured_composite_takes

    @property
    def calibration_report_exists(self) -> bool:
        return self.calibration_status is not None

    @property
    def stage(self) -> str:
        if self.calibration_status is None:
            return "Ready for SD3 signal calibration"
        if self.calibration_status != "technical-pass-user-mix-review-required":
            return "SD3 calibration failed or is invalid — review before capture"
        if self.captured_takes < self.total_takes:
            return "Ready to capture" if self.captured_takes == 0 else "Capture can be resumed"
        if not self.quality_report_exists:
            return "Capture complete — run quality review"
        if not self.quality_report_passed:
            return "Capture quality failed or is stale — review before export"
        if self.captured_composite_takes < self.composite_takes or not self.composite_quality_passed:
            return "Quality approved — capture the simultaneous layered centers"
        if not self.drumgizmo_export_exists:
            return "Quality report available — export DrumGizmo when approved"
        if not self.drumgizmo_validation_passed:
            return "DrumGizmo export present — run its internal validation"
        return "DrumGizmo files validated — external host smoke test remains"


@dataclass(frozen=True)
class Sd3CaptureCampaign:
    """A portable campaign plus its deterministic drum-sampler session."""

    identifier: str
    sd3_preset: str
    midi_output: str
    audio_input: str
    channels: tuple[str, ...]
    rows: tuple[CaptureRow, ...]
    sd3_midi_map: str = "Kit_Metalcore_MidiMapping_Capture_V1"
    sd3_preset_file: str | None = None
    sd3_preset_sha256: str | None = None
    megakit_plan_file: str | None = None
    capture_session_sha256: str | None = None
    # Neutral SD3/DrumGizmo masters stay at the studio/live rate. DDrum4
    # preparation performs its own deliberate 44.1 kHz conversion later.
    sample_rate: int = 48000
    tail_ms: int = 5000
    license_statement: str = "SD3 capture for personal kit development"

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.identifier):
            raise ValueError("campaign ID must use a lowercase English identifier")
        if (not self.sd3_preset.strip() or not self.sd3_midi_map.strip()
                or not self.midi_output.strip() or not self.audio_input.strip()):
            raise ValueError("SD3 preset, MIDI map, MIDI output, and audio input are required")
        if not self.channels or any(not channel.strip() for channel in self.channels):
            raise ValueError("at least one named capture channel is required")
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("capture channels must be unique")
        if not self.rows:
            raise ValueError("add at least one SD3 articulation before creating a campaign")
        if (self.sd3_preset_file is None) != (self.sd3_preset_sha256 is None):
            raise ValueError("SD3 preset file and SHA-256 must be recorded together")
        if self.sd3_preset_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", self.sd3_preset_sha256):
            raise ValueError("SD3 preset SHA-256 must be 64 lowercase hexadecimal characters")
        if self.megakit_plan_file is not None and not self.megakit_plan_file.strip():
            raise ValueError("MegaKit plan file cannot be blank")
        if (self.capture_session_sha256 is not None
                and not re.fullmatch(r"[0-9a-f]{64}", self.capture_session_sha256)):
            raise ValueError("capture-session SHA-256 must be 64 lowercase hexadecimal characters")
        if self.sample_rate < 8000 or self.tail_ms < 0:
            raise ValueError("sample rate or tail is invalid")

    @property
    def total_takes(self) -> int:
        return sum(len(row.raw_filenames()) for row in self.rows)

    @property
    def expected_session_sha256(self) -> str:
        """Fingerprint the exact immutable MIDI/audio session contract."""
        if self.capture_session_sha256 is not None:
            return self.capture_session_sha256
        payload = json.dumps(self.session_document(), indent=2, sort_keys=True) + "\n"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def campaign_document(self) -> dict[str, object]:
        document: dict[str, object] = {
            "schema_version": 1,
            "kind": "sd3-capture-campaign",
            "id": self.identifier,
            "sd3_preset": self.sd3_preset,
            "sd3_midi_map": self.sd3_midi_map,
            "midi_output": self.midi_output,
            "audio_input": self.audio_input,
            "channels": list(self.channels),
            "sample_rate": self.sample_rate,
            "tail_ms": self.tail_ms,
            "license_statement": self.license_statement,
            "expected_take_count": self.total_takes,
            "capture_session_sha256": self.expected_session_sha256,
            "rows": [row.to_document() for row in self.rows],
            "outputs": {
                "session": "capture-session.json",
                "raw_directory": "raw-wav",
                "calibration_directory": "calibration-wav",
                "calibration_report": "reports/calibration.json",
                "library": "library.json",
                "quality_report": "reports/quality.json",
                "composite_directory": "drumgizmo-composite-wav",
                "composite_quality_report": "reports/composite-quality.json",
                "drumgizmo_directory": "drumgizmo-kit",
                "drumgizmo_report": "reports/drumgizmo-export.json",
                "drumgizmo_validation_report": "reports/drumgizmo-validation.json",
            },
        }
        if self.sd3_preset_file is not None:
            document["sd3_preset_file"] = self.sd3_preset_file
            document["sd3_preset_sha256"] = self.sd3_preset_sha256
        if self.megakit_plan_file is not None:
            document["megakit_plan_file"] = self.megakit_plan_file
        return document

    def session_document(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "capture-session",
            "midi_output": self.midi_output,
            "audio_input": self.audio_input,
            "channels": list(self.channels),
            "sample_rate": self.sample_rate,
            "preroll_ms": 100,
            "gate_ms": 100,
            "tail_ms": self.tail_ms,
            "cooldown_ms": 300,
            "requests": [{
                "instrument": row.instrument,
                "articulation": row.articulation,
                "note": row.note,
                "channel": row.channel,
                "controllers": [list(pair) for pair in row.controllers],
                "velocities": list(row.velocities),
                "repetitions": row.repetitions,
            } for row in self.rows],
        }

    def write_new(self, run_directory: Path) -> None:
        """Create a campaign without replacing a prior run or its session."""
        run_directory.mkdir(parents=True, exist_ok=True)
        campaign = run_directory / "campaign.json"
        session = run_directory / "capture-session.json"
        conflicts = [path.name for path in (campaign, session) if path.exists()]
        if conflicts:
            raise FileExistsError(f"campaign directory already contains {', '.join(conflicts)}")
        campaign.write_text(json.dumps(self.campaign_document(), indent=2, sort_keys=True) + "\n",
                            encoding="utf-8", newline="\n")
        session.write_text(json.dumps(self.session_document(), indent=2, sort_keys=True) + "\n",
                           encoding="utf-8", newline="\n")

    @classmethod
    def read(cls, run_directory: Path) -> "Sd3CaptureCampaign":
        document = json.loads((run_directory / "campaign.json").read_text(encoding="utf-8"))
        if document.get("schema_version") != 1 or document.get("kind") != "sd3-capture-campaign":
            raise ValueError("unsupported SD3 capture campaign")
        rows = document.get("rows")
        if not isinstance(rows, list):
            raise ValueError("campaign rows must be a list")
        try:
            return cls(
                identifier=document["id"], sd3_preset=document["sd3_preset"],
                sd3_midi_map=document.get("sd3_midi_map", "Kit_Metalcore_MidiMapping_Capture_V1"),
                midi_output=document["midi_output"], audio_input=document["audio_input"],
                channels=tuple(document["channels"]), sample_rate=document.get("sample_rate", 48000),
                tail_ms=document.get("tail_ms", 5000),
                sd3_preset_file=document.get("sd3_preset_file"),
                sd3_preset_sha256=document.get("sd3_preset_sha256"),
                megakit_plan_file=document.get("megakit_plan_file"),
                capture_session_sha256=document.get("capture_session_sha256"),
                license_statement=document.get("license_statement", "unassigned"),
                rows=tuple(CaptureRow(
                    instrument=row["instrument"], articulation=row["articulation"], note=row["note"],
                    channel=row.get("channel", 10), velocities=tuple(row["velocities"]),
                    repetitions=row["repetitions"],
                    controllers=tuple(tuple(pair) for pair in row.get("controllers", [])),
                    drumgizmo_note=row.get("drumgizmo_note"),
                ) for row in rows),
            )
        except (KeyError, TypeError) as error:
            raise ValueError("invalid SD3 capture campaign") from error

    def progress(self, run_directory: Path) -> CampaignProgress:
        session_path = run_directory / "capture-session.json"
        session_contract_current = (
            session_path.is_file()
            and hashlib.sha256(session_path.read_bytes()).hexdigest() == self.expected_session_sha256
        )
        raw_directory = run_directory / "raw-wav"
        captured = sum((raw_directory / filename).is_file()
                       for row in self.rows for filename in row.raw_filenames())
        calibration_report = run_directory / "reports" / "calibration.json"
        calibration_status: str | None = None
        calibration_outliers: tuple[str, ...] = ()
        calibration_technical_failures = 0
        calibration_level_groups: tuple[CalibrationLevelGroup, ...] = ()
        if calibration_report.is_file():
            try:
                calibration_document = json.loads(calibration_report.read_text(encoding="utf-8"))
                summary = calibration_document.get("summary")
                status = summary.get("status") if isinstance(summary, dict) else None
                calibration_status = status if isinstance(status, str) else "invalid"
                outliers = summary.get("relative_level_outliers") if isinstance(summary, dict) else None
                if isinstance(outliers, list) and all(isinstance(item, str) for item in outliers):
                    calibration_outliers = tuple(outliers)
                technical_failures = summary.get("technical_failures") if isinstance(summary, dict) else None
                if isinstance(technical_failures, int) and technical_failures >= 0:
                    calibration_technical_failures = technical_failures
                level_groups = summary.get("level_groups") if isinstance(summary, dict) else None
                if isinstance(level_groups, Mapping):
                    parsed_groups: list[CalibrationLevelGroup] = []
                    for name, details in sorted(level_groups.items()):
                        if not isinstance(name, str) or not isinstance(details, Mapping):
                            continue
                        group_outliers = details.get("outliers", [])
                        try:
                            if (not isinstance(group_outliers, list)
                                    or not all(isinstance(item, str) for item in group_outliers)):
                                raise ValueError
                            parsed_groups.append(CalibrationLevelGroup(
                                name=name,
                                articulations=int(details["articulations"]),
                                peak_span_db=float(details["peak_span_db"]),
                                quietest_peak_dbfs=float(details["quietest_peak_dbfs"]),
                                loudest_peak_dbfs=float(details["loudest_peak_dbfs"]),
                                outliers=tuple(group_outliers),
                            ))
                        except (KeyError, TypeError, ValueError):
                            continue
                    calibration_level_groups = tuple(parsed_groups)
                if calibration_status == "technical-pass-user-mix-review-required":
                    policy = calibration_document.get("policy")
                    rows = calibration_document.get("rows")
                    complete_v2 = (
                        calibration_document.get("format") == "sd3-calibration-report/v2"
                        and isinstance(policy, Mapping) and policy.get("only") == []
                        and isinstance(rows, list) and bool(rows)
                        and summary.get("articulations") == len(rows)
                        and summary.get("technical_failures") == 0
                        and isinstance(level_groups, Mapping) and bool(level_groups)
                        and len(calibration_level_groups) == len(level_groups)
                        and calibration_outliers == ()
                        and all(not group.outliers for group in calibration_level_groups)
                    )
                    if not complete_v2:
                        calibration_status = "invalid-v2"
                if (not session_contract_current
                        or calibration_document.get("session_sha256")
                        != hashlib.sha256(session_path.read_bytes()).hexdigest()):
                    calibration_status = "stale-session-contract"
                preset = calibration_document.get("preset")
                if self.sd3_preset_sha256 is not None and (
                    not isinstance(preset, dict)
                    or preset.get("sha256") != self.sd3_preset_sha256
                    or preset.get("loaded_confirmed") is not True
                ):
                    calibration_status = "stale-preset"
            except (OSError, json.JSONDecodeError):
                calibration_status = "invalid"
        composite_filenames: tuple[str, ...] = ()
        if self.megakit_plan_file is not None:
            try:
                composite_filenames = drumgizmo_composite_filenames(Path(self.megakit_plan_file))
            except (OSError, ValueError):
                composite_filenames = ()
        composite_directory = run_directory / "drumgizmo-composite-wav"
        captured_composites = sum((composite_directory / filename).is_file()
                                  for filename in composite_filenames)
        composite_quality_passed = False
        composite_quality_report = run_directory / "reports" / "composite-quality.json"
        if not composite_filenames:
            composite_quality_passed = True
        elif composite_quality_report.is_file():
            try:
                composite_quality = json.loads(composite_quality_report.read_text(encoding="utf-8"))
                composite_summary = composite_quality.get("summary")
                composite_records = composite_quality.get("takes")
                indexed_composites: dict[str, Mapping[str, object]] = {}
                if isinstance(composite_records, list):
                    for record in composite_records:
                        if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
                            indexed_composites = {}
                            break
                        name = Path(str(record["path"])).name
                        if name in indexed_composites:
                            indexed_composites = {}
                            break
                        indexed_composites[name] = record
                plan_path = Path(self.megakit_plan_file) if self.megakit_plan_file is not None else None
                session_path = run_directory / "capture-session.json"
                composite_hashes_match = (
                    set(indexed_composites) == set(composite_filenames)
                    and all(
                        (composite_directory / name).is_file()
                        and isinstance(indexed_composites[name].get("facts"), Mapping)
                        and indexed_composites[name]["facts"].get("sha256")
                        == hashlib.sha256((composite_directory / name).read_bytes()).hexdigest()
                        for name in composite_filenames
                    )
                )
                composite_quality_passed = (
                    composite_quality.get("kind") == "drumgizmo-composite-quality-report"
                    and session_contract_current
                    and composite_quality.get("session_sha256") == hashlib.sha256(session_path.read_bytes()).hexdigest()
                    and plan_path is not None and plan_path.is_file()
                    and composite_quality.get("megakit_plan_sha256") == hashlib.sha256(plan_path.read_bytes()).hexdigest()
                    and isinstance(composite_summary, Mapping)
                    and composite_summary.get("accepted") == len(composite_filenames)
                    and composite_summary.get("rejected") == 0
                    and composite_summary.get("missing") == 0
                    and composite_summary.get("round_robin_duplicate_cells") == 0
                    and composite_hashes_match
                )
            except (OSError, json.JSONDecodeError):
                pass
        library_path = run_directory / "library.json"
        quality_report_path = run_directory / "reports" / "quality.json"
        quality_report_exists = quality_report_path.is_file()
        quality_report_passed = False
        quality_accepted = quality_rejected = quality_missing = 0
        if quality_report_exists and library_path.is_file():
            try:
                quality_document = json.loads(quality_report_path.read_text(encoding="utf-8"))
                quality_summary = quality_document.get("summary")
                if isinstance(quality_summary, Mapping):
                    quality_accepted = int(quality_summary.get("accepted", 0))
                    quality_rejected = int(quality_summary.get("rejected", 0))
                    quality_missing = int(quality_summary.get("missing", 0))
                    quality_report_passed = (
                        quality_document.get("kind") == "capture-quality-report"
                        and session_contract_current
                        and quality_document.get("library_sha256") == hashlib.sha256(library_path.read_bytes()).hexdigest()
                        and (run_directory / "capture-session.json").is_file()
                        and quality_document.get("session_sha256")
                        == hashlib.sha256((run_directory / "capture-session.json").read_bytes()).hexdigest()
                        and quality_accepted == self.total_takes
                        and quality_rejected == 0
                        and quality_missing == 0
                        and quality_summary.get("round_robin_duplicate_cells") == 0
                    )
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        drumgizmo_validation_passed = False
        drumgizmo_validation_report = run_directory / "reports" / "drumgizmo-validation.json"
        if drumgizmo_validation_report.is_file():
            try:
                validation_document = json.loads(drumgizmo_validation_report.read_text(encoding="utf-8"))
                validation_files = validation_document.get("files")
                kit_directory = run_directory / "drumgizmo-kit"
                actual_files = {path.relative_to(kit_directory).as_posix(): path
                                for path in kit_directory.rglob("*") if path.is_file()}
                declared_files = {
                    item.get("path"): item for item in validation_files
                    if isinstance(item, Mapping) and isinstance(item.get("path"), str)
                } if isinstance(validation_files, list) else {}
                hashes_match = (
                    set(actual_files) == set(declared_files)
                    and all(
                        declared_files[name].get("bytes") == path.stat().st_size
                        and declared_files[name].get("sha256") == hashlib.sha256(path.read_bytes()).hexdigest()
                        for name, path in actual_files.items()
                    )
                )
                drumgizmo_validation_passed = (
                    validation_document.get("kind") == "drumgizmo-kit-validation-report"
                    and validation_document.get("status") == "pass"
                    and bool(declared_files) and hashes_match
                )
            except (OSError, json.JSONDecodeError):
                pass
        return CampaignProgress(
            total_takes=self.total_takes,
            captured_takes=captured,
            composite_takes=len(composite_filenames),
            captured_composite_takes=captured_composites,
            calibration_status=calibration_status,
            calibration_outliers=calibration_outliers,
            calibration_technical_failures=calibration_technical_failures,
            calibration_level_groups=calibration_level_groups,
            library_exists=library_path.is_file(),
            quality_report_exists=quality_report_exists,
            quality_report_passed=quality_report_passed,
            quality_accepted=quality_accepted,
            quality_rejected=quality_rejected,
            quality_missing=quality_missing,
            composite_quality_passed=composite_quality_passed,
            drumgizmo_export_exists=(run_directory / "drumgizmo-kit").is_dir(),
            drumgizmo_validation_passed=drumgizmo_validation_passed,
        )


def drumgizmo_composite_filenames(path: Path) -> tuple[str, ...]:
    """Return the exact simultaneous layer-take filenames declared by a MegaKit plan."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"cannot read SD3 MegaKit plan: {path}") from error
    if not isinstance(document, Mapping) or document.get("kind") != "sd3-megakit-plan":
        raise ValueError("unsupported SD3 MegaKit plan")
    rows = {(row.instrument, row.articulation): row for row in capture_rows_from_megakit_plan(path)}
    specifications = document.get("drumgizmo_composites", [])
    if not isinstance(specifications, list):
        raise ValueError("drumgizmo_composites must be a list")
    filenames: list[str] = []
    seen: set[tuple[str, str]] = set()
    for specification in specifications:
        if not isinstance(specification, Mapping):
            raise ValueError("each DrumGizmo composite must be an object")
        target = specification.get("target")
        if not isinstance(target, str) or target.count(".") != 1:
            raise ValueError("DrumGizmo composite target must be instrument.articulation")
        key = tuple(target.split(".", 1))
        if key in seen:
            raise ValueError(f"duplicate DrumGizmo composite target: {target}")
        seen.add(key)
        row = rows.get(key)
        if row is None:
            raise ValueError(f"DrumGizmo composite target is not a captured row: {target}")
        filenames.extend(
            f"{row.instrument}__{row.articulation}__v{velocity:03d}__rr{repetition:02d}_composite.wav"
            for velocity in row.velocities for repetition in range(1, row.repetitions + 1)
        )
    return tuple(filenames)


def fingerprint_sd3_preset(path: Path) -> tuple[str, str]:
    """Return the resolved local preset path and its immutable campaign fingerprint."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.suffix.lower() != ".sd3p":
        raise ValueError(f"SD3 preset file does not exist or is not .sd3p: {resolved}")
    return str(resolved), hashlib.sha256(resolved.read_bytes()).hexdigest()


def capture_rows_from_megakit_plan(path: Path) -> tuple[CaptureRow, ...]:
    """Build the exact raw-capture grid from a reviewed SD3 MegaKit plan.

    Rows marked ``capture: false`` deliberately share the audio of another
    logical target.  They remain in the renderer map but must not consume
    duplicate SD3 takes or DrumGizmo source files.
    """
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"cannot read SD3 MegaKit plan: {path}") from error
    if not isinstance(document, Mapping) or document.get("kind") != "sd3-megakit-plan":
        raise ValueError("unsupported SD3 MegaKit plan")
    velocity_sets = document.get("velocity_sets")
    articulations = document.get("articulations")
    if not isinstance(velocity_sets, Mapping) or not isinstance(articulations, list):
        raise ValueError("SD3 MegaKit plan needs velocity_sets and articulations")
    rows: list[CaptureRow] = []
    notes: set[int] = set()
    for item in articulations:
        if not isinstance(item, Mapping) or item.get("capture") is not True:
            continue
        logical, note, velocity_name, repetitions = item.get("logical"), item.get("note"), item.get("velocities"), item.get("rr")
        velocities = velocity_sets.get(velocity_name) if isinstance(velocity_name, str) else None
        if (not isinstance(logical, str) or not isinstance(note, int) or not isinstance(repetitions, int)
                or not isinstance(velocities, list) or not all(isinstance(value, int) for value in velocities)):
            raise ValueError(f"invalid capture articulation in SD3 MegaKit plan: {logical!r}")
        if logical.count(".") != 1:
            raise ValueError(f"capture logical target must be instrument.articulation: {logical!r}")
        instrument, articulation = logical.split(".", 1)
        variants = item.get("capture_variants")
        if variants is not None:
            if not isinstance(variants, list) or not variants:
                raise ValueError(f"capture_variants must be a non-empty list for {logical!r}")
            for variant in variants:
                if not isinstance(variant, Mapping):
                    raise ValueError(f"invalid capture variant for {logical!r}")
                variant_name = variant.get("articulation")
                controllers = variant.get("controllers")
                drumgizmo_note = variant.get("drumgizmo_note")
                if (not isinstance(variant_name, str) or not isinstance(controllers, list)
                        or not all(isinstance(pair, list) and len(pair) == 2
                                   and all(isinstance(value, int) for value in pair) for pair in controllers)
                        or not isinstance(drumgizmo_note, int)):
                    raise ValueError(f"invalid capture variant for {logical!r}")
                rows.append(CaptureRow(
                    instrument, variant_name, note, tuple(velocities), repetitions,
                    controllers=tuple((pair[0], pair[1]) for pair in controllers),
                    drumgizmo_note=drumgizmo_note,
                ))
        else:
            if note in notes:
                raise ValueError(f"SD3 MegaKit plan captures duplicate MIDI note {note}")
            notes.add(note)
            rows.append(CaptureRow(instrument, articulation, note, tuple(velocities), repetitions))
    if not rows:
        raise ValueError("SD3 MegaKit plan has no capture rows")
    return tuple(rows)


STARTER_ROWS: tuple[CaptureRow, ...] = (
    CaptureRow("kick", "head", 36, (24, 40, 56, 72, 88, 104, 120), 4),
    CaptureRow("snare_main", "head", 38, (24, 40, 56, 72, 88, 104, 120), 4),
    CaptureRow("snare_main", "rimshot", 40, (40, 64, 88, 112), 3),
    CaptureRow("hi_hat", "closed", 42, (32, 56, 80, 104, 120), 3),
    CaptureRow("hi_hat", "open", 46, (32, 56, 80, 104, 120), 3),
    CaptureRow("tom_1", "head", 48, (24, 48, 72, 96, 120), 3),
    CaptureRow("tom_2", "head", 45, (24, 48, 72, 96, 120), 3),
    CaptureRow("tom_3", "head", 43, (24, 48, 72, 96, 120), 3),
    CaptureRow("crash_1", "bow", 49, (32, 56, 80, 104, 120), 3),
    CaptureRow("ride", "bow", 51, (32, 56, 80, 104, 120), 3),
    CaptureRow("ride", "bell", 53, (40, 64, 88, 112), 3),
)


# Add this set to an existing approved acoustic campaign.  It is intentionally
# the capture list, not the entire SD3 runtime map: note 49 reuses the captured
# industrial/trap snare through routing and therefore has no duplicate raw row.
METALCORE_ELECTRONIC_V1_ADDITIONS: tuple[CaptureRow, ...] = (
    CaptureRow("kick_dnb", "head", 26, (24, 48, 72, 96, 120), 2),
    CaptureRow("kick_industrial", "head", 27, (24, 48, 72, 96, 120), 2),
    CaptureRow("kick_808", "head", 28, (24, 48, 72, 96, 120), 2),
    CaptureRow("snare_dnb", "head", 47, (24, 48, 72, 96, 120), 2),
    CaptureRow("snare_industrial_trap", "head", 48, (24, 48, 72, 96, 120), 2),
    CaptureRow("clap_main", "hit", 50, (40, 64, 88, 112), 2),
    CaptureRow("electronic_rim_click", "hit", 51, (40, 64, 88, 112), 1),
    CaptureRow("stack_acoustic", "hit", 85, (40, 64, 88, 112), 2),
    CaptureRow("electronic_hat", "closed", 68, (40, 64, 88, 112), 2),
    CaptureRow("electronic_hat", "open", 69, (40, 64, 88, 112), 2),
    CaptureRow("metallic_hit", "hit", 88, (40, 64, 88, 112), 1),
    CaptureRow("glitch_noise", "hit", 89, (40, 64, 88, 112), 1),
    CaptureRow("electronic_tom", "low", 90, (40, 64, 88, 112), 2),
    CaptureRow("cowbell", "hit", 92, (40, 64, 88, 112), 1),
    CaptureRow("woodblock", "hit", 93, (40, 64, 88, 112), 1),
)
