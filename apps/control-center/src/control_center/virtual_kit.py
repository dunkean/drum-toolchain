"""Renderer-parity view model for the Control Center virtual-kit workspace.

The view model has no Qt, MIDI or audio dependency.  It is intentionally built
from the validated ``RigProject`` so a GUI table, a CLI report and a future
hardware simulator can all answer the same question: does this physical
articulation resolve to one logical sound with all three renderer targets?
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .ddrum4_matrix import Ddrum4KitMatrix, load_kit_matrix
from .simulator import RigSimulator, SimulationError


@dataclass(frozen=True)
class VirtualKitRow:
    """One physical articulation resolved in the current Scene/VP state."""

    physical: str
    raw_notes: Mapping[str, int]
    logical_sound: str | None
    ddrum4_slot: int | None
    ddrum4_sound_id: str | None
    ddrum4_note_p: int | None
    ddrum4_note: int | None
    sd3_note: int | None
    sd3_channel: int | None
    drumgizmo_note: int | None
    drumgizmo_channel: int | None
    drumgizmo_instrument: str | None
    drumgizmo_articulation: str | None

    @property
    def complete(self) -> bool:
        """Whether all three renderer maps are usable for a Note-On hit."""
        return (self.logical_sound is not None and self.ddrum4_note is not None
                and self.sd3_note is not None and self.drumgizmo_note is not None
                and self.drumgizmo_instrument is not None and self.drumgizmo_articulation is not None)

    @property
    def status(self) -> str:
        return "complete" if self.complete else "missing renderer destination"


def build_virtual_kit(simulator: RigSimulator) -> tuple[VirtualKitRow, ...]:
    """Resolve every declared physical event against the simulator's state."""
    rows: list[VirtualKitRow] = []
    matrix: Ddrum4KitMatrix | None = None
    if simulator.project.ddrum4_bank_facts is not None:
        matrix = load_kit_matrix(simulator.project.ddrum4_bank_facts.manifest)
    for physical in simulator.project.physical_events:
        raw_notes = {
            decoder.source: decoder.match["note"]
            for decoder in simulator.project.source_decoders
            if decoder.physical == physical and decoder.message_type == "note"
        }
        try:
            logical = simulator._logical_target(physical)
        except SimulationError:
            logical = None
        ddrum = simulator.project.renderers["ddrum4"].get(logical, {}) if logical else {}
        sd3 = simulator.project.renderers["sd3"].get(logical, {}) if logical else {}
        gizmo = simulator.project.renderers["drumgizmo"].get(logical, {}) if logical else {}
        bank_sound = matrix.sound_for_note(ddrum["note"]) if matrix is not None and ddrum.get("note") is not None else None
        rows.append(VirtualKitRow(
            physical=physical, raw_notes=raw_notes, logical_sound=logical,
            ddrum4_slot=bank_sound.slot if bank_sound else None, ddrum4_sound_id=bank_sound.sound_id if bank_sound else None,
            ddrum4_note_p=(ddrum["note"] - bank_sound.note_base + 1) if bank_sound and bank_sound.note_base is not None else None,
            ddrum4_note=ddrum.get("note"), sd3_note=sd3.get("note"), sd3_channel=sd3.get("channel", 10),
            drumgizmo_note=gizmo.get("note"), drumgizmo_channel=gizmo.get("channel", 10),
            drumgizmo_instrument=gizmo.get("instrument"), drumgizmo_articulation=gizmo.get("articulation"),
        ))
    return tuple(rows)
