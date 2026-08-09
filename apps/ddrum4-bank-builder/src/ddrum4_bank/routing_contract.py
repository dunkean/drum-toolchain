"""Versioned resolved ddrum4 routing contracts consumed by firmware tooling."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ContractRoute:
    identifier: str
    source: str
    input_note: int
    output_note: int
    sound_id: str
    position: int | None = None
    input_velocity_min: int = 1
    input_velocity_max: int = 127
    output_velocity_min: int = 1
    output_velocity_max: int = 127

    def __post_init__(self) -> None:
        if not self.identifier or not self.source or not self.sound_id:
            raise ValueError("route identifier, source, and sound_id are required")
        for name, value, low, high in (
            ("input_note", self.input_note, 0, 127),
            ("output_note", self.output_note, 0, 127),
            ("input_velocity_min", self.input_velocity_min, 1, 127),
            ("input_velocity_max", self.input_velocity_max, 1, 127),
            ("output_velocity_min", self.output_velocity_min, 1, 127),
            ("output_velocity_max", self.output_velocity_max, 1, 127),
        ):
            if not low <= value <= high:
                raise ValueError(f"{name} must be {low}..{high}")
        if self.position is not None and not 1 <= self.position <= 8:
            raise ValueError("position must be 1..8")

    def to_document(self) -> dict[str, Any]:
        document = asdict(self)
        document["velocity"] = {
            "input_min": document.pop("input_velocity_min"),
            "input_max": document.pop("input_velocity_max"),
            "output_min": document.pop("output_velocity_min"),
            "output_max": document.pop("output_velocity_max"),
        }
        return document


@dataclass(frozen=True)
class RoutingContract:
    bank_id: str
    ddrum_output_channel: int
    sources: dict[str, int]
    hihat: dict[str, Any]
    routes: tuple[ContractRoute, ...]

    def __post_init__(self) -> None:
        if not self.bank_id or not 1 <= self.ddrum_output_channel <= 16:
            raise ValueError("bank_id and a ddrum output channel in 1..16 are required")
        if not self.sources or any(not name or not 1 <= channel <= 16 for name, channel in self.sources.items()):
            raise ValueError("sources must map names to MIDI channels in 1..16")
        if len({(route.source, route.input_note) for route in self.routes}) != len(self.routes):
            raise ValueError("routing contract contains duplicate source/note routes")
        if any(route.source not in self.sources for route in self.routes):
            raise ValueError("routing contract references an unknown source")

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "ddrum4-routing-contract",
            "bank_id": self.bank_id,
            "midi": {
                "ddrum_output_channel": self.ddrum_output_channel,
                "sources": {name: {"channel": channel} for name, channel in sorted(self.sources.items())},
            },
            "hihat": self.hihat,
            "routes": [route.to_document() for route in self.routes],
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
