"""Reproducible, hardware-safe SD3 capture campaign records.

The Control Center owns the operator-facing campaign document.  It writes the
same ``capture-session`` JSON consumed by drum-sampler, but never opens MIDI or
audio devices itself.
"""
from __future__ import annotations

from dataclasses import dataclass
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
class CampaignProgress:
    """File-backed progress only; it never claims an audio take is approved."""

    total_takes: int
    captured_takes: int
    library_exists: bool
    quality_report_exists: bool
    drumgizmo_export_exists: bool

    @property
    def missing_takes(self) -> int:
        return self.total_takes - self.captured_takes

    @property
    def stage(self) -> str:
        if self.captured_takes < self.total_takes:
            return "Ready to capture" if self.captured_takes == 0 else "Capture can be resumed"
        if not self.quality_report_exists:
            return "Capture complete — run quality review"
        if not self.drumgizmo_export_exists:
            return "Quality report available — export DrumGizmo when approved"
        return "DrumGizmo export present — review and validate it"


@dataclass(frozen=True)
class Sd3CaptureCampaign:
    """A portable campaign plus its deterministic drum-sampler session."""

    identifier: str
    sd3_preset: str
    midi_output: str
    audio_input: str
    channels: tuple[str, ...]
    rows: tuple[CaptureRow, ...]
    sample_rate: int = 44100
    tail_ms: int = 5000
    license_statement: str = "SD3 capture for personal kit development"

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.identifier):
            raise ValueError("campaign ID must use a lowercase English identifier")
        if not self.sd3_preset.strip() or not self.midi_output.strip() or not self.audio_input.strip():
            raise ValueError("SD3 preset, MIDI output, and audio input are required")
        if not self.channels or any(not channel.strip() for channel in self.channels):
            raise ValueError("at least one named capture channel is required")
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("capture channels must be unique")
        if not self.rows:
            raise ValueError("add at least one SD3 articulation before creating a campaign")
        if self.sample_rate < 8000 or self.tail_ms < 0:
            raise ValueError("sample rate or tail is invalid")

    @property
    def total_takes(self) -> int:
        return sum(len(row.raw_filenames()) for row in self.rows)

    def campaign_document(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "sd3-capture-campaign",
            "id": self.identifier,
            "sd3_preset": self.sd3_preset,
            "midi_output": self.midi_output,
            "audio_input": self.audio_input,
            "channels": list(self.channels),
            "sample_rate": self.sample_rate,
            "tail_ms": self.tail_ms,
            "license_statement": self.license_statement,
            "expected_take_count": self.total_takes,
            "rows": [row.to_document() for row in self.rows],
            "outputs": {
                "session": "capture-session.json",
                "raw_directory": "raw-wav",
                "library": "library.json",
                "quality_report": "reports/quality.json",
                "drumgizmo_directory": "drumgizmo-kit",
                "drumgizmo_report": "reports/drumgizmo-export.json",
            },
        }

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
        campaign.write_text(json.dumps(self.campaign_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        session.write_text(json.dumps(self.session_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

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
                midi_output=document["midi_output"], audio_input=document["audio_input"],
                channels=tuple(document["channels"]), sample_rate=document.get("sample_rate", 44100),
                tail_ms=document.get("tail_ms", 5000),
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
        raw_directory = run_directory / "raw-wav"
        captured = sum((raw_directory / filename).is_file()
                       for row in self.rows for filename in row.raw_filenames())
        return CampaignProgress(
            total_takes=self.total_takes,
            captured_takes=captured,
            library_exists=(run_directory / "library.json").is_file(),
            quality_report_exists=(run_directory / "reports" / "quality.json").is_file(),
            drumgizmo_export_exists=(run_directory / "drumgizmo-kit").is_dir(),
        )


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
