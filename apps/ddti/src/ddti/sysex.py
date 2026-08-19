"""Lossless, protocol-agnostic SysEx framing helpers.

These helpers intentionally identify only universal MIDI framing.  They do
not claim a manufacturer, command layout, checksum, or semantic payload.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SysExMessage:
    raw: bytes

    def __post_init__(self) -> None:
        if len(self.raw) < 2 or self.raw[0] != 0xF0 or self.raw[-1] != 0xF7:
            raise ValueError("SysEx message must begin with F0 and end with F7")
        if any(byte > 0x7F for byte in self.raw[1:-1]):
            raise ValueError("SysEx data bytes must be 7-bit values")

    @property
    def data(self) -> bytes:
        return self.raw[1:-1]


def parse_stream(raw: bytes) -> tuple[SysExMessage, ...]:
    """Parse a concatenated raw `.syx` stream without normalising any byte."""
    messages: list[SysExMessage] = []
    position = 0
    while position < len(raw):
        if raw[position] != 0xF0:
            raise ValueError(f"unexpected byte 0x{raw[position]:02X} at offset 0x{position:04X}; expected F0")
        end = raw.find(b"\xF7", position + 1)
        if end == -1:
            raise ValueError(f"unterminated SysEx message starting at offset 0x{position:04X}")
        messages.append(SysExMessage(raw[position:end + 1]))
        position = end + 1
    return tuple(messages)


def render_hex(messages: tuple[SysExMessage, ...]) -> str:
    offset = 0
    rows: list[str] = []
    for index, message in enumerate(messages, start=1):
        rows.append(f"message {index:03d} | offset 0x{offset:06X} | {len(message.raw)} bytes")
        for line_start in range(0, len(message.raw), 16):
            chunk = message.raw[line_start:line_start + 16]
            rows.append(f"  {offset + line_start:06X}: {' '.join(f'{byte:02X}' for byte in chunk)}")
        offset += len(message.raw)
    return "\n".join(rows) + ("\n" if rows else "")
