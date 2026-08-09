"""Normalized MIDI-independent event vocabulary for the hybrid drum kit."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


EventKind = Literal["hit", "controller", "choke", "program_change"]


@dataclass(frozen=True)
class LogicalEvent:
    """An event after source-specific MIDI has been interpreted.

    The event intentionally does not contain a source module MIDI note. Source
    MIDI belongs to a wiring profile; target MIDI belongs to a target profile.
    """

    instrument: str
    articulation: str
    kind: EventKind = "hit"
    velocity: int | None = None
    position: float | None = None
    openness: float | None = None

    def __post_init__(self) -> None:
        if not self.instrument or not self.articulation:
            raise ValueError("instrument and articulation are required")
        if self.velocity is not None and not 1 <= self.velocity <= 127:
            raise ValueError("velocity must be 1..127")
        for name, value in (("position", self.position), ("openness", self.openness)):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be 0.0..1.0")
