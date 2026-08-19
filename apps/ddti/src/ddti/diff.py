"""Offline byte-level differential analysis; semantic labels are never guessed."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .protocol import DDTiDump, decode_dump
from .sysex import parse_stream


@dataclass(frozen=True)
class ByteDifference:
    offset: int
    before: int | None
    after: int | None
    observed_packet_family: int | None = None
    observed_packet_index: int | None = None
    packet_byte_offset: int | None = None


def diff_bytes(before: bytes, after: bytes) -> tuple[ByteDifference, ...]:
    return tuple(ByteDifference(offset, before[offset] if offset < len(before) else None, after[offset] if offset < len(after) else None)
                 for offset in range(max(len(before), len(after)))
                 if (before[offset] if offset < len(before) else None) != (after[offset] if offset < len(after) else None))


def _packet_context(dump: DDTiDump, offset: int) -> tuple[int | None, int | None, int | None]:
    position = 0
    for packet in dump.packets:
        if position <= offset < position + len(packet.raw):
            return packet.record_type, packet.record_index, offset - position
        position += len(packet.raw)
    return None, None, None


def diff_ddti_bytes(before: bytes, after: bytes) -> tuple[ByteDifference, ...]:
    """Diff two complete DDTi streams with their observed packet context."""
    # Keep standard SysEx validation first so failures remain clear for truncated files.
    parse_stream(before)
    parse_stream(after)
    before_dump = decode_dump(before)
    decode_dump(after)
    return tuple(
        ByteDifference(
            difference.offset,
            difference.before,
            difference.after,
            *_packet_context(before_dump, difference.offset),
        )
        for difference in diff_bytes(before, after)
    )


def diff_files(before_path: Path, after_path: Path) -> tuple[ByteDifference, ...]:
    return diff_ddti_bytes(before_path.read_bytes(), after_path.read_bytes())


def _observed_position_label(difference: ByteDifference) -> str | None:
    if difference.observed_packet_family is None or difference.packet_byte_offset is None:
        return None
    byte = difference.packet_byte_offset
    labels = {
        0: "SysEx start",
        4: "observed device byte",
        5: "observed command byte",
        8: "declared-length byte",
        9: "record family",
        10: "record index",
    }
    if 1 <= byte <= 3:
        position = f"manufacturer ID byte {byte}"
    elif byte in (6, 7):
        position = f"observed address/reserved byte {byte - 5}"
    elif (difference.observed_packet_family == 0x01 and byte == 77) or (difference.observed_packet_family == 0x02 and byte == 17):
        position = "SysEx end"
    else:
        position = labels.get(byte, f"opaque body byte +0x{byte - 11:02X}" if byte >= 11 else f"packet byte 0x{byte:02X}")
    return (
        f"Observed packet family 0x{difference.observed_packet_family:02X} / "
        f"index {difference.observed_packet_index}, {position}"
    )


def render_diff(differences: tuple[ByteDifference, ...]) -> str:
    if not differences:
        return "No byte differences.\n"
    lines = ["Protocol field interpretations are intentionally unavailable until validated."]
    for difference in differences:
        before = "--" if difference.before is None else f"0x{difference.before:02X}"
        after = "--" if difference.after is None else f"0x{difference.after:02X}"
        delta = "n/a" if difference.before is None or difference.after is None else f"{difference.after - difference.before:+d}"
        lines.extend((f"Offset 0x{difference.offset:06X}:", f"    A = {before}", f"    B = {after}", f"    delta = {delta}"))
        if context := _observed_position_label(difference):
            lines.append(f"    Structural context: {context}")
    return "\n".join(lines) + "\n"
