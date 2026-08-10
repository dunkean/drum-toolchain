"""Reporting for a bank made from actual ddrum4edit-encoded sounds."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class EncodedSound:
    path: str
    encoded_blocks: int
    bytes: int
    sha256: str


@dataclass(frozen=True)
class ActualBankReport:
    capacity_blocks: int
    sounds: tuple[EncodedSound, ...]

    @property
    def used_blocks(self) -> int:
        return sum(sound.encoded_blocks for sound in self.sounds)

    @property
    def remaining_blocks(self) -> int:
        return self.capacity_blocks - self.used_blocks

    @property
    def fits(self) -> bool:
        return self.remaining_blocks >= 0

    def to_document(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "ddrum4-actual-bank-report",
            "capacity_blocks": self.capacity_blocks,
            "used_blocks": self.used_blocks,
            "remaining_blocks": self.remaining_blocks,
            "fits": self.fits,
            "sounds": [asdict(sound) for sound in self.sounds],
        }


def report_actual_bank(capacity_blocks: int, entries: Iterable[tuple[Path, int]]) -> ActualBankReport:
    if capacity_blocks < 1:
        raise ValueError("capacity_blocks must be positive")
    sounds: list[EncodedSound] = []
    seen: set[Path] = set()
    for path, blocks in entries:
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"encoded sound not found: {path}")
        if path in seen:
            raise ValueError(f"duplicate sound in actual bank report: {path}")
        if blocks < 1:
            raise ValueError(f"encoded block count must be positive for {path}")
        seen.add(path)
        sounds.append(EncodedSound(str(path), blocks, path.stat().st_size, sha256(path.read_bytes()).hexdigest()))
    return ActualBankReport(capacity_blocks, tuple(sounds))
