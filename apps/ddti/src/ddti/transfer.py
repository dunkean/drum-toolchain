"""Validated *offline* plans for the future DDTi SysEx transfer path.

This module intentionally does not import MIDI libraries or open output ports.
It establishes the invariant a hardware sender will require: only a complete,
lossless legacy DDTi dump can ever be considered for transfer.

An exact golden-dump round trip was attempted on 2026-08-19.  The DDTi
normalised one still-unexplained byte in each of the first twenty kit frames.
Consequently the sender is deliberately hard-disabled until that field and
the device's acceptance rules are understood.  A review plan remains useful
for offline configuration work and future validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

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
            "hardware_write": "not implemented",
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


def build_transfer_plan(raw: bytes) -> DDTiTransferPlan:
    """Validate a complete 42-frame DDTi dump for offline transfer review."""
    dump = decode_dump(raw)
    if dump.family_indexes() != _COMPLETE_FAMILIES:
        raise ValueError("a DDTi transfer plan requires all 21 kit and 21 global-trigger packets")
    return DDTiTransferPlan(dump)


def build_transfer_plan_from_file(path: Path) -> DDTiTransferPlan:
    return build_transfer_plan(path.read_bytes())


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
    The exact full golden dump produced a repeatable ``0x7f -> 0x00`` change at
    family-01 body offset ``+0x41`` for indexes 0--19.  It is not safe to infer
    that this is cosmetic or that other staged fields can be restored.
    """
    del plan, output_query, expected_sha256, confirmation, inter_message_ms
    raise ProtocolNotValidatedError(
        "DDTi writes are disabled: the 2026-08-19 full-dump round trip changed "
        "family-01 body byte +0x41 in records 0--19"
    )
