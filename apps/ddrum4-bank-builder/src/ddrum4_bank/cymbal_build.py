"""Reproducible offline preparation of a flagship multi-layer DDrum cymbal."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Sequence

from drum_sampler.audio import QualityProfile, process_wav
from drum_sampler.library import SampleLibrary, SampleTake

from .sound_config import cymbal_velocity_layers, materialize_sound_config


_SOUND_ID = re.compile(r"^[A-Z0-9]{3,4}_[0-9]{3}$")


@dataclass(frozen=True)
class PreparedCymbalLayer:
    velocity: int
    raw_file: str
    prepared_file: str
    raw_peak_dbfs: float
    sample_rate: int
    frames: int
    channels: int
    duration_seconds: float


@dataclass(frozen=True)
class FlagshipCymbalBuild:
    sound_id: str
    instrument: str
    config: Path
    sound: Path
    profile: QualityProfile
    layers: tuple[PreparedCymbalLayer, ...]

    def to_document(self, encoded_blocks: int) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "ddrum4-flagship-cymbal-build",
            "sound_id": self.sound_id,
            "instrument": self.instrument,
            "config": self.config.name,
            "sound": self.sound.name,
            "encoded_blocks": encoded_blocks,
            "profile": asdict(self.profile),
            "layers": [asdict(layer) for layer in self.layers],
        }

    def write_report(self, path: Path, encoded_blocks: int) -> None:
        if path.exists():
            raise FileExistsError(f"refusing to overwrite build report: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_document(encoded_blocks), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def materialize_flagship_cymbal(
    library: SampleLibrary,
    *,
    raw_directory: Path,
    output_directory: Path,
    sound_id: str,
    instrument: str,
    template: Path,
    profile: QualityProfile,
    velocities: Sequence[int],
) -> FlagshipCymbalBuild:
    """Prepare selected raw takes and emit a ddrum4edit config, never MIDI.

    The source library remains immutable. A request must name every chosen
    velocity explicitly, so a larger later build cannot silently replace a
    previously auditioned candidate. For each velocity the round robin with
    the highest raw peak is selected deterministically before normalisation.
    """
    if not _SOUND_ID.fullmatch(sound_id):
        raise ValueError("sound_id must be an uppercase DDrum4 group and three-digit number")
    if not 1 <= len(velocities) <= 7 or len(set(velocities)) != len(velocities):
        raise ValueError("flagship cymbal needs 1..7 unique velocity layers")
    # Validate before processing any WAV so an unreviewed partial curve never
    # leaves a half-built directory on disk.
    layer_rows = cymbal_velocity_layers(len(velocities))
    if output_directory.exists():
        raise FileExistsError(f"refusing to reuse output directory: {output_directory}")
    if not raw_directory.is_dir():
        raise FileNotFoundError(f"raw directory not found: {raw_directory}")
    if not template.is_file():
        raise FileNotFoundError(f"template configuration not found: {template}")

    layers: list[PreparedCymbalLayer] = []
    sample_files: list[str] = []
    output_directory.mkdir(parents=True)
    for index, velocity in enumerate(velocities, 1):
        candidates = [
            take for take in library.takes
            if take.instrument == instrument and take.velocity == velocity and take.status == "captured"
        ]
        if not candidates:
            raise ValueError(f"no captured {instrument} take at velocity {velocity}")
        take = sorted(candidates, key=lambda item: (-item.peak_dbfs, item.repetition, item.raw_file))[0]
        raw = raw_directory / take.raw_file
        if not raw.is_file():
            raise FileNotFoundError(f"captured raw take is missing: {raw}")
        prepared_name = f"{sound_id}_s{index:02d}.wav"
        facts = process_wav(raw, output_directory / prepared_name, profile)
        sample_files.append(prepared_name)
        layers.append(PreparedCymbalLayer(
            velocity=velocity,
            raw_file=take.raw_file,
            prepared_file=prepared_name,
            raw_peak_dbfs=take.peak_dbfs,
            sample_rate=int(facts["sample_rate"]),
            frames=int(facts["frames"]),
            channels=int(facts["channels"]),
            duration_seconds=float(facts["duration_seconds"]),
        ))
    sound = output_directory / f"{sound_id}.mid"
    config = materialize_sound_config(
        template, output_directory / f"{sound_id}.cfg", sound_name=sound_id,
        output_sound=sound, sample_files=sample_files,
        layer_rows=layer_rows,
    )
    return FlagshipCymbalBuild(sound_id, instrument, config, sound, profile, tuple(layers))
