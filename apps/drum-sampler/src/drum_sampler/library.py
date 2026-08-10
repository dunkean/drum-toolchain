"""Versioned neutral sample-library records; raw audio is never overwritten."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path

from .session import PlannedTake


@dataclass(frozen=True)
class SampleTake:
    instrument: str
    articulation: str
    note: int
    channel: int
    velocity: int
    repetition: int
    raw_file: str
    prepared_file: str | None = None
    sample_rate: int | None = None
    channels: tuple[str, ...] = ()
    frames: int | None = None
    peak_dbfs: float | None = None
    rms_dbfs: float | None = None
    clipped: bool | None = None
    sha256: str | None = None
    capture_duration_ms: int | None = None
    source: str = "unassigned"
    license_statement: str = "unassigned"
    processing_history: tuple[str, ...] = ()
    status: str = "planned"

    @classmethod
    def from_planned_take(cls, take: PlannedTake) -> "SampleTake":
        return cls(
            instrument=take.request.instrument,
            articulation=take.request.articulation,
            note=take.request.note,
            channel=take.request.channel,
            velocity=take.velocity,
            repetition=take.repetition,
            raw_file=take.raw_filename(),
        )


@dataclass(frozen=True)
class SampleLibrary:
    identifier: str
    channel_layout: tuple[str, ...]
    takes: tuple[SampleTake, ...]

    def to_document(self) -> dict[str, object]:
        takes: list[dict[str, object]] = []
        for take in self.takes:
            record = asdict(take)
            record["channels"] = list(take.channels)
            record["processing_history"] = list(take.processing_history)
            takes.append(record)
        return {
            "schema_version": 1,
            "kind": "neutral-sample-library",
            "id": self.identifier,
            "channel_layout": list(self.channel_layout),
            "takes": takes,
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> "SampleLibrary":
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("schema_version") != 1 or document.get("kind") != "neutral-sample-library":
            raise ValueError("unsupported neutral sample-library document")
        identifier = document.get("id")
        layout = document.get("channel_layout")
        takes = document.get("takes")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("sample-library id is required")
        if not isinstance(layout, list) or not all(isinstance(item, str) and item for item in layout):
            raise ValueError("sample-library channel_layout must be a string list")
        if not isinstance(takes, list):
            raise ValueError("sample-library takes must be a list")
        parsed_takes: list[SampleTake] = []
        for take in takes:
            if not isinstance(take, dict):
                raise ValueError("each sample-library take must be an object")
            take_data = dict(take)
            channels = take_data.get("channels", [])
            if not isinstance(channels, list) or not all(isinstance(item, str) and item for item in channels):
                raise ValueError("sample-library take channels must be a string list")
            take_data["channels"] = tuple(channels)
            history = take_data.get("processing_history", [])
            if not isinstance(history, list) or not all(isinstance(item, str) and item for item in history):
                raise ValueError("sample-library processing_history must be a string list")
            take_data["processing_history"] = tuple(history)
            parsed_takes.append(SampleTake(**take_data))
        return cls(identifier, tuple(layout), tuple(parsed_takes))


def library_from_plan(identifier: str, channel_layout: tuple[str, ...], takes: tuple[PlannedTake, ...]) -> SampleLibrary:
    if not identifier:
        raise ValueError("sample-library id is required")
    return SampleLibrary(identifier, channel_layout, tuple(
        replace(SampleTake.from_planned_take(take), channels=channel_layout)
        for take in takes
    ))


def merge_libraries(identifier: str, sources: tuple[tuple[SampleLibrary, str], ...]) -> SampleLibrary:
    """Merge independent capture manifests without relocating their audio.

    Each prefix is relative to the future shared ``audio_root`` and becomes
    part of every non-absolute raw/prepared file reference. This preserves the
    provenance-rich neutral manifests while making a merged export portable.
    """
    if not identifier or not sources:
        raise ValueError("identifier and at least one source library are required")
    layout = sources[0][0].channel_layout
    merged: list[SampleTake] = []
    for library, prefix in sources:
        if library.channel_layout != layout:
            raise ValueError("all merged libraries must use the same channel layout")
        normalized_prefix = Path(prefix)
        if normalized_prefix.is_absolute() or str(normalized_prefix) in {"", "."}:
            raise ValueError("each library prefix must be a non-empty relative path")
        for take in library.takes:
            def prefixed(value: str | None) -> str | None:
                if value is None or Path(value).is_absolute():
                    return value
                return (normalized_prefix / value).as_posix()
            merged.append(replace(take, raw_file=prefixed(take.raw_file) or take.raw_file,
                                  prepared_file=prefixed(take.prepared_file)))
    return SampleLibrary(identifier, layout, tuple(merged))
