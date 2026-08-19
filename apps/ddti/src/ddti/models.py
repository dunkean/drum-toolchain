"""Validated read model for the note fields of observed legacy DDTi dumps.

Only Kit/Input/Tip-or-Ring MIDI note locations are semantic fields here.  The
other two bytes stored alongside every zone remain raw observations, and no
configuration produced by this module may be sent to hardware yet.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .protocol import DDTiDump, decode_dump


_ZONE_COUNT = 20
_ZONE_BYTES = 3
_ZONE_START_IN_PACKET = 11
NOTE_PRESET_FORMAT = "ddti-note-preset/v1"


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
class DDTiGlobalTriggerRecord:
    """One lossless Family-02 record; field semantics remain experimental."""

    index: int
    values: tuple[int, ...]
    raw_offsets: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.values) != 6 or len(self.raw_offsets) != 6:
            raise ValueError("observed global-trigger records contain exactly six bytes")

    def to_document(self) -> dict[str, object]:
        return {
            "record": self.index,
            "raw_values": list(self.values),
            "raw_offsets": list(self.raw_offsets),
            "semantic_decoding": "uninterpreted; Input 1 Tip Gain is confirmed at record 0 / byte 0 only",
        }


@dataclass(frozen=True)
class DDTiConfiguration:
    """Lossless configuration view with validated note fields only."""

    dump: DDTiDump
    kits: tuple[DDTiKit, ...]
    global_trigger_records: tuple[DDTiGlobalTriggerRecord, ...]

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

    def to_note_preset(self) -> dict[str, object]:
        """Export every confirmed note field as a portable offline preset.

        This deliberately excludes channels and companion bytes: their meaning
        has not yet been validated from controlled hardware captures.
        """
        return {
            "format": NOTE_PRESET_FORMAT,
            "kits": [
                {
                    "kit": kit.number,
                    "inputs": [
                        {
                            "input": input_.number,
                            "tip_note": input_.tip.note,
                            "ring_note": input_.ring.note,
                        }
                        for input_ in kit.inputs
                    ],
                }
                for kit in self.kits
            ],
        }

    def with_note_preset(self, preset: Mapping[str, object]) -> "DDTiConfiguration":
        """Apply a validated portable note preset to an offline configuration.

        The preset may contain any subset of the observed kits and inputs.  It
        never opens a MIDI port and returns a new in-memory configuration.
        """
        if preset.get("format") != NOTE_PRESET_FORMAT:
            raise ValueError(f"preset format must be {NOTE_PRESET_FORMAT!r}")
        kit_entries = preset.get("kits")
        if not isinstance(kit_entries, Sequence) or isinstance(kit_entries, (str, bytes)):
            raise ValueError("preset kits must be a list")
        by_kit = {kit.number: kit for kit in self.kits}
        seen_kits: set[int] = set()
        raw = bytearray(self.raw)
        for kit_entry in kit_entries:
            if not isinstance(kit_entry, Mapping):
                raise ValueError("each preset kit must be an object")
            kit_number = kit_entry.get("kit")
            if type(kit_number) is not int or kit_number not in by_kit:
                raise ValueError("preset contains an unknown kit")
            if kit_number in seen_kits:
                raise ValueError(f"preset repeats kit {kit_number}")
            seen_kits.add(kit_number)
            input_entries = kit_entry.get("inputs")
            if not isinstance(input_entries, Sequence) or isinstance(input_entries, (str, bytes)):
                raise ValueError("preset kit inputs must be a list")
            seen_inputs: set[int] = set()
            for input_entry in input_entries:
                if not isinstance(input_entry, Mapping):
                    raise ValueError("each preset input must be an object")
                input_number = input_entry.get("input")
                if type(input_number) is not int or not 1 <= input_number <= 10:
                    raise ValueError("preset input must be 1..10")
                if input_number in seen_inputs:
                    raise ValueError(f"preset repeats input {input_number} in kit {kit_number}")
                seen_inputs.add(input_number)
                target = by_kit[kit_number].inputs[input_number - 1]
                for field, zone in (("tip_note", target.tip), ("ring_note", target.ring)):
                    if field not in input_entry:
                        continue
                    note = input_entry[field]
                    if type(note) is not int or not 0 <= note <= 127:
                        raise ValueError(f"{field} must be an integer in 0..127")
                    raw[zone.raw_note_offset] = note
        return decode_configuration(decode_dump(bytes(raw)))

    def to_document(self) -> dict[str, object]:
        return {
            "semantic_decoding": "MIDI notes confirmed; companion bytes remain raw/uninterpreted",
            "kits": [kit.to_document() for kit in self.kits],
            "global_trigger_records": [record.to_document() for record in self.global_trigger_records],
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
    global_records = []
    for packet in sorted((packet for packet in dump.packets if packet.record_type == 0x02), key=lambda packet: packet.record_index):
        if len(packet.body) != 6:
            raise ValueError(f"global-trigger packet {packet.record_index} does not contain six raw bytes")
        packet_start = offsets[id(packet)]
        global_records.append(DDTiGlobalTriggerRecord(
            packet.record_index,
            tuple(packet.body),
            tuple(packet_start + 11 + value_index for value_index in range(6)),
        ))
    return DDTiConfiguration(dump, tuple(kits), tuple(global_records))


def encode_configuration(configuration: DDTiConfiguration) -> bytes:
    """Return the original/locally edited bytes exactly; hardware writes are forbidden elsewhere."""
    return configuration.raw
