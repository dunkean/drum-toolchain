"""Apply named musical-role templates to an explicit DDTi input layout.

The DDTi dump knows numbered electrical inputs, not the musician's physical
kit. A GM or SD3 template therefore never guesses that Input 1 is a kick or
that a ring is a rim. The user-owned layout document supplies that missing
relationship. A template may also declare one stable output channel, after
which only the already-confirmed per-zone channel/note bytes are changed in an
offline staged configuration.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from .models import DDTiConfiguration


ROLE_TEMPLATE_FORMAT = "ddti-note-role-template/v1"
INPUT_LAYOUT_FORMAT = "ddti-input-layout/v1"


def _sequence(value: object, message: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(message)
    return value


def _role_note(template: Mapping[str, object], path: object) -> int:
    if not isinstance(path, str) or path.count(".") != 1:
        raise ValueError("layout binding role must be '<role>.<articulation>'")
    role, articulation = path.split(".", 1)
    roles = template.get("roles")
    if not isinstance(roles, Mapping):
        raise ValueError("role template roles must be an object")
    role_entry = roles.get(role)
    if not isinstance(role_entry, Mapping):
        raise ValueError(f"role template does not define role {role!r}")
    note = role_entry.get(articulation)
    if type(note) is not int or not 0 <= note <= 127:
        raise ValueError(f"role template does not define a MIDI note for {path!r}")
    return note


def apply_role_template(
    configuration: DDTiConfiguration,
    template: Mapping[str, object],
    layout: Mapping[str, object],
) -> DDTiConfiguration:
    """Stage one role-template layout mapping onto explicitly selected kits.

    Both inputs are ordinary YAML/JSON mappings. Nothing here opens MIDI or
    changes a captured source file. The layout chooses kits, physical input
    number, zone and a dotted semantic role from the named template.
    """
    if template.get("format") != ROLE_TEMPLATE_FORMAT:
        raise ValueError(f"role template format must be {ROLE_TEMPLATE_FORMAT!r}")
    if layout.get("format") != INPUT_LAYOUT_FORMAT:
        raise ValueError(f"input layout format must be {INPUT_LAYOUT_FORMAT!r}")
    kit_entries = _sequence(layout.get("kits"), "input layout kits must be a list")
    kit_numbers: list[int] = []
    available_kits = {kit.number for kit in configuration.kits}
    for kit in kit_entries:
        if type(kit) is not int or kit not in available_kits:
            raise ValueError("input layout contains an unknown kit")
        if kit in kit_numbers:
            raise ValueError(f"input layout repeats kit {kit}")
        kit_numbers.append(kit)
    if not kit_numbers:
        raise ValueError("input layout must select at least one kit")
    channel = template.get("channel")
    if channel is not None and (type(channel) is not int or not 1 <= channel <= 16):
        raise ValueError("role template channel must be an integer in 1..16")

    bindings = _sequence(layout.get("bindings"), "input layout bindings must be a list")
    staged_bindings: list[tuple[int, str, int]] = []
    used_targets: set[tuple[int, str]] = set()
    for binding in bindings:
        if not isinstance(binding, Mapping):
            raise ValueError("each input layout binding must be an object")
        input_number = binding.get("input")
        zone = binding.get("zone")
        if type(input_number) is not int or not 1 <= input_number <= 10:
            raise ValueError("input layout binding input must be 1..10")
        if zone not in {"tip", "ring"}:
            raise ValueError("input layout binding zone must be 'tip' or 'ring'")
        target = (input_number, zone)
        if target in used_targets:
            raise ValueError(f"input layout repeats Input {input_number} {zone}")
        used_targets.add(target)
        staged_bindings.append((input_number, zone, _role_note(template, binding.get("role"))))

    updated = configuration
    for kit in kit_numbers:
        for input_number, zone, note in staged_bindings:
            updated = updated.with_zone(kit, input_number, zone, channel=channel, note=note)
    return updated
