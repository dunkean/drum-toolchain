"""Deterministic source-layer selection for compact DDrum4 sound builds."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from drum_sampler.library import SampleLibrary, SampleTake


@dataclass(frozen=True)
class SelectedLayer:
    velocity: int
    raw_file: str
    prepared_file: str | None
    sha256: str | None


@dataclass(frozen=True)
class SnareSelection:
    library_id: str
    instrument: str
    head: tuple[SelectedLayer, ...]
    rim: tuple[SelectedLayer, ...]
    accent: SelectedLayer
    warnings: tuple[str, ...]

    def to_document(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "ddrum4-snare-source-selection",
            "library_id": self.library_id,
            "instrument": self.instrument,
            "head": [asdict(layer) for layer in self.head],
            "rim": [asdict(layer) for layer in self.rim],
            "accent": asdict(self.accent),
            "warnings": list(self.warnings),
            "sample_slots": len(self.head) + len(self.rim) + 1,
        }

    def write(self, path: Path) -> None:
        if path.exists():
            raise FileExistsError(f"refusing to overwrite selection: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _eligible(library: SampleLibrary, instrument: str, articulation: str) -> list[SampleTake]:
    takes = [take for take in library.takes if take.instrument == instrument and take.articulation == articulation and take.status == "captured"]
    if not takes:
        raise ValueError(f"no captured takes for {instrument}.{articulation}")
    if any(take.license_statement in {"", "unassigned"} or take.source in {"", "unassigned"} for take in takes):
        raise ValueError(f"{instrument}.{articulation} has captured takes without source/licence provenance")
    return takes


def select_velocity_layers(library: SampleLibrary, instrument: str, articulation: str, maximum: int) -> tuple[SelectedLayer, ...]:
    """Choose evenly distributed velocity levels, retaining the extrema."""
    if not 1 <= maximum <= 10:
        raise ValueError("maximum must be 1..10")
    by_velocity: dict[int, list[SampleTake]] = {}
    for take in _eligible(library, instrument, articulation):
        by_velocity.setdefault(take.velocity, []).append(take)
    levels = sorted(by_velocity)
    count = min(maximum, len(levels))
    indexes = (0,) if count == 1 else tuple(round(index * (len(levels) - 1) / (count - 1)) for index in range(count))
    selected: list[SelectedLayer] = []
    for index in indexes:
        representative = sorted(by_velocity[levels[index]], key=lambda take: (take.repetition, take.raw_file))[0]
        selected.append(SelectedLayer(representative.velocity, representative.raw_file, representative.prepared_file, representative.sha256))
    return tuple(selected)


def select_snare(library: SampleLibrary, instrument: str = "snare_main", head_layers: int = 7, rim_layers: int = 2) -> SnareSelection:
    """Apply the B1 priority: head dynamics, rim dynamics, then a strong accent."""
    if not 1 <= head_layers <= 7 or not 1 <= rim_layers <= 2:
        raise ValueError("snare selection supports 1..7 head and 1..2 rim layers")
    head = select_velocity_layers(library, instrument, "head", head_layers)
    rim = select_velocity_layers(library, instrument, "rim", rim_layers)
    warnings: list[str] = []
    try:
        accent = select_velocity_layers(library, instrument, "cross_stick", 1)[0]
    except ValueError:
        accent = head[-1]
        warnings.append("no captured cross_stick; strongest selected head is used as the accent candidate")
    selection = SnareSelection(library.identifier, instrument, head, rim, accent, tuple(warnings))
    if selection.to_document()["sample_slots"] > 10:
        raise ValueError("selected snare exceeds DDrum4 ten-sample limit")
    return selection
