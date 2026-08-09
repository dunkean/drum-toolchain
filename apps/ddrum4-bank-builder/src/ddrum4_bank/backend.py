"""Sound-backend boundary. The initial implementation delegates to ddrum4edit."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SoundBackend(Protocol):
    def inspect(self, sound: Path) -> str: ...

    def encoded_blocks(self, sound: Path) -> int: ...

    def build(self, config: Path, output: Path, *, syx: bool = False, markers: bool = False) -> None: ...
