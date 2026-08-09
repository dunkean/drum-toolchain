from __future__ import annotations

from .project import KitProject


def markdown(project: KitProject) -> str:
    used = project.allocated_blocks()
    lines = [
        f"# {project.raw.get('project', {}).get('name', project.path.stem)} — kit report",
        "",
        f"Memory allocation: **{used} / {project.memory_blocks} blocks** ({project.memory_blocks - used} free).",
        "",
        "## Sound allocation",
        "",
        "| Sound | Category | Reserved blocks | Actual blocks | Samples | Layers | Variations |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for sound in project.sounds:
        lines.append(f"| {sound.identifier} | {sound.category} | {sound.allocation_blocks} | {sound.actual_blocks if sound.actual_blocks is not None else 'pending encode'} | {sound.sample_slots} | {sound.layers} | {sound.variations} |")
    lines.extend(["", "## Physical articulation routing", "", "| Articulation | Source | Input | ddrum output | Sound | Position | Output velocity |", "| --- | --- | --- | --- | --- | ---: | --- |"])
    for route in project.routes:
        lines.append(f"| {route.articulation} | {route.source} | ch {route.channel}, note {route.input_note} | ch {project.output_channel}, note {route.output_note} | {route.sound or 'pending'} | {route.position or '-'} | {route.output_velocity_min}–{route.output_velocity_max} |")
    return "\n".join(lines) + "\n"
