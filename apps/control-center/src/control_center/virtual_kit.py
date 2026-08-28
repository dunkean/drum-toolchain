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
    physical_instrument: str | None
    physical_zone: str | None
    raw_notes: Mapping[str, int]
    logical_sound: str | None
    ddrum4_slot: int | None
    ddrum4_sound_id: str | None
    ddrum4_note_p: int | None
    ddrum4_note: int | None
    ddrum4_variations: tuple[tuple[int, str | None], ...]
    ddrum4_layer_candidates: tuple[MatrixLayer, ...]
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

    @property
    def hardware_summary(self) -> str:
        """Compact source-module and physical pad/zone label for the UI."""
        source = next(iter(self.raw_notes), None)
        source_label = {"edrumin": "eDRUMin", "ddti": "DDTi", "ddrum4": "DDrum4"}.get(
            source or "", source or "unknown source",
        )
        if self.physical_instrument and self.physical_zone:
            return f"{source_label} · {self.physical_instrument} / {self.physical_zone}"
        return f"{source_label} · binding missing"

    @property
    def raw_note_summary(self) -> str:
        """Show exact decoder notes without reserving one column per module."""
        labels = {"edrumin": "eDRUMin", "ddti": "DDTi", "ddrum4": "DDrum4"}
        return " · ".join(f"{labels.get(source, source)} N{note}" for source, note in self.raw_notes.items()) or "MISSING"

    @property
    def ddrum4_content_summary(self) -> str:
        """Describe the declared DDrum4 content for this NOTE P only.

        A bank manifest records mappings and shared samples, not its exact
        runtime random/velocity-selection algorithm.  The summary therefore
        exposes candidates, variations, pitch and RR facts without claiming
        which candidate will be chosen by a particular hit.
        """
        if self.ddrum4_note_p is None or self.ddrum4_sound_id is None:
            return "No linked DDrum4 bank content."
        variations = ", ".join(
            f"V{number}" + (f" {name}" if name else "") for number, name in self.ddrum4_variations
        ) or "no declared variation label"
        if not self.ddrum4_layer_candidates:
            return f"{self.ddrum4_sound_id} P{self.ddrum4_note_p} · {variations} · no declared layer candidate"
        candidates: list[str] = []
        for layer in self.ddrum4_layer_candidates:
            facts = [f"L{layer.index}"]
            if layer.source:
                facts.append(layer.source)
            if layer.velocity is not None:
                facts.append(f"V{layer.velocity}")
            if layer.variation:
                facts.append("variation " + "/".join(str(number) for number in layer.variation))
            if layer.pitch is not None:
                facts.append(f"pitch {layer.pitch:+d}")
            if layer.round_robin is not None:
                facts.append(f"RR{layer.round_robin}")
            if layer.sample is not None:
                facts.append(f"sample {layer.sample}")
            candidates.append(" · ".join(facts))
        return f"{self.ddrum4_sound_id} P{self.ddrum4_note_p} · {variations}\nCandidates (declared, not selected):\n" + "\n".join(candidates)


def build_virtual_kit(simulator: RigSimulator) -> tuple[VirtualKitRow, ...]:
    """Resolve every declared physical event against the simulator's state."""
    rows: list[VirtualKitRow] = []
    matrix: Ddrum4KitMatrix | None = None
    if simulator.project.ddrum4_bank_facts is not None:
        matrix = load_kit_matrix(simulator.project.ddrum4_bank_facts.manifest)
    for physical in simulator.project.physical_events:
        binding = simulator.project.physical_bindings.get(physical, {})
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
        note_p = (ddrum["note"] - bank_sound.note_base + 1) if bank_sound and bank_sound.note_base is not None else None
        candidates = tuple(layer for layer in (bank_sound.layers if bank_sound else ()) if layer.position == note_p)
        rows.append(VirtualKitRow(
            physical=physical,
            physical_instrument=binding.get("instrument"), physical_zone=binding.get("zone"),
            raw_notes=raw_notes, logical_sound=logical,
            ddrum4_slot=bank_sound.slot if bank_sound else None, ddrum4_sound_id=bank_sound.sound_id if bank_sound else None,
            ddrum4_note_p=note_p, ddrum4_variations=bank_sound.variations if bank_sound else (),
            ddrum4_layer_candidates=candidates,
            ddrum4_note=ddrum.get("note"), sd3_note=sd3.get("note"), sd3_channel=sd3.get("channel", 10),
            drumgizmo_note=gizmo.get("note"), drumgizmo_channel=gizmo.get("channel", 10),
            drumgizmo_instrument=gizmo.get("instrument"), drumgizmo_articulation=gizmo.get("articulation"),
        ))
    return tuple(rows)
