"""Reproducible eight-position flagship DDrum4 hi-hat build."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import re
from typing import Sequence

from drum_sampler.audio import QualityProfile, process_wav
from drum_sampler.library import SampleLibrary, SampleTake

from .sound_config import hihat_position_layers, materialize_sound_config


_SOUND_ID = re.compile(r"^[A-Z0-9]{3,4}_[0-9]{3}$")


@dataclass(frozen=True)
class HihatBranch:
    position: int
    articulation: str
    velocities: tuple[int, ...]
    max_duration_seconds: float


FLAGSHIP_HIHAT_BRANCHES = (
    HihatBranch(1, "pedal_chick", (96,), 1.00),
    HihatBranch(2, "tight_tip", (36, 112), 1.00),
    HihatBranch(3, "closed_tip", (36, 112), 1.00),
    HihatBranch(4, "loose_tip", (96,), 1.20),
    HihatBranch(5, "open_1_tip", (96,), 1.30),
    HihatBranch(6, "open_3_tip", (96,), 5.50),
    HihatBranch(7, "open_5_tip", (96,), 5.80),
    HihatBranch(8, "foot_splash", (112,), 5.30),
)


# The primary HHAT sound exhausts its eight Note-P positions.  Keep the edge
# family in a second, Arduino-selected nested sound instead of sacrificing
# bow openness or encoding articulation into velocity.  Position 8 adds the
# missing bow open-4 transition, so all ten available layers remain useful.
FLAGSHIP_HIHAT_EDGE_BRANCHES = (
    HihatBranch(1, "tight_edge", (36, 112), 1.00),
    HihatBranch(2, "closed_edge", (36, 112), 1.10),
    HihatBranch(3, "loose_edge", (96,), 1.20),
    HihatBranch(4, "open_1_edge", (96,), 1.30),
    HihatBranch(5, "open_2_edge", (96,), 2.10),
    HihatBranch(6, "open_3_edge", (96,), 5.80),
    HihatBranch(7, "open_4_edge", (96,), 5.60),
    HihatBranch(8, "open_4_tip", (96,), 5.60),
)


@dataclass(frozen=True)
class PreparedHihatLayer:
    position: int
    articulation: str
    velocity: int
    max_duration_seconds: float
    raw_file: str
    prepared_file: str
    raw_peak_dbfs: float
    sample_rate: int
    frames: int
    channels: int
    duration_seconds: float


@dataclass(frozen=True)
class FlagshipHihatBuild:
    sound_id: str
    instrument: str
    config: Path
    sound: Path
    profile: QualityProfile
    branches: tuple[HihatBranch, ...]
    layers: tuple[PreparedHihatLayer, ...]

    def write_report(self, path: Path, encoded_blocks: int) -> None:
        if path.exists():
            raise FileExistsError(f"refusing to overwrite build report: {path}")
        document = {
            "schema_version": 1,
            "kind": "ddrum4-flagship-hihat-build",
            "sound_id": self.sound_id,
            "instrument": self.instrument,
            "config": self.config.name,
            "sound": self.sound.name,
            "encoded_blocks": encoded_blocks,
            "profile": asdict(self.profile),
            "branches": [asdict(branch) for branch in self.branches],
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
    if any(take.peak_dbfs is None for take in candidates):
        raise ValueError(f"{instrument}.{articulation} has captured takes without peak analysis")
    if any(take.source in {"", "unassigned"} or take.license_statement in {"", "unassigned"} for take in candidates):
        raise ValueError(f"{instrument}.{articulation} has captured takes without provenance")
    return sorted(candidates, key=lambda take: (-float(take.peak_dbfs), take.repetition, take.raw_file))[0]


def materialize_flagship_hihat(
    library: SampleLibrary,
    *,
    raw_directory: Path,
    output_directory: Path,
    sound_id: str,
    instrument: str,
    template: Path,
    profile: QualityProfile,
    branches: Sequence[HihatBranch] = FLAGSHIP_HIHAT_BRANCHES,
) -> FlagshipHihatBuild:
    """Prepare an explicit eight-position/ten-layer sound without sending MIDI."""
    if not _SOUND_ID.fullmatch(sound_id):
        raise ValueError("sound_id must be an uppercase DDrum4 group and three-digit number")
    branch_tuple = tuple(branches)
    if tuple(branch.position for branch in branch_tuple) != tuple(range(1, 9)):
        raise ValueError("flagship hi-hat branches must declare positions 1..8 in order")
    if any(len(branch.velocities) not in (1, 2) for branch in branch_tuple):
        raise ValueError("each hi-hat position requires one or two source velocities")
    layer_rows = hihat_position_layers(tuple(len(branch.velocities) for branch in branch_tuple))
    if output_directory.exists():
        raise FileExistsError(f"refusing to reuse output directory: {output_directory}")
    if not raw_directory.is_dir():
        raise FileNotFoundError(f"raw directory not found: {raw_directory}")
    if not template.is_file():
        raise FileNotFoundError(f"template configuration not found: {template}")

    selected: list[tuple[HihatBranch, int, SampleTake, Path]] = []
    for branch in branch_tuple:
        for velocity in branch.velocities:
            take = _select_take(library, instrument, branch.articulation, velocity)
            raw = raw_directory / take.raw_file
            if not raw.is_file():
                raise FileNotFoundError(f"captured raw take is missing: {raw}")
            selected.append((branch, velocity, take, raw))

    output_directory.mkdir(parents=True)
    layers: list[PreparedHihatLayer] = []
    sample_files: list[str] = []
    for branch, velocity, take, raw in selected:
        prepared_name = f"{sound_id}_s{len(layers) + 1:02d}.wav"
        facts = process_wav(
            raw,
            output_directory / prepared_name,
            replace(profile, max_duration_seconds=branch.max_duration_seconds),
        )
        sample_files.append(prepared_name)
        layers.append(PreparedHihatLayer(
            position=branch.position,
            articulation=branch.articulation,
            velocity=velocity,
            max_duration_seconds=branch.max_duration_seconds,
            raw_file=take.raw_file,
            prepared_file=prepared_name,
            raw_peak_dbfs=float(take.peak_dbfs),
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
        layer_rows=layer_rows,
    )
    return FlagshipHihatBuild(
        sound_id, instrument, config, sound, profile, branch_tuple, tuple(layers)
    )
