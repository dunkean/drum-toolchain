"""Offline byte-level differential analysis; semantic labels are never guessed."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .sysex import parse_stream


@dataclass(frozen=True)
class ByteDifference:
    offset: int
    before: int | None
    after: int | None


def diff_bytes(before: bytes, after: bytes) -> tuple[ByteDifference, ...]:
    return tuple(ByteDifference(offset, before[offset] if offset < len(before) else None, after[offset] if offset < len(after) else None)
                 for offset in range(max(len(before), len(after)))
                 if (before[offset] if offset < len(before) else None) != (after[offset] if offset < len(after) else None))


def diff_files(before_path: Path, after_path: Path) -> tuple[ByteDifference, ...]:
    before, after = before_path.read_bytes(), after_path.read_bytes()
    parse_stream(before)
    parse_stream(after)
    return diff_bytes(before, after)


def render_diff(differences: tuple[ByteDifference, ...]) -> str:
    if not differences:
        return "No byte differences.\n"
    lines = ["Protocol field interpretations are intentionally unavailable until validated."]
    for difference in differences:
        before = "--" if difference.before is None else f"0x{difference.before:02X}"
        after = "--" if difference.after is None else f"0x{difference.after:02X}"
        delta = "n/a" if difference.before is None or difference.after is None else f"{difference.after - difference.before:+d}"
        lines.extend((f"Offset 0x{difference.offset:06X}:", f"    A = {before}", f"    B = {after}", f"    delta = {delta}"))
    return "\n".join(lines) + "\n"
