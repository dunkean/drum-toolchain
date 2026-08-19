"""Validated offline model for fields observed in legacy DDTi dumps."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .protocol import DDTiDump, decode_dump


_ZONE_COUNT = 20
_ZONE_BYTES = 3
_ZONE_START_IN_PACKET = 11
NOTE_PRESET_FORMAT = "ddti-note-preset/v1"
CONFIGURATION_PRESET_FORMAT = "ddti-configuration-preset/v1"
GLOBAL_TRIGGER_FIELDS = {
    "gain": 0,
    "velocity_curve": 1,
    "threshold": 2,
    "xtalk": 3,
    "retrigger": 4,
}
VELOCITY_CURVE_LABELS = {6: "Lin", 7: "LG1"}
_INPUT_1_TIP_RECORD = 0
_PROGRAM_CHANGE_DISABLED_BODY_OFFSET = 0x40
_PROGRAM_CHANGE_VALUE_BODY_OFFSET = 0x41


@dataclass(frozen=True)
class DDTiZone:
    note: int
    channel_raw: int
    flags_raw: int
    raw_channel_offset: int
    raw_note_offset: int

    def __post_init__(self) -> None:
        if not 0 <= self.note <= 127:
            raise ValueError("MIDI note must be 0..127")

    @property
    def channel(self) -> int:
        """MIDI channel shown by the DDTi; storage is zero-based."""
        return self.channel_raw + 1

    def to_document(self) -> dict[str, int]:
        return {
            "note": self.note,
            "channel": self.channel,
            "channel_raw": self.channel_raw,
            "flags_raw": self.flags_raw,
            "raw_channel_offset": self.raw_channel_offset,
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
class DDTiHiHatKitSettings:
    """Per-kit pedal and closed-hi-hat notes from the six-byte kit tail."""

    pedal_channel_raw: int
    pedal_note: int
    closed_note: int
    link_raw: int
    raw_pedal_channel_offset: int
    raw_pedal_note_offset: int
    raw_closed_note_offset: int

    @property
    def pedal_channel(self) -> int:
        return self.pedal_channel_raw + 1

    def to_document(self) -> dict[str, int]:
        return {
            "pedal_channel": self.pedal_channel,
            "pedal_note": self.pedal_note,
            "closed_note": self.closed_note,
            "link_raw": self.link_raw,
        }


@dataclass(frozen=True)
class DDTiKit:
    number: int
    inputs: tuple[DDTiInput, ...]
    hi_hat: DDTiHiHatKitSettings
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
            "hi_hat": self.hi_hat.to_document(),
        }


@dataclass(frozen=True)
class DDTiGlobalTriggerRecord:
    """One lossless Family-02 record."""

    index: int
    values: tuple[int, ...]
    raw_offsets: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.values) != 6 or len(self.raw_offsets) != 6:
            raise ValueError("observed global-trigger records contain exactly six bytes")

    @property
    def input_number(self) -> int | None:
        return self.index // 2 + 1 if self.index < 20 else None

    @property
    def zone(self) -> str:
        if self.index == 20:
            return "hi_hat_pedal"
        return "tip" if self.index % 2 == 0 else "ring"

    @property
    def label(self) -> str:
        return "Hi-hat pedal" if self.index == 20 else f"Input {self.input_number} {self.zone.title()}"

    @property
    def settings(self) -> dict[str, int]:
        return {name: self.values[index] for name, index in GLOBAL_TRIGGER_FIELDS.items()}

    @property
    def trigger_type_raw(self) -> int:
        return self.values[5]

    def to_document(self) -> dict[str, object]:
        document: dict[str, object] = {
            "record": self.index,
            "raw_values": list(self.values),
            "raw_offsets": list(self.raw_offsets),
            "target": self.label,
            "input": self.input_number,
            "zone": self.zone,
            "settings": self.settings,
            "velocity_curve_label": VELOCITY_CURVE_LABELS.get(self.values[1]),
            "trigger_type_raw": self.trigger_type_raw,
            "semantic_decoding": "five setting bytes mapped; trigger-type byte remains raw",
        }
        return document


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
        return self.with_zone(kit, input_number, zone, note=note)

    def with_zone(
        self,
        kit: int,
        input_number: int,
        zone: str,
        *,
        channel: int | None = None,
        note: int | None = None,
    ) -> "DDTiConfiguration":
        """Stage the per-kit MIDI channel and/or note for one physical zone."""
        if not 0 <= kit < len(self.kits):
            raise ValueError(f"kit must be 0..{len(self.kits) - 1}")
        if not 1 <= input_number <= 10:
            raise ValueError("input_number must be 1..10")
        selected_input = self.kits[kit].inputs[input_number - 1]
        selected_zone = {"tip": selected_input.tip, "ring": selected_input.ring}.get(zone)
        if selected_zone is None:
            raise ValueError("zone must be 'tip' or 'ring'")
        if channel is not None and (type(channel) is not int or not 1 <= channel <= 16):
            raise ValueError("MIDI channel must be an integer in 1..16")
        if note is not None and (type(note) is not int or not 0 <= note <= 127):
            raise ValueError("MIDI note must be an integer in 0..127")
        raw = bytearray(self.raw)
        if channel is not None:
            raw[selected_zone.raw_channel_offset] = channel - 1
        if note is not None:
            raw[selected_zone.raw_note_offset] = note
        return decode_configuration(decode_dump(bytes(raw)))

    def with_hi_hat_kit_settings(
        self,
        kit: int,
        *,
        pedal_channel: int | None = None,
        pedal_note: int | None = None,
        closed_note: int | None = None,
    ) -> "DDTiConfiguration":
        """Stage the documented per-kit hi-hat pedal and closed-note fields."""
        if not 0 <= kit < len(self.kits):
            raise ValueError(f"kit must be 0..{len(self.kits) - 1}")
        if pedal_channel is not None and (type(pedal_channel) is not int or not 1 <= pedal_channel <= 16):
            raise ValueError("hi-hat pedal MIDI channel must be an integer in 1..16")
        for name, value in (("pedal_note", pedal_note), ("closed_note", closed_note)):
            if value is not None and (type(value) is not int or not 0 <= value <= 127):
                raise ValueError(f"hi-hat {name} must be an integer in 0..127")
        target = self.kits[kit].hi_hat
        raw = bytearray(self.raw)
        if pedal_channel is not None:
            raw[target.raw_pedal_channel_offset] = pedal_channel - 1
        if pedal_note is not None:
            raw[target.raw_pedal_note_offset] = pedal_note
        if closed_note is not None:
            raw[target.raw_closed_note_offset] = closed_note
        return decode_configuration(decode_dump(bytes(raw)))

    @property
    def input_1_tip_gain(self) -> int:
        return self.input_1_tip_settings["gain"]

    @property
    def input_1_tip_settings(self) -> dict[str, int]:
        """Return the five settings isolated together in Family 02 record 0."""
        record = next((record for record in self.global_trigger_records if record.index == _INPUT_1_TIP_RECORD), None)
        if record is None:
            raise ValueError("dump contains no global-trigger record 0 for Input 1 Tip settings")
        return record.settings

    @property
    def input_1_tip_velocity_curve_label(self) -> str | None:
        return VELOCITY_CURVE_LABELS.get(self.input_1_tip_settings["velocity_curve"])

    def with_input_1_tip_settings(self, settings: Mapping[str, object]) -> "DDTiConfiguration":
        """Stage any subset of the five confirmed Input 1 Tip fields offline."""
        return self.with_global_trigger_settings(_INPUT_1_TIP_RECORD, settings)

    def with_global_trigger_settings(
        self,
        record_index: int,
        settings: Mapping[str, object],
    ) -> "DDTiConfiguration":
        """Stage global settings for one of 20 zones or the hi-hat pedal."""
        allowed = {*GLOBAL_TRIGGER_FIELDS, "trigger_type_raw"}
        unknown = set(settings) - allowed
        if unknown:
            raise ValueError(f"unknown global trigger setting(s): {', '.join(sorted(unknown))}")
        record = next((item for item in self.global_trigger_records if item.index == record_index), None)
        if record is None:
            raise ValueError(f"dump contains no global-trigger record {record_index}")
        raw = bytearray(self.raw)
        for name, value in settings.items():
            if type(value) is not int or not 0 <= value <= 127:
                display_name = "Gain" if name == "gain" else name
                raise ValueError(f"{record.label} {display_name} must be an integer in 0..127")
            value_index = 5 if name == "trigger_type_raw" else GLOBAL_TRIGGER_FIELDS[name]
            raw[record.raw_offsets[value_index]] = value
        return decode_configuration(decode_dump(bytes(raw)))

    def with_input_1_tip_gain(self, gain: int) -> "DDTiConfiguration":
        """Stage the confirmed Input 1 Tip Gain byte offline."""
        return self.with_input_1_tip_settings({"gain": gain})

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
        """Export the complete modeled configuration as a portable preset.

        The unresolved final trigger byte is carried under its explicit raw
        name; every byte outside the model remains in the source dump.
        """
        document: dict[str, object] = {
            "format": CONFIGURATION_PRESET_FORMAT,
            "notes": [
                {
                    "kit": kit.number,
                    "inputs": [
                        {
                            "input": input_.number,
                            "tip_channel": input_.tip.channel,
                            "tip_note": input_.tip.note,
                            "ring_channel": input_.ring.channel,
                            "ring_note": input_.ring.note,
                        }
                        for input_ in kit.inputs
                    ],
                    "hi_hat": kit.hi_hat.to_document(),
                }
                for kit in self.kits
            ],
            "kit_settings": [
                {"kit": kit.number, "program_change": kit.program_change}
                for kit in self.kits
            ],
            "global_triggers": [
                {
                    "record": record.index,
                    "target": record.label,
                    **record.settings,
                    "trigger_type_raw": record.trigger_type_raw,
                }
                for record in self.global_trigger_records
            ],
            # Backward-compatible alias consumed by early v1 presets/clients.
            "confirmed_global_trigger": {"input_1_tip": self.input_1_tip_settings},
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
        for kit_entry in notes:
            if not isinstance(kit_entry, Mapping):
                continue
            kit_number = kit_entry.get("kit")
            if type(kit_number) is not int or not 0 <= kit_number < len(self.kits):
                continue
            inputs = kit_entry.get("inputs", [])
            if isinstance(inputs, Sequence) and not isinstance(inputs, (str, bytes)):
                for input_entry in inputs:
                    if not isinstance(input_entry, Mapping):
                        continue
                    input_number = input_entry.get("input")
                    if type(input_number) is not int or not 1 <= input_number <= 10:
                        continue
                    for zone in ("tip", "ring"):
                        channel_key = f"{zone}_channel"
                        if channel_key in input_entry:
                            configuration = configuration.with_zone(
                                kit_number, input_number, zone, channel=input_entry[channel_key]
                            )
            hi_hat = kit_entry.get("hi_hat")
            if isinstance(hi_hat, Mapping):
                configuration = configuration.with_hi_hat_kit_settings(
                    kit_number,
                    pedal_channel=hi_hat.get("pedal_channel"),
                    pedal_note=hi_hat.get("pedal_note"),
                    closed_note=hi_hat.get("closed_note"),
                )
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
        global_triggers = preset.get("global_triggers", [])
        if not isinstance(global_triggers, Sequence) or isinstance(global_triggers, (str, bytes)):
            raise ValueError("configuration preset global_triggers must be a list")
        seen_records: set[int] = set()
        for entry in global_triggers:
            if not isinstance(entry, Mapping):
                raise ValueError("each global trigger entry must be an object")
            record = entry.get("record")
            if type(record) is not int or not 0 <= record < len(self.global_trigger_records):
                raise ValueError("configuration preset contains an unknown global trigger record")
            if record in seen_records:
                raise ValueError(f"configuration preset repeats global trigger record {record}")
            seen_records.add(record)
            values = {
                name: entry[name]
                for name in (*GLOBAL_TRIGGER_FIELDS, "trigger_type_raw")
                if name in entry
            }
            configuration = configuration.with_global_trigger_settings(record, values)
        # The complete list is canonical. Consume the legacy alias only for
        # older presets without record 0, otherwise a stale alias could undo a
        # record-0 edit in the same document.
        if 0 not in seen_records and "input_1_tip" in trigger:
            input_1_tip = trigger["input_1_tip"]
            if not isinstance(input_1_tip, Mapping):
                raise ValueError("confirmed_global_trigger.input_1_tip must be an object")
            configuration = configuration.with_input_1_tip_settings(input_1_tip)
        if 0 not in seen_records and "input_1_tip_gain" in trigger:
            configuration = configuration.with_input_1_tip_gain(trigger["input_1_tip_gain"])
        return configuration

    def to_document(self) -> dict[str, object]:
        return {
            "semantic_decoding": "per-kit channels/notes/hi-hat/Program Change and five global setting columns decoded; trigger type stays raw",
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
                    raw_channel_offset=packet_start + start,
                    raw_note_offset=packet_start + start + 1,
                ))
            inputs.append(DDTiInput(input_index + 1, zones[0], zones[1]))
        if len(packet.body) <= _PROGRAM_CHANGE_VALUE_BODY_OFFSET:
            raise ValueError(f"kit packet {packet.record_index} is too short for Program Change fields")
        disabled_raw = packet.body[_PROGRAM_CHANGE_DISABLED_BODY_OFFSET]
        value_raw = packet.body[_PROGRAM_CHANGE_VALUE_BODY_OFFSET]
        program_change = None if disabled_raw == 1 else value_raw if disabled_raw == 0 else None
        hi_hat = DDTiHiHatKitSettings(
            pedal_channel_raw=packet.body[0x3C],
            pedal_note=packet.body[0x3D],
            link_raw=packet.body[0x3E],
            closed_note=packet.body[0x3F],
            raw_pedal_channel_offset=packet_start + _ZONE_START_IN_PACKET + 0x3C,
            raw_pedal_note_offset=packet_start + _ZONE_START_IN_PACKET + 0x3D,
            raw_closed_note_offset=packet_start + _ZONE_START_IN_PACKET + 0x3F,
        )
        kits.append(DDTiKit(
            number=packet.record_index,
            inputs=tuple(inputs),
            hi_hat=hi_hat,
            program_change=program_change,
            program_change_disabled_raw=disabled_raw,
            raw_program_change_disabled_offset=packet_start + _ZONE_START_IN_PACKET + _PROGRAM_CHANGE_DISABLED_BODY_OFFSET,
            raw_program_change_value_offset=packet_start + _ZONE_START_IN_PACKET + _PROGRAM_CHANGE_VALUE_BODY_OFFSET,
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
