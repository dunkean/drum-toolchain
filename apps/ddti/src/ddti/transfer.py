"""Validated *offline* plans for the future DDTi SysEx transfer path.

This module intentionally does not import MIDI libraries or open output ports.
It establishes the invariant a hardware sender will require: only a complete,
lossless legacy DDTi dump can ever be considered for transfer.

An exact golden-dump round trip initially normalised one byte in each of the
first twenty kit frames. Controlled panel tests proved it is the ignored value
of a disabled Program Change. Subsequent Note, Program/Gain, and grouped
five-setting Input 1 Tip transfers were returned byte-identically. The safe
writer therefore permits only confirmed field offsets and observed values,
and keeps unrestricted raw replay hard-disabled.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from .diff import ByteDifference, diff_ddti_bytes
from .protocol import DDTiDump, decode_dump
from .device import ProtocolNotValidatedError
from .models import decode_configuration
from .sysex import parse_stream


_COMPLETE_FAMILIES = {1: tuple(range(21)), 2: tuple(range(21))}
FACTORY_GOLDEN_SHA256 = "43c64c486f72ec349c5ebee4020ef9e176f5d64033118f95fb25f6f81f84c70f"
NOTE_WRITE_VALIDATION_SHA256 = "c14e5136f3db716d3ad85986c9d1b5c6b72346d976132c537b0abfa323ee1cdb"


@dataclass(frozen=True)
class DDTiTransferPlan:
    """A reviewable, output-free description of one complete SysEx transfer."""

    dump: DDTiDump

    @property
    def raw(self) -> bytes:
        return self.dump.raw

    @property
    def sha256(self) -> str:
        return self.dump.sha256

    def to_document(self) -> dict[str, object]:
        return {
            "kind": "ddti-legacy-transfer-plan",
            "hardware_write": "unrestricted_raw_disabled",
            "byte_count": len(self.raw),
            "packet_count": len(self.dump.packets),
            "sha256": self.sha256,
            "families": self.dump.family_indexes(),
            "safety": "This is a review-only plan. It opens no MIDI output and sends no bytes.",
        }


@dataclass(frozen=True)
class DDTiTransferResult:
    output_port: str
    packet_count: int
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class DDTiSafeWritePlan:
    """A candidate proven to differ only in hardware-validated fields."""

    source_sha256: str
    transfer: DDTiTransferPlan
    differences: tuple[ByteDifference, ...]

    @property
    def raw(self) -> bytes:
        return self.transfer.raw

    @property
    def sha256(self) -> str:
        return self.transfer.sha256

    def to_document(self) -> dict[str, object]:
        return {
            "kind": "ddti-confirmed-fields-write-plan",
            "source_sha256": self.source_sha256,
            "candidate_sha256": self.sha256,
            "byte_count": len(self.raw),
            "packet_count": len(self.transfer.dump.packets),
            "changed_bytes": len(self.differences),
            "allowed_fields": ["kit MIDI notes", "kit Program Change", "validated Input 1 Tip settings"],
            "hardware_write": "requires explicit confirmation",
        }


def build_transfer_plan(raw: bytes) -> DDTiTransferPlan:
    """Validate a complete 42-frame DDTi dump for offline transfer review."""
    dump = decode_dump(raw)
    if dump.family_indexes() != _COMPLETE_FAMILIES:
        raise ValueError("a DDTi transfer plan requires all 21 kit and 21 global-trigger packets")
    return DDTiTransferPlan(dump)


def build_transfer_plan_from_file(path: Path) -> DDTiTransferPlan:
    return build_transfer_plan(path.read_bytes())


def build_safe_write_plan(source_raw: bytes, candidate_raw: bytes) -> DDTiSafeWritePlan:
    """Reject every candidate mutation outside experimentally proven fields."""
    source_plan = build_transfer_plan(source_raw)
    candidate_plan = build_transfer_plan(candidate_raw)
    source = decode_configuration(source_plan.dump)
    candidate = decode_configuration(candidate_plan.dump)

    # The device canonicalises the unused Program Change value while disabled.
    candidate = candidate.canonicalize_disabled_program_changes()
    candidate_plan = build_transfer_plan(candidate.raw)

    allowed_offsets = {
        zone.raw_note_offset
        for kit in source.kits
        for input_ in kit.inputs
        for zone in (input_.tip, input_.ring)
    }
    for kit in source.kits:
        allowed_offsets.add(kit.raw_program_change_disabled_offset)
        allowed_offsets.add(kit.raw_program_change_value_offset)
    input_1_tip_offsets = source.global_trigger_records[0].raw_offsets[:5]
    allowed_offsets.update(input_1_tip_offsets)

    for kit in candidate.kits:
        if kit.program_change_disabled_raw not in {0, 1}:
            raise ValueError(f"Kit {kit.number} Program Change disabled flag must be 0 or 1")
        if kit.program_change_disabled_raw == 1 and candidate.raw[kit.raw_program_change_value_offset] != 0:
            raise ValueError(f"Kit {kit.number} disabled Program Change must use canonical value 0")
    observed_write_values = {
        "gain": {15, 16},
        "velocity_curve": {6, 7},
        "threshold": {5, 7},
        "xtalk": {1, 4},
        "retrigger": {10, 14},
    }
    source_settings = source.input_1_tip_settings
    candidate_settings = candidate.input_1_tip_settings
    for field, allowed_values in observed_write_values.items():
        if source_settings[field] != candidate_settings[field] and candidate_settings[field] not in allowed_values:
            ordered = sorted(allowed_values)
            values = f"{ordered[0]} and {ordered[1]}" if len(ordered) == 2 else ", ".join(map(str, ordered))
            raise ValueError(f"Input 1 Tip {field} writes are currently validated only for values {values}")

    differences = diff_ddti_bytes(source.raw, candidate.raw)
    forbidden = [difference for difference in differences if difference.offset not in allowed_offsets]
    if forbidden:
        offsets = ", ".join(f"0x{difference.offset:06X}" for difference in forbidden[:8])
        raise ProtocolNotValidatedError(f"candidate changes unvalidated DDTi byte(s): {offsets}")
    return DDTiSafeWritePlan(source_plan.sha256, candidate_plan, differences)


def build_note_write_validation_plan(raw: bytes) -> DDTiTransferPlan:
    """Build the one authorised-candidate Note 35->36 validation payload.

    This accepts only the immutable complete factory golden. Disabled Program
    Changes are first canonicalised to the device-observed ``01 00`` encoding,
    then exactly Kit index 0 / Input 1 Tip is staged from note 35 to 36.
    Constructing the plan is offline and opens no MIDI output.
    """
    source = build_transfer_plan(raw)
    if source.sha256 != FACTORY_GOLDEN_SHA256:
        raise ValueError("note-write validation requires the exact complete factory golden SHA-256")
    configuration = decode_configuration(source.dump)
    if configuration.kits[0].inputs[0].tip.note != 35:
        raise ValueError("factory golden does not contain expected Kit 0 / Input 1 Tip note 35")
    staged = configuration.canonicalize_disabled_program_changes().with_note(0, 1, "tip", 36)
    return build_transfer_plan(staged.raw)


def build_settings_write_validation_plan(raw: bytes) -> DDTiTransferPlan:
    """Build the fixed Program Change 0 plus Gain 15->16 validation payload."""
    source = build_transfer_plan(raw)
    if source.sha256 != FACTORY_GOLDEN_SHA256:
        raise ValueError("settings-write validation requires the exact complete factory golden SHA-256")
    configuration = decode_configuration(source.dump)
    if configuration.kits[0].program_change is not None:
        raise ValueError("factory golden does not contain expected disabled Kit 0 Program Change")
    if configuration.input_1_tip_gain != 15:
        raise ValueError("factory golden does not contain expected Input 1 Tip Gain 15")
    staged = (
        configuration.canonicalize_disabled_program_changes()
        .with_program_change(0, 0)
        .with_input_1_tip_gain(16)
    )
    return build_transfer_plan(staged.raw)


def _resolve_output(query: str) -> str:
    import mido

    names = list(mido.get_output_names())
    exact = [name for name in names if name.casefold() == query.casefold()]
    matches = exact or [name for name in names if query.casefold() in name.casefold()]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one MIDI output matching {query!r}; found {matches}")
    return matches[0]


def send_note_write_validation(
    plan: DDTiTransferPlan,
    output_query: str,
    *,
    expected_sha256: str,
    confirmation: str,
    inter_message_ms: float = 50,
) -> DDTiTransferResult:
    """Send only the fixed, reviewed Note 35->36 validation payload.

    This is not a generic writer. Both the compiled-in payload hash and the
    caller-reviewed hash must match, the dedicated confirmation token is
    mandatory, and timing cannot be reduced below the 50 ms validation rate.
    """
    if plan.sha256 != NOTE_WRITE_VALIDATION_SHA256:
        raise ValueError("payload is not the fixed Note 35->36 validation stream")
    if expected_sha256.casefold() != NOTE_WRITE_VALIDATION_SHA256:
        raise ValueError("expected SHA-256 does not match the fixed validation stream")
    if confirmation != "I_AUTHORIZE_DDTI_NOTE_35_TO_36":
        raise ValueError("dedicated Note 35->36 confirmation token is required")
    if inter_message_ms < 50:
        raise ValueError("validation transfer requires at least 50 ms between messages")

    import mido

    name = _resolve_output(output_query)
    frames = parse_stream(plan.raw)
    with mido.open_output(name) as output:
        for frame in frames:
            output.send(mido.Message("sysex", data=frame.data))
            time.sleep(inter_message_ms / 1000)
    return DDTiTransferResult(name, len(frames), len(plan.raw), plan.sha256)


def send_settings_write_validation(
    golden_raw: bytes,
    output_query: str,
    *,
    expected_sha256: str,
    confirmation: str,
    inter_message_ms: float = 50,
) -> DDTiTransferResult:
    """Send only the payload deterministically built from the factory golden."""
    plan = build_settings_write_validation_plan(golden_raw)
    if expected_sha256.casefold() != plan.sha256:
        raise ValueError("expected SHA-256 does not match the fixed settings validation stream")
    if confirmation != "I_AUTHORIZE_DDTI_PROGRAM_0_GAIN_16":
        raise ValueError("dedicated Program 0 / Gain 16 confirmation token is required")
    if inter_message_ms < 50:
        raise ValueError("validation transfer requires at least 50 ms between messages")

    import mido

    name = _resolve_output(output_query)
    frames = parse_stream(plan.raw)
    with mido.open_output(name) as output:
        for frame in frames:
            output.send(mido.Message("sysex", data=frame.data))
            time.sleep(inter_message_ms / 1000)
    return DDTiTransferResult(name, len(frames), len(plan.raw), plan.sha256)


def send_safe_configuration(
    source_raw: bytes,
    candidate_raw: bytes,
    output_query: str,
    *,
    expected_sha256: str,
    confirmation: str,
    inter_message_ms: float = 50,
) -> DDTiTransferResult:
    """Send a candidate only after safe-field validation and hash review."""
    plan = build_safe_write_plan(source_raw, candidate_raw)
    if expected_sha256.casefold() != plan.sha256:
        raise ValueError("expected SHA-256 does not match the validated candidate")
    if confirmation != "I_AUTHORIZE_DDTI_CONFIRMED_FIELDS":
        raise ValueError("confirmed-fields write confirmation token is required")
    if inter_message_ms < 50:
        raise ValueError("DDTi writes require at least 50 ms between messages")

    import mido

    name = _resolve_output(output_query)
    frames = parse_stream(plan.raw)
    with mido.open_output(name) as output:
        for frame in frames:
            output.send(mido.Message("sysex", data=frame.data))
            time.sleep(inter_message_ms / 1000)
    return DDTiTransferResult(name, len(frames), len(plan.raw), plan.sha256)


def send_reviewed_transfer(
    plan: DDTiTransferPlan,
    output_query: str,
    *,
    expected_sha256: str,
    confirmation: str,
    inter_message_ms: float = 10,
) -> DDTiTransferResult:
    """Raise unconditionally: the legacy DDTi sender is not validated.

    Parameters are intentionally retained as an audit-friendly future API, but
    this function must not import ``mido``, resolve an output, or send a byte.
    Unrestricted raw replay stays unavailable even though the former
    ``0x7f -> 0x00`` difference is now understood. Callers must use
    :func:`send_safe_configuration`, which validates source-relative offsets.
    """
    del plan, output_query, expected_sha256, confirmation, inter_message_ms
    raise ProtocolNotValidatedError(
        "unrestricted raw DDTi writes are disabled; use the confirmed-fields safe writer"
    )
