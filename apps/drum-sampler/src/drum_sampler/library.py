"""Versioned neutral sample-library records; raw audio is never overwritten."""
from __future__ import annotations

from dataclasses import asdict, dataclass
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
        return {
            "schema_version": 1,
            "kind": "neutral-sample-library",
            "id": self.identifier,
            "channel_layout": list(self.channel_layout),
            "takes": [asdict(take) for take in self.takes],
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
    return SampleLibrary(identifier, channel_layout, tuple(SampleTake.from_planned_take(take) for take in takes))
