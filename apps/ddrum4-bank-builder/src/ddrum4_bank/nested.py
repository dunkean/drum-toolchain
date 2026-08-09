"""Pure validation for nested ddrum4 articulation layouts."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NestedRoute:
    articulation: str
    position: int
    sample_slots: int
    layers: int
    priority: int


@dataclass(frozen=True)
class NestedSound:
    identifier: str
    note_p: int
    routes: tuple[NestedRoute, ...]

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.note_p not in (1, 2, 4, 8):
            errors.append("note_p must be one of 1, 2, 4, 8")
        positions = [route.position for route in self.routes]
        if len(positions) != len(set(positions)):
            errors.append("nested positions must be unique")
        if any(not 1 <= position <= self.note_p for position in positions):
            errors.append("nested position exceeds note_p")
        if sum(route.sample_slots for route in self.routes) > 10:
            errors.append("nested sound exceeds ten sample slots")
        if sum(route.layers for route in self.routes) > 10:
            errors.append("nested sound exceeds ten layers")
        return tuple(errors)
