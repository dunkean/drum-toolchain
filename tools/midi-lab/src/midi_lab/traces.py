"""Portable JSON Lines MIDI traces for learn and replay tests."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class TraceEvent:
    timestamp_ms: int
    message_type: str
    channel: int | None = None
    data1: int | None = None
    data2: int | None = None

    def __post_init__(self) -> None:
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")
        if self.channel is not None and not 1 <= self.channel <= 16:
            raise ValueError("channel must be 1..16")
        for name, value in (("data1", self.data1), ("data2", self.data2)):
            if value is not None and not 0 <= value <= 127:
                raise ValueError(f"{name} must be 0..127")


@dataclass(frozen=True)
class MidiTrace:
    source: str
    events: tuple[TraceEvent, ...]

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps({"schema_version": 1, "source": self.source}, sort_keys=True) + "\n")
            for event in self.events:
                output.write(json.dumps(asdict(event), sort_keys=True) + "\n")

    @classmethod
    def read(cls, path: Path) -> "MidiTrace":
        with path.open(encoding="utf-8") as source:
            records = [json.loads(line) for line in source if line.strip()]
        if not records or records[0].get("schema_version") != 1:
            raise ValueError("unsupported or missing trace header")
        name = records[0].get("source")
        if not isinstance(name, str) or not name:
            raise ValueError("trace source is required")
        return cls(name, tuple(TraceEvent(**record) for record in records[1:]))


def trace(source: str, events: Iterable[TraceEvent]) -> MidiTrace:
    return MidiTrace(source, tuple(events))
