"""Physical-kit model with no routing or target-MIDI assumptions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PhysicalInstrument:
    identifier: str
    kind: str
    zones: tuple[str, ...]
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class PhysicalKit:
    identifier: str
    instruments: tuple[PhysicalInstrument, ...]

    @classmethod
    def load(cls, path: Path) -> "PhysicalKit":
        document: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("physical-kit document must be a mapping")
        identifier = document.get("kit")
        values = document.get("instruments")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("physical-kit requires a non-empty kit id")
        if not isinstance(values, list) or not values:
            raise ValueError("physical-kit requires instruments")
        instruments: list[PhysicalInstrument] = []
        known: set[str] = set()
        for value in values:
            if not isinstance(value, dict):
                raise ValueError("physical instrument must be a mapping")
            instrument_id = value.get("id")
            kind = value.get("kind")
            zones = value.get("zones", [])
            capabilities = value.get("capabilities", [])
            if not isinstance(instrument_id, str) or not instrument_id:
                raise ValueError("physical instrument requires id")
            if instrument_id in known:
                raise ValueError(f"duplicate physical instrument: {instrument_id}")
            if not isinstance(kind, str) or not kind:
                raise ValueError(f"{instrument_id}: kind is required")
            if not isinstance(zones, list) or not zones or not all(isinstance(item, str) and item for item in zones):
                raise ValueError(f"{instrument_id}: zones must be a non-empty string list")
            if not isinstance(capabilities, list) or not all(isinstance(item, str) and item for item in capabilities):
                raise ValueError(f"{instrument_id}: capabilities must be a string list")
            known.add(instrument_id)
            instruments.append(PhysicalInstrument(instrument_id, kind, tuple(zones), tuple(capabilities)))
        return cls(identifier, tuple(instruments))

    def instrument(self, identifier: str) -> PhysicalInstrument:
        for instrument in self.instruments:
            if instrument.identifier == identifier:
                return instrument
        raise KeyError(identifier)
