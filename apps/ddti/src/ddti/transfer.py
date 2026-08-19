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

from .protocol import DDTiDump, decode_dump
from .device import ProtocolNotValidatedError


_COMPLETE_FAMILIES = {1: tuple(range(21)), 2: tuple(range(21))}


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
