"""Validated *offline* plans for the future DDTi SysEx transfer path.

This module intentionally does not import MIDI libraries or open output ports.
It establishes the invariant a hardware sender will require: only a complete,
lossless legacy DDTi dump can ever be considered for transfer.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from .protocol import DDTiDump, decode_dump
from .sysex import parse_stream


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


def _resolve_output(query: str) -> str:
    import mido

    names = list(mido.get_output_names())
    exact = [name for name in names if name.casefold() == query.casefold()]
    matches = exact or [name for name in names if query.casefold() in name.casefold()]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one MIDI output matching {query!r}; found {matches}")
    return matches[0]


def send_reviewed_transfer(
    plan: DDTiTransferPlan,
    output_query: str,
    *,
    expected_sha256: str,
    confirmation: str,
    inter_message_ms: float = 10,
) -> DDTiTransferResult:
    """Transmit a previously reviewed complete dump after explicit confirmation.

    The caller must supply the exact plan SHA-256 and confirmation phrase. This
    is deliberately a separate operation from plan construction so a GUI/API
    cannot transmit merely by staging an edit.
    """
    if expected_sha256.casefold() != plan.sha256:
        raise ValueError("expected SHA-256 does not match the reviewed transfer plan")
    if confirmation != "I_UNDERSTAND_DDTI_WRITE":
        raise ValueError("explicit confirmation phrase is required")
    if inter_message_ms < 0:
        raise ValueError("inter_message_ms must be non-negative")
    import mido

    name = _resolve_output(output_query)
    frames = parse_stream(plan.raw)
    with mido.open_output(name) as output:
        for frame in frames:
            output.send(mido.Message("sysex", data=frame.data))
            if inter_message_ms:
                time.sleep(inter_message_ms / 1000)
    return DDTiTransferResult(name, len(frames), len(plan.raw), plan.sha256)
