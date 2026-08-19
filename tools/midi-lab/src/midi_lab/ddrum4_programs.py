"""Exact DDrum4 SE kit and palette Program Change contract."""
from __future__ import annotations

from dataclasses import dataclass


_PALETTE_RANGES = {
    "kick": (100, 105),
    "snare": (106, 111),
    "toms": (112, 117),
    "percussion": (118, 123),
}


@dataclass(frozen=True)
class Ddrum4Program:
    program: int
    kind: str
    group: str | None = None
    selection: int | None = None

    @property
    def label(self) -> str:
        if self.kind == "user_kit":
            return f"P.{self.selection}"
        if self.kind == "factory_kit":
            return f"F.{self.selection}"
        if self.kind == "palette_mode":
            return "PAL"
        if self.kind == "palette_select":
            return f"{self.group} palette {self.selection}"
        if self.kind == "palette_revert":
            return f"{self.group} palette off"
        return f"unsupported PC {self.program}"


def decode_ddrum4_program(program: int) -> Ddrum4Program:
    if not 0 <= program <= 127:
        raise ValueError("MIDI Program Change must be 0..127")
    if program <= 25:
        return Ddrum4Program(program, "user_kit", selection=program + 1)
    if program <= 98:
        return Ddrum4Program(program, "factory_kit", selection=program + 1)
    if program == 99:
        return Ddrum4Program(program, "palette_mode")
    for group, (first, revert) in _PALETTE_RANGES.items():
        if first <= program < revert:
            return Ddrum4Program(program, "palette_select", group, program - first + 1)
        if program == revert:
            return Ddrum4Program(program, "palette_revert", group)
    return Ddrum4Program(program, "unsupported")


def program_for_kit(kit: int) -> int:
    """Return the zero-based MIDI PC for panel kit P.1..F.99."""
    if not 1 <= kit <= 99:
        raise ValueError("DDrum4 kit must be 1..99")
    return kit - 1


def program_for_palette(group: str, selection: int | None) -> int:
    """Return a palette-selection PC; None reverts that group to its kit."""
    try:
        first, revert = _PALETTE_RANGES[group.lower()]
    except KeyError as error:
        raise ValueError(f"unknown DDrum4 palette group: {group}") from error
    if selection is None:
        return revert
    if not 1 <= selection <= 5:
        raise ValueError("DDrum4 palette selection must be 1..5")
    return first + selection - 1
