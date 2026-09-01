"""Build deterministic Superior Drummer 3 e-drum mapping presets."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml


_IDENTIFIER = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-+")


def _checked_name(value: Any, label: str) -> str:
    name = str(value)
    if not name or any(character not in _IDENTIFIER and character != " " for character in name):
        raise ValueError(f"{label} contains unsupported SD3 preset characters: {name!r}")
    return name


def _source_plan_notes(profile_path: Path, profile: dict[str, Any]) -> tuple[set[int], str | None]:
    source_name = profile.get("source_plan")
    if not source_name:
        expected = profile.get("expected_input_notes")
        if not isinstance(expected, list):
            raise ValueError("profile requires source_plan or expected_input_notes")
        return {int(note) for note in expected}, None
    source = (profile_path.parent / str(source_name)).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"SD3 mapping source plan is missing: {source}")
    payload = source.read_bytes()
    plan = yaml.safe_load(payload.decode("utf-8"))
    if not isinstance(plan, dict) or plan.get("kind") != "sd3-megakit-plan":
        raise ValueError("source_plan must be an sd3-megakit-plan")
    rows = list(plan.get("articulations", []))
    if profile.get("include_positional_reserve", False):
        rows.extend(plan.get("positional_reserve", []))
    return {int(row["note"]) for row in rows}, sha256(payload).hexdigest()


def build_sd3_edrum_preset(profile_path: Path, output: Path, force: bool = False) -> dict[str, Any]:
    """Render a reviewed YAML map to SD3's text EdrumPresets format."""
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    if not isinstance(profile, dict) or profile.get("kind") != "sd3-edrum-preset":
        raise ValueError("profile must be an sd3-edrum-preset document")
    if output.exists() and not force:
        raise FileExistsError(f"output exists (pass force to replace generated output): {output}")
    name = _checked_name(profile.get("name", ""), "name")
    expected_notes, source_plan_hash = _source_plan_notes(profile_path, profile)

    mappings: dict[int, tuple[str, int]] = {}
    for row in profile.get("mappings", []):
        if not isinstance(row, dict) or not isinstance(row.get("input_notes"), list):
            raise ValueError("each mapping requires an input_notes list")
        pad = _checked_name(row.get("pad", ""), "pad")
        standard_note = int(row["standard_note"])
        if not 0 <= standard_note <= 127:
            raise ValueError(f"standard_note must be 0..127 for {pad}")
        for value in row["input_notes"]:
            note = int(value)
            if not 0 <= note <= 127:
                raise ValueError(f"input note must be 0..127: {note}")
            if note in mappings:
                raise ValueError(f"duplicate SD3 e-drum input note: {note}")
            mappings[note] = (pad, standard_note)
    actual_notes = set(mappings)
    if actual_notes != expected_notes:
        missing = sorted(expected_notes - actual_notes)
        extra = sorted(actual_notes - expected_notes)
        raise ValueError(f"SD3 e-drum map coverage mismatch; missing={missing}, extra={extra}")

    controller_lines: list[str] = []
    controller_inputs: set[int] = set()
    for row in profile.get("controllers", []):
        input_cc = int(row["input_cc"])
        standard_cc = int(row["standard_cc"])
        pad = _checked_name(row.get("pad", ""), "controller pad")
        if not 0 <= input_cc <= 127 or not 0 <= standard_cc <= 127:
            raise ValueError("controller numbers must be 0..127")
        if input_cc in controller_inputs:
            raise ValueError(f"duplicate SD3 e-drum input controller: {input_cc}")
        controller_inputs.add(input_cc)
        controller_lines.append(f"usermap {128 + input_cc} {pad} {128 + standard_cc}")

    lines = [f'"{name}" {{']
    lines.extend(
        f"usermap {note} {pad} {standard_note} -1"
        for note, (pad, standard_note) in sorted(mappings.items())
    )
    lines.extend(controller_lines)
    lines.extend([
        "Trafo 129 {", "curve {", "0 0 0", "1 0.0629921 0.0629921",
        "2 0.23622 0.23622", "3 0.472441 0.472441", "4 0.708661 0.708661",
        "5 0.826772 0.826772", "6 0.944882 0.944882", "7 0.992126 0.992126",
        "8 1 1", "}", "}",
        "Trafo 132 {", "curve {", "0 0 0", "1 0.0629921 0.0629921",
        "2 0.23622 0.23622", "3 0.472441 0.472441", "4 0.708661 0.708661",
        "5 0.826772 0.826772", "6 0.944882 0.944882", "7 0.992126 0.992126",
        "8 1 1", "}", "}",
        "Trafo 144 {", "curve {", "0 0 0", "1 0.503937 0.503937", "2 1 1", "}", "}",
        "StoredTrafo 144 {", "lo 0 20", "}",
        "StoredTrafo 129 {", "lo 0 20", "}",
        "StoredTrafo 132 {", "lo 0 20", "}",
        "ShowNonSpec",
        f"HatsSplash 1 {int(profile.get('hats_splash_note', 67))}",
        "HatsPedalMode hhLibDefault",
        "}",
    ])
    payload = ("\r\n".join(lines) + "\r\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    return {
        "output": str(output),
        "name": name,
        "mapping_count": len(mappings),
        "controller_count": len(controller_lines),
        "input_notes": sorted(mappings),
        "source_plan_sha256": source_plan_hash,
        "sha256": sha256(payload).hexdigest(),
        "hardware_io": "disabled",
    }
