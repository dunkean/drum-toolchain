"""Validated *offline* plans for the future DDTi SysEx transfer path.

This module intentionally does not import MIDI libraries or open output ports.
It establishes the invariant a hardware sender will require: only a complete,
lossless legacy DDTi dump can ever be considered for transfer.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .protocol import DDTiDump, decode_dump


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


def build_transfer_plan(raw: bytes) -> DDTiTransferPlan:
    """Validate a complete 42-frame DDTi dump for offline transfer review."""
    dump = decode_dump(raw)
    if dump.family_indexes() != _COMPLETE_FAMILIES:
        raise ValueError("a DDTi transfer plan requires all 21 kit and 21 global-trigger packets")
    return DDTiTransferPlan(dump)


def build_transfer_plan_from_file(path: Path) -> DDTiTransferPlan:
    return build_transfer_plan(path.read_bytes())
