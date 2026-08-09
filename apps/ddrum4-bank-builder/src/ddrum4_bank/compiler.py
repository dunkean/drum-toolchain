"""Compile declared nested articulation layouts into the firmware contract."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import yaml

from .nested import NestedRoute, NestedSound
from .routing_contract import ContractRoute, RoutingContract


@dataclass(frozen=True)
class CompiledNestedSound:
    identifier: str
    output_note: int
    note_p: int
    routes: tuple[NestedRoute, ...]


@dataclass(frozen=True)
class Compilation:
    bank_id: str
    sounds: tuple[CompiledNestedSound, ...]
    contract: RoutingContract
    warnings: tuple[str, ...]

    def report(self) -> str:
        lines = ["# Nested Sound Compilation", "", f"Bank: **{self.bank_id}**", "", "## Sound allocation", "", "| Sound | MIDI note | Note P | Articulation | Position | Samples | Layers |", "| --- | ---: | ---: | --- | ---: | ---: | ---: |"]
        for sound in self.sounds:
            for route in sound.routes:
                lines.append(f"| {sound.identifier} | {sound.output_note} | {sound.note_p} | {route.articulation} | {route.position} | {route.sample_slots} | {route.layers} |")
        lines.extend(["", "## Routing coverage", "", "| Articulation | Source input | DDrum4 output | Sound | Position |", "| --- | --- | --- | --- | ---: |"])
        for route in self.contract.routes:
            lines.append(f"| {route.identifier} | {route.source} note {route.input_note} | note {route.output_note} | {route.sound_id} | {route.position or '-'} |")
        if self.warnings:
            lines.extend(["", "## Warnings", ""])
            lines.extend(f"- {warning}" for warning in self.warnings)
        return "\n".join(lines) + "\n"


def _integer(value: Any, label: str, low: int, high: int) -> int:
    if not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label} must be an integer in {low}..{high}")
    return value


def compile_nested(document: dict[str, Any]) -> Compilation:
    """Compile a fully declared layout; no module-specific IDs are guessed."""
    bank = document.get("bank")
    midi = document.get("midi")
    declared_sounds = document.get("sounds")
    if not isinstance(bank, dict) or not isinstance(bank.get("id"), str) or not bank["id"]:
        raise ValueError("bank.id is required")
    if not isinstance(midi, dict) or not isinstance(declared_sounds, list) or not declared_sounds:
        raise ValueError("midi and non-empty sounds are required")
    sources_raw = midi.get("sources")
    if not isinstance(sources_raw, dict):
        raise ValueError("midi.sources is required")
    sources = {name: _integer(spec.get("channel") if isinstance(spec, dict) else None, f"source {name} channel", 1, 16) for name, spec in sources_raw.items()}
    output_channel = _integer(midi.get("ddrum_output_channel"), "midi.ddrum_output_channel", 1, 16)
    compiled_sounds: list[CompiledNestedSound] = []
    contract_routes: list[ContractRoute] = []
    warnings: list[str] = []
    for declared in declared_sounds:
        if not isinstance(declared, dict):
            raise ValueError("each sound must be a mapping")
        identifier = declared.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("sound id is required")
        output_note = _integer(declared.get("output_note"), f"{identifier}.output_note", 0, 127)
        note_p = _integer(declared.get("note_p"), f"{identifier}.note_p", 1, 8)
        routes_raw = declared.get("routes")
        if not isinstance(routes_raw, list) or not routes_raw:
            raise ValueError(f"{identifier}.routes is required")
        nested_routes: list[NestedRoute] = []
        for entry in routes_raw:
            if not isinstance(entry, dict):
                raise ValueError(f"{identifier}: route must be a mapping")
            route_id = entry.get("id")
            source = entry.get("source")
            if not isinstance(route_id, str) or not route_id or source not in sources:
                raise ValueError(f"{identifier}: each route needs an id and known source")
            position = _integer(entry.get("position"), f"{route_id}.position", 1, 8)
            nested = NestedRoute(route_id, position, _integer(entry.get("sample_slots"), f"{route_id}.sample_slots", 1, 10), _integer(entry.get("layers"), f"{route_id}.layers", 1, 10), _integer(entry.get("priority", 0), f"{route_id}.priority", 0, 1000))
            nested_routes.append(nested)
            velocity = entry.get("velocity", {})
            if not isinstance(velocity, dict):
                raise ValueError(f"{route_id}.velocity must be a mapping")
            contract_routes.append(ContractRoute(
                route_id, source, _integer(entry.get("input_note"), f"{route_id}.input_note", 0, 127), output_note, identifier, position,
                _integer(velocity.get("input_min", 1), f"{route_id}.velocity.input_min", 1, 127),
                _integer(velocity.get("input_max", 127), f"{route_id}.velocity.input_max", 1, 127),
                _integer(velocity.get("output_min", 1), f"{route_id}.velocity.output_min", 1, 127),
                _integer(velocity.get("output_max", 127), f"{route_id}.velocity.output_max", 1, 127),
            ))
        layout = NestedSound(identifier, note_p, tuple(nested_routes))
        errors = layout.validate()
        if errors:
            raise ValueError(f"{identifier}: " + "; ".join(errors))
        if sum(route.sample_slots for route in nested_routes) == 10 or sum(route.layers for route in nested_routes) == 10:
            warnings.append(f"{identifier}: nested layout consumes its entire ten-slot/layer budget")
        compiled_sounds.append(CompiledNestedSound(identifier, output_note, note_p, tuple(nested_routes)))
    if len({sound.identifier for sound in compiled_sounds}) != len(compiled_sounds):
        raise ValueError("duplicate sound id")
    return Compilation(bank["id"], tuple(compiled_sounds), RoutingContract(bank["id"], output_channel, sources, document.get("hihat", {}), tuple(contract_routes)), tuple(warnings))


def compile_nested_file(path: Path) -> Compilation:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("nested plan root must be a mapping")
    return compile_nested(document)


def write_compilation(compilation: Compilation, contract_path: Path, report_path: Path) -> None:
    if contract_path.exists() or report_path.exists():
        raise FileExistsError("refusing to overwrite nested compilation output")
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    compilation.contract.write(contract_path)
    report_path.write_text(compilation.report(), encoding="utf-8")
