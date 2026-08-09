"""Load an editable bank-planning manifest and render allocation reports."""
from __future__ import annotations

from pathlib import Path

import yaml

from .allocator import AllocationOption, AllocationResult, compare_allocations


def load_options(path: Path) -> tuple[int, tuple[AllocationOption, ...]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("bank"), dict):
        raise ValueError("bank plan must contain a bank mapping")
    bank = document["bank"]
    memory = bank.get("planning_memory_blocks")
    components = document.get("logical_components")
    if not isinstance(memory, int) or memory < 1:
        raise ValueError("bank.planning_memory_blocks must be a positive integer")
    if not isinstance(components, list) or not components:
        raise ValueError("bank plan must contain logical_components")
    options: list[AllocationOption] = []
    for component in components:
        if not isinstance(component, dict) or not isinstance(component.get("id"), str):
            raise ValueError("each logical component needs an id")
        logical_id = component["id"]
        priority = component.get("priority")
        group = component.get("planned_sound_group")
        variants = component.get("options")
        if not isinstance(priority, int) or not isinstance(group, str) or not isinstance(variants, list):
            raise ValueError(f"{logical_id}: priority, planned_sound_group, and options are required")
        for variant in variants:
            if not isinstance(variant, dict):
                raise ValueError(f"{logical_id}: option must be a mapping")
            options.append(AllocationOption(
                identifier=variant["id"], logical_id=logical_id, sound_id=group,
                quality=variant["quality"], priority=priority, sample_slots=variant["sample_slots"],
                layers=variant["layers"], estimated_blocks=variant["estimated_blocks"],
                source_take_ids=tuple(variant["source_take_ids"]),
            ))
    return memory, tuple(options)


def render_comparison(results: tuple[AllocationResult, AllocationResult]) -> str:
    lines = ["# DDrum4 Planning Allocation", "", "Estimated blocks are planning estimates, not encoded DDrum4 block counts.", ""]
    for result in results:
        lines.extend([f"## {result.strategy}", "", f"Estimated blocks: **{result.estimated_blocks}**", "", "| Logical articulation | Option | Planned sound group | Quality |", "| --- | --- | --- | ---: |"])
        for option in result.selected:
            lines.append(f"| {option.logical_id} | {option.identifier} | {option.sound_id} | {option.quality} |")
        if result.warnings:
            lines.extend(["", "Warnings:"])
            lines.extend(f"- {warning}" for warning in result.warnings)
        lines.append("")
    return "\n".join(lines)


def compare_plan(path: Path) -> tuple[AllocationResult, AllocationResult]:
    memory, options = load_options(path)
    return compare_allocations(options, memory)
