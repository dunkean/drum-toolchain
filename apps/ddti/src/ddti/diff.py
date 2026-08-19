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
    elif difference.observed_packet_family == 0x01 and 11 <= byte < 71:
        zone_record, field = divmod(byte - 11, 3)
        input_number = zone_record // 2 + 1
        zone = "Tip" if zone_record % 2 == 0 else "Ring"
        position = {
            0: f"Kit {difference.observed_packet_index + 1} / Input {input_number} {zone} MIDI Channel (CONFIRMED; stored channel-1)",
            1: f"Kit {difference.observed_packet_index + 1} / Input {input_number} {zone} MIDI Note (CONFIRMED)",
            2: f"Kit {difference.observed_packet_index + 1} / Input {input_number} {zone} companion byte (UNKNOWN)",
        }[field]
    elif difference.observed_packet_family == 0x01 and byte == 11 + 0x3C:
        position = "Kit Hi-hat pedal MIDI Channel (CONFIRMED; stored channel-1)"
    elif difference.observed_packet_family == 0x01 and byte == 11 + 0x3D:
        position = "Kit Hi-hat pedal MIDI Note (CONFIRMED)"
    elif difference.observed_packet_family == 0x01 and byte == 11 + 0x3E:
        position = "Kit Hi-hat link/companion byte (UNKNOWN)"
    elif difference.observed_packet_family == 0x01 and byte == 11 + 0x3F:
        position = "Kit Input 3 closed Hi-hat MIDI Note (CONFIRMED)"
    elif difference.observed_packet_family == 0x01 and byte == 11 + 0x40:
        position = "Kit Program Change disabled flag (CONFIRMED; 1=---, 0=active)"
    elif difference.observed_packet_family == 0x01 and byte == 11 + 0x41:
        position = "Kit Program Change value (CONFIRMED; ignored while disabled)"
    elif difference.observed_packet_family == 0x02 and 0 <= difference.observed_packet_index <= 20 and 11 <= byte <= 15:
        record = difference.observed_packet_index
        target = "Hi-hat pedal" if record == 20 else f"Input {record // 2 + 1} {'Tip' if record % 2 == 0 else 'Ring'}"
        evidence = "CONFIRMED" if record == 0 else "MAPPED; HARDWARE WRITE NOT YET VALIDATED"
        position = {
            11: f"{target} Gain ({evidence})",
            12: f"{target} Velocity Curve ({evidence}; observed 6=Lin, 7=LG1)",
            13: f"{target} Threshold ({evidence})",
            14: f"{target} {'Calibration' if record == 20 else 'X-Talk'} ({evidence})",
            15: f"{target} Retrigger ({evidence})",
        }[byte]
    elif difference.observed_packet_family == 0x02 and 0 <= difference.observed_packet_index <= 20 and byte == 16:
        record = difference.observed_packet_index
        target = "Hi-hat pedal" if record == 20 else f"Input {record // 2 + 1} {'Tip' if record % 2 == 0 else 'Ring'}"
        position = f"{target} final raw byte (Trigger Type encoding unresolved)"
    else:
        position = labels.get(byte, f"opaque body byte +0x{byte - 11:02X}" if byte >= 11 else f"packet byte 0x{byte:02X}")
    return (
        f"Observed packet family 0x{difference.observed_packet_family:02X} / "
        f"index {difference.observed_packet_index}, {position}"
    )


def render_diff(differences: tuple[ByteDifference, ...]) -> str:
    if not differences:
        return "No byte differences.\n"
    lines = ["Field labels distinguish mapped bytes from hardware-write-validated bytes."]
    for difference in differences:
        before = "--" if difference.before is None else f"0x{difference.before:02X}"
        after = "--" if difference.after is None else f"0x{difference.after:02X}"
        delta = "n/a" if difference.before is None or difference.after is None else f"{difference.after - difference.before:+d}"
        lines.extend((f"Offset 0x{difference.offset:06X}:", f"    A = {before}", f"    B = {after}", f"    delta = {delta}"))
        if context := _observed_position_label(difference):
            lines.append(f"    Structural context: {context}")
    return "\n".join(lines) + "\n"
