"""Validated read model for the note fields of observed legacy DDTi dumps.

Only Kit/Input/Tip-or-Ring MIDI note locations are semantic fields here.  The
other two bytes stored alongside every zone remain raw observations, and no
configuration produced by this module may be sent to hardware yet.
"""
from __future__ import annotations

from dataclasses import dataclass

from .protocol import DDTiDump, decode_dump


_ZONE_COUNT = 20
_ZONE_BYTES = 3
_ZONE_START_IN_PACKET = 11


@dataclass(frozen=True)
class DDTiZone:
    note: int
    channel_raw: int
    flags_raw: int
    raw_note_offset: int

    def __post_init__(self) -> None:
        if not 0 <= self.note <= 127:
            raise ValueError("MIDI note must be 0..127")

    def to_document(self) -> dict[str, int]:
        return {
            "note": self.note,
            "channel_raw": self.channel_raw,
            "flags_raw": self.flags_raw,
            "raw_note_offset": self.raw_note_offset,
        }


@dataclass(frozen=True)
class DDTiInput:
    number: int
    tip: DDTiZone
    ring: DDTiZone

    def to_document(self) -> dict[str, object]:
        return {"input": self.number, "tip": self.tip.to_document(), "ring": self.ring.to_document()}


@dataclass(frozen=True)
class DDTiKit:
    number: int
    inputs: tuple[DDTiInput, ...]

    def __post_init__(self) -> None:
        if len(self.inputs) != 10:
            raise ValueError("observed DDTi kit layout has exactly 10 trigger inputs")

    def to_document(self) -> dict[str, object]:
        return {"kit": self.number, "inputs": [input_.to_document() for input_ in self.inputs]}


@dataclass(frozen=True)
class DDTiConfiguration:
    """Lossless configuration view with validated note fields only."""

    dump: DDTiDump
    kits: tuple[DDTiKit, ...]

    @property
    def raw(self) -> bytes:
        return self.dump.raw

    def with_note(self, kit: int, input_number: int, zone: str, note: int) -> "DDTiConfiguration":
        """Create an offline modified view; this does not transmit anything."""
        if not 0 <= note <= 127:
            raise ValueError("MIDI note must be 0..127")
        if not 0 <= kit < len(self.kits):
            raise ValueError(f"kit must be 0..{len(self.kits) - 1}")
        if not 1 <= input_number <= 10:
            raise ValueError("input_number must be 1..10")
        selected_kit = self.kits[kit]
        selected_input = selected_kit.inputs[input_number - 1]
        selected_zone = {"tip": selected_input.tip, "ring": selected_input.ring}.get(zone)
        if selected_zone is None:
            raise ValueError("zone must be 'tip' or 'ring'")
        raw = bytearray(self.raw)
        raw[selected_zone.raw_note_offset] = note
        return decode_configuration(decode_dump(bytes(raw)))

    def to_document(self) -> dict[str, object]:
        return {
            "semantic_decoding": "MIDI notes confirmed; companion bytes remain raw/uninterpreted",
            "kits": [kit.to_document() for kit in self.kits],
        }


def decode_configuration(dump: DDTiDump) -> DDTiConfiguration:
    """Decode only MIDI-note locations confirmed by controlled panel diffs.

    Family 0x01 record index maps to the kit number.  Its first 60 body bytes
    form twenty 3-byte records in Input1 Tip/Ring through Input10 Tip/Ring
    order.  The second byte of each record is the MIDI note.
    """
    offsets: dict[int, int] = {}
    position = 0
    for packet in dump.packets:
        offsets[id(packet)] = position
        position += len(packet.raw)
    packets = sorted((packet for packet in dump.packets if packet.record_type == 0x01), key=lambda packet: packet.record_index)
    if not packets:
        raise ValueError("dump contains no observed kit-family (0x01) packets")
    kits: list[DDTiKit] = []
    for packet in packets:
        if len(packet.body) < _ZONE_COUNT * _ZONE_BYTES:
            raise ValueError(f"kit packet {packet.record_index} is too short for 20 zone records")
        packet_start = offsets[id(packet)]
        inputs = []
        for input_index in range(10):
            zones = []
            for zone_index in (input_index * 2, input_index * 2 + 1):
                start = _ZONE_START_IN_PACKET + zone_index * _ZONE_BYTES
                zones.append(DDTiZone(
                    note=packet.raw[start + 1],
                    channel_raw=packet.raw[start],
                    flags_raw=packet.raw[start + 2],
                    raw_note_offset=packet_start + start + 1,
                ))
            inputs.append(DDTiInput(input_index + 1, zones[0], zones[1]))
        kits.append(DDTiKit(packet.record_index, tuple(inputs)))
    return DDTiConfiguration(dump, tuple(kits))


def encode_configuration(configuration: DDTiConfiguration) -> bytes:
    """Return the original/locally edited bytes exactly; hardware writes are forbidden elsewhere."""
    return configuration.raw
