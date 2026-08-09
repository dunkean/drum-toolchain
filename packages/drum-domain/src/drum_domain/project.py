from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ProjectError(ValueError):
    pass


def _number(value: Any, name: str, low: int, high: int) -> int:
    if not isinstance(value, int) or not low <= value <= high:
        raise ProjectError(f"{name} must be an integer in {low}..{high}")
    return value


@dataclass(frozen=True)
class Route:
    identifier: str
    source: str
    channel: int
    input_note: int
    output_note: int
    articulation: str
    sound: str
    position: int | None
    input_velocity_min: int
    input_velocity_max: int
    output_velocity_min: int
    output_velocity_max: int


@dataclass(frozen=True)
class Sound:
    identifier: str
    category: str
    allocation_blocks: int
    actual_blocks: int | None
    sample_slots: int
    layers: int
    variations: int
    description: str


@dataclass
class KitProject:
    path: Path
    raw: dict[str, Any]
    memory_blocks: int
    output_channel: int
    sources: dict[str, int]
    sounds: list[Sound]
    routes: list[Route]

    @classmethod
    def load(cls, path: Path) -> "KitProject":
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise ProjectError(f"cannot read {path}: {error}") from error
        except yaml.YAMLError as error:
            raise ProjectError(f"invalid YAML in {path}: {error}") from error
        if not isinstance(raw, dict):
            raise ProjectError("manifest root must be a mapping")
        module = raw.get("module", {})
        midi = raw.get("midi", {})
        source_map = midi.get("sources", {})
        if not isinstance(source_map, dict):
            raise ProjectError("midi.sources must be a mapping")
        sources = {name: _number(value.get("channel"), f"source {name} channel", 1, 16)
                   for name, value in source_map.items() if isinstance(value, dict)}
        if not sources:
            raise ProjectError("at least one MIDI source is required")
        sounds: list[Sound] = []
        for item in raw.get("sounds", []):
            if not isinstance(item, dict):
                raise ProjectError("each sound must be a mapping")
            identifier = item.get("id")
            if not isinstance(identifier, str) or not identifier:
                raise ProjectError("sound id is required")
            actual = item.get("actual_blocks")
            sounds.append(Sound(
                identifier, str(item.get("category", "PERC")),
                _number(item.get("allocation_blocks"), f"sound {identifier} allocation_blocks", 0, 8192),
                _number(actual, f"sound {identifier} actual_blocks", 0, 8192) if actual is not None else None,
                _number(item.get("sample_slots", 0), f"sound {identifier} sample_slots", 0, 10),
                _number(item.get("layers", 0), f"sound {identifier} layers", 0, 10),
                _number(item.get("variations", 0), f"sound {identifier} variations", 0, 10),
                str(item.get("description", "")),
            ))
        routes: list[Route] = []
        for item in raw.get("routes", []):
            if not isinstance(item, dict):
                raise ProjectError("each route must be a mapping")
            source = item.get("source")
            if source not in sources:
                raise ProjectError(f"route {item.get('id', '?')}: unknown source {source!r}")
            target = item.get("target", {})
            if not isinstance(target, dict):
                raise ProjectError("route target must be a mapping")
            velocity = target.get("velocity", {})
            if not isinstance(velocity, dict):
                raise ProjectError("route target.velocity must be a mapping")
            routes.append(Route(
                str(item.get("id", f"route_{len(routes) + 1}")), source, sources[source],
                _number(item.get("input_note"), "route input_note", 0, 127),
                _number(target.get("output_note"), "route target.output_note", 0, 127),
                str(item.get("articulation", item.get("id", ""))), str(target.get("sound", "")),
                _number(target["position"], "route target.position", 1, 8) if "position" in target else None,
                _number(velocity.get("input_min", 1), "route target.velocity.input_min", 1, 127),
                _number(velocity.get("input_max", 127), "route target.velocity.input_max", 1, 127),
                _number(velocity.get("output_min", 1), "route target.velocity.output_min", 1, 127),
                _number(velocity.get("output_max", 127), "route target.velocity.output_max", 1, 127),
            ))
        return cls(path, raw, _number(module.get("memory_blocks", 8192), "module.memory_blocks", 1, 65535),
                   _number(midi.get("ddrum_output_channel", 10), "midi.ddrum_output_channel", 1, 16),
                   sources, sounds, routes)

    def validate(self) -> list[str]:
        errors: list[str] = []
        ids = [sound.identifier for sound in self.sounds]
        if len(ids) != len(set(ids)):
            errors.append("duplicate sound id")
        total = sum(sound.allocation_blocks for sound in self.sounds)
        if total > self.memory_blocks:
            errors.append(f"allocated {total} blocks exceeds module budget {self.memory_blocks}")
        for sound in self.sounds:
            if sound.actual_blocks is not None and sound.actual_blocks > sound.allocation_blocks:
                errors.append(f"{sound.identifier}: actual {sound.actual_blocks} > allocation {sound.allocation_blocks}")
        keys = [(route.channel, route.input_note) for route in self.routes]
        if len(keys) != len(set(keys)):
            errors.append("two routes use the same source channel/input note")
        for route in self.routes:
            if route.sound and route.sound not in ids:
                errors.append(f"{route.identifier}: unknown sound {route.sound}")
        return errors

    def allocated_blocks(self) -> int:
        return sum(sound.allocation_blocks for sound in self.sounds)

    def route(self, channel: int, note: int) -> Route | None:
        return next((route for route in self.routes if route.channel == channel and route.input_note == note), None)

    def hihat_cc(self, channel: int, controller: int, value: int) -> tuple[int, int] | None:
        hihat = self.raw.get("hihat", {})
        if hihat.get("mode") != "direct_cc4" or hihat.get("source") not in self.sources:
            return None
        if channel != self.sources[hihat["source"]] or controller != hihat.get("input_cc", 4):
            return None
        low, high = hihat.get("input_closed", 0), hihat.get("input_open", 127)
        value = max(min(value, max(low, high)), min(low, high))
        normalized = 0 if low == high else round((value - low) * 127 / (high - low))
        if hihat.get("invert", False):
            normalized = 127 - normalized
        out_low, out_high = hihat.get("output_closed", 0), hihat.get("output_open", 127)
        mapped = round(out_low + normalized * (out_high - out_low) / 127)
        return int(hihat.get("output_cc", 4)), int(mapped)

    @staticmethod
    def mapped_velocity(route: Route, velocity: int) -> int:
        velocity = _number(velocity, "velocity", 1, 127)
        low, high = sorted((route.input_velocity_min, route.input_velocity_max))
        velocity = max(low, min(high, velocity))
        normalized = 0 if low == high else round((velocity - low) * 127 / (high - low))
        if route.input_velocity_min > route.input_velocity_max:
            normalized = 127 - normalized
        return round(route.output_velocity_min + normalized * (route.output_velocity_max - route.output_velocity_min) / 127)
