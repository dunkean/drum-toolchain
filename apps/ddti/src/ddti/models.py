"""Validated offline model for fields observed in legacy DDTi dumps.

Kit/Input/Tip-or-Ring MIDI notes and Input 1 Tip Gain are the only semantic
fields here. The other bytes remain raw observations, and no configuration
produced by this module may be sent to hardware yet.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .protocol import DDTiDump, decode_dump


_ZONE_COUNT = 20
_ZONE_BYTES = 3
_ZONE_START_IN_PACKET = 11
NOTE_PRESET_FORMAT = "ddti-note-preset/v1"
CONFIGURATION_PRESET_FORMAT = "ddti-configuration-preset/v1"
_INPUT_1_TIP_GAIN_RECORD = 0
_INPUT_1_TIP_GAIN_VALUE_INDEX = 0
_PROGRAM_CHANGE_DISABLED_BODY_OFFSET = 0x40
_PROGRAM_CHANGE_VALUE_BODY_OFFSET = 0x41


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
    program_change: int | None = None
    program_change_disabled_raw: int = 1
    raw_program_change_disabled_offset: int = -1
    raw_program_change_value_offset: int = -1

    def __post_init__(self) -> None:
        if len(self.inputs) != 10:
            raise ValueError("observed DDTi kit layout has exactly 10 trigger inputs")

    def to_document(self) -> dict[str, object]:
        return {
            "kit": self.number,
            "program_change": self.program_change,
            "program_change_disabled_raw": self.program_change_disabled_raw,
            "inputs": [input_.to_document() for input_ in self.inputs],
        }


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
    """Lossless offline configuration view with only proven semantic edits."""

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

    @property
    def input_1_tip_gain(self) -> int:
        """Return the one gain byte confirmed by a controlled panel change.

        Its byte location is confirmed for Input 1 Tip. The valid panel range
        has not been fully mapped, so offline edits accept the complete uint7
        storage range and still cannot be sent to a DDTi.
        """
        record = next((record for record in self.global_trigger_records if record.index == _INPUT_1_TIP_GAIN_RECORD), None)
        if record is None:
            raise ValueError("dump contains no global-trigger record 0 for Input 1 Tip Gain")
        return record.values[_INPUT_1_TIP_GAIN_VALUE_INDEX]

    def with_input_1_tip_gain(self, gain: int) -> "DDTiConfiguration":
        """Stage the confirmed Input 1 Tip Gain byte offline."""
        if type(gain) is not int or not 0 <= gain <= 127:
            raise ValueError("Input 1 Tip Gain must be an integer in 0..127")
        record = next((record for record in self.global_trigger_records if record.index == _INPUT_1_TIP_GAIN_RECORD), None)
        if record is None:
            raise ValueError("dump contains no global-trigger record 0 for Input 1 Tip Gain")
        raw = bytearray(self.raw)
        raw[record.raw_offsets[_INPUT_1_TIP_GAIN_VALUE_INDEX]] = gain
        return decode_configuration(decode_dump(bytes(raw)))

    def with_program_change(self, kit: int, program_change: int | None) -> "DDTiConfiguration":
        """Stage a confirmed per-kit Program Change, or ``None`` for ``---``."""
        if not 0 <= kit < len(self.kits):
            raise ValueError(f"kit must be 0..{len(self.kits) - 1}")
        if program_change is not None and (type(program_change) is not int or not 0 <= program_change <= 127):
            raise ValueError("Program Change must be null/--- or an integer in 0..127")
        target = self.kits[kit]
        if target.raw_program_change_disabled_offset < 0 or target.raw_program_change_value_offset < 0:
            raise ValueError("kit packet has no decoded Program Change fields")
        raw = bytearray(self.raw)
        raw[target.raw_program_change_disabled_offset] = 1 if program_change is None else 0
        raw[target.raw_program_change_value_offset] = 0 if program_change is None else program_change
        return decode_configuration(decode_dump(bytes(raw)))

    def canonicalize_disabled_program_changes(self) -> "DDTiConfiguration":
        """Encode every disabled ``---`` field as the device's observed `01 00`."""
        updated = self
        for kit in self.kits:
            if kit.program_change is None and (
                kit.program_change_disabled_raw != 1
                or updated.raw[kit.raw_program_change_value_offset] != 0
            ):
                updated = updated.with_program_change(kit.number, None)
        return updated

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

    def to_configuration_preset(self, *, name: str | None = None) -> dict[str, object]:
        """Export all currently proven editable values as a portable preset.

        This intentionally is a subset of the raw dump. Unknown trigger bytes
        stay in the source dump and are neither serialised as semantics nor
        modified by applying this document.
        """
        document: dict[str, object] = {
            "format": CONFIGURATION_PRESET_FORMAT,
            "notes": self.to_note_preset()["kits"],
            "kit_settings": [
                {"kit": kit.number, "program_change": kit.program_change}
                for kit in self.kits
            ],
            "confirmed_global_trigger": {"input_1_tip_gain": self.input_1_tip_gain},
        }
        if name:
            document["name"] = name
        return document

    def with_configuration_preset(self, preset: Mapping[str, object]) -> "DDTiConfiguration":
        """Stage a YAML/JSON configuration preset without opening MIDI."""
        if preset.get("format") != CONFIGURATION_PRESET_FORMAT:
            raise ValueError(f"preset format must be {CONFIGURATION_PRESET_FORMAT!r}")
        notes = preset.get("notes", [])
        if not isinstance(notes, Sequence) or isinstance(notes, (str, bytes)):
            raise ValueError("configuration preset notes must be a list")
        configuration = self.with_note_preset({"format": NOTE_PRESET_FORMAT, "kits": notes})
        kit_settings = preset.get("kit_settings", [])
        if not isinstance(kit_settings, Sequence) or isinstance(kit_settings, (str, bytes)):
            raise ValueError("configuration preset kit_settings must be a list")
        seen_kit_settings: set[int] = set()
        for setting in kit_settings:
            if not isinstance(setting, Mapping):
                raise ValueError("each configuration preset kit setting must be an object")
            kit_number = setting.get("kit")
            if type(kit_number) is not int or not 0 <= kit_number < len(self.kits):
                raise ValueError("configuration preset contains an unknown kit setting")
            if kit_number in seen_kit_settings:
                raise ValueError(f"configuration preset repeats kit setting {kit_number}")
            seen_kit_settings.add(kit_number)
            if "program_change" in setting:
                configuration = configuration.with_program_change(kit_number, setting["program_change"])
        trigger = preset.get("confirmed_global_trigger", {})
        if not isinstance(trigger, Mapping):
            raise ValueError("configuration preset confirmed_global_trigger must be an object")
        if "input_1_tip_gain" in trigger:
            configuration = configuration.with_input_1_tip_gain(trigger["input_1_tip_gain"])
        return configuration

    def to_document(self) -> dict[str, object]:
        return {
            "semantic_decoding": "MIDI notes, per-kit Program Change, and Input 1 Tip Gain confirmed; remaining bytes stay raw/uninterpreted",
            "kits": [kit.to_document() for kit in self.kits],
            "confirmed_global_trigger": {"input_1_tip_gain": self.input_1_tip_gain} if self.global_trigger_records else {},
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
        if len(packet.body) <= _PROGRAM_CHANGE_VALUE_BODY_OFFSET:
            raise ValueError(f"kit packet {packet.record_index} is too short for Program Change fields")
        disabled_raw = packet.body[_PROGRAM_CHANGE_DISABLED_BODY_OFFSET]
        value_raw = packet.body[_PROGRAM_CHANGE_VALUE_BODY_OFFSET]
        program_change = None if disabled_raw == 1 else value_raw if disabled_raw == 0 else None
        kits.append(DDTiKit(
            packet.record_index,
            tuple(inputs),
            program_change,
            disabled_raw,
            packet_start + _ZONE_START_IN_PACKET + _PROGRAM_CHANGE_DISABLED_BODY_OFFSET,
            packet_start + _ZONE_START_IN_PACKET + _PROGRAM_CHANGE_VALUE_BODY_OFFSET,
        ))
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
