"""Reproducible offline preparation of a positional flagship DDrum4 snare."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Sequence

from drum_sampler.audio import QualityProfile, process_wav
from drum_sampler.library import SampleLibrary, SampleTake

from .sound_config import materialize_sound_config, positional_snare_layers


_SOUND_ID = re.compile(r"^SNRE_[0-9]{3}$")


@dataclass(frozen=True)
class PreparedSnareLayer:
    position: str
    velocity: int
    raw_file: str
    prepared_file: str
    sample_rate: int
    frames: int
    channels: int
    duration_seconds: float


@dataclass(frozen=True)
class PositionalSnareBuild:
    sound_id: str
    instrument: str
    positions: tuple[str, str]
    config: Path
    sound: Path
    profile: QualityProfile
    layers: tuple[PreparedSnareLayer, ...]

    def write_report(self, path: Path, encoded_blocks: int) -> None:
        if path.exists():
            raise FileExistsError(f"refusing to overwrite build report: {path}")
        document = {
            "schema_version": 1,
            "kind": "ddrum4-positional-snare-build",
            "sound_id": self.sound_id,
            "instrument": self.instrument,
            "positions": list(self.positions),
            "config": self.config.name,
            "sound": self.sound.name,
            "encoded_blocks": encoded_blocks,
            "profile": asdict(self.profile),
            "layers": [asdict(layer) for layer in self.layers],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _select_take(
    library: SampleLibrary, instrument: str, articulation: str, velocity: int
) -> SampleTake:
    candidates = [
        take for take in library.takes
        if take.instrument == instrument and take.articulation == articulation
        and take.velocity == velocity and take.status == "captured"
    ]
    if not candidates:
        raise ValueError(f"no captured {instrument}.{articulation} take at velocity {velocity}")
    if any(take.source in {"", "unassigned"} or take.license_statement in {"", "unassigned"} for take in candidates):
        raise ValueError(f"{instrument}.{articulation} has captured takes without provenance")
    return sorted(
        candidates,
        key=lambda take: (-(take.peak_dbfs if take.peak_dbfs is not None else float("-inf")), take.repetition, take.raw_file),
    )[0]


def materialize_positional_snare(
    library: SampleLibrary,
    *,
    raw_directory: Path,
    output_directory: Path,
    sound_id: str,
    instrument: str,
    positions: Sequence[str],
    velocities: Sequence[int],
    template: Path,
    profile: QualityProfile,
) -> PositionalSnareBuild:
    """Prepare exactly two positions by five velocities and emit a config."""
    if not _SOUND_ID.fullmatch(sound_id):
        raise ValueError("positional snare sound_id must be SNRE plus a three-digit number")
    if len(positions) != 2 or len(set(positions)) != 2:
        raise ValueError("positional snare requires exactly two distinct articulations")
    if len(velocities) != 5 or len(set(velocities)) != 5 or tuple(velocities) != tuple(sorted(velocities)):
        raise ValueError("positional snare requires five unique ascending velocities")
    if output_directory.exists():
        raise FileExistsError(f"refusing to reuse output directory: {output_directory}")
    if not raw_directory.is_dir():
        raise FileNotFoundError(f"raw directory not found: {raw_directory}")
    if not template.is_file():
        raise FileNotFoundError(f"template configuration not found: {template}")

    # Resolve the complete source grid before creating any build artefacts. A
    # typo or missing raw take must leave no half-populated output directory
    # that could later be mistaken for a valid candidate.
    source_grid: list[tuple[str, int, SampleTake, Path]] = []
    for position in positions:
        for velocity in velocities:
            take = _select_take(library, instrument, position, velocity)
            raw = raw_directory / take.raw_file
            if not raw.is_file():
                raise FileNotFoundError(f"captured raw take is missing: {raw}")
            source_grid.append((position, velocity, take, raw))

    output_directory.mkdir(parents=True)
    layers: list[PreparedSnareLayer] = []
    sample_files: list[str] = []
    for position, velocity, take, raw in source_grid:
        prepared_name = f"{sound_id}_s{len(layers) + 1:02d}.wav"
        facts = process_wav(raw, output_directory / prepared_name, profile)
        sample_files.append(prepared_name)
        layers.append(PreparedSnareLayer(
            position=position,
            velocity=velocity,
            raw_file=take.raw_file,
            prepared_file=prepared_name,
            sample_rate=int(facts["sample_rate"]),
            frames=int(facts["frames"]),
            channels=int(facts["channels"]),
            duration_seconds=float(facts["duration_seconds"]),
        ))

    sound = output_directory / f"{sound_id}.mid"
    config = materialize_sound_config(
        template,
        output_directory / f"{sound_id}.cfg",
        sound_name=sound_id,
        output_sound=sound,
        sample_files=sample_files,
        layer_rows=positional_snare_layers(),
    )
    return PositionalSnareBuild(
        sound_id, instrument, (positions[0], positions[1]), config, sound, profile, tuple(layers)
    )
