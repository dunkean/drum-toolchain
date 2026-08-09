"""Explicit adapter around a user-installed ddrum4edit executable."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ddrum4ui import encoded_block_count, run_edit


@dataclass(frozen=True)
class Ddrum4EditBackend:
    executable: Path

    def _run(self, arguments: list[str]) -> str:
        result = run_edit(self.executable, arguments)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"ddrum4edit exited with code {result.returncode}")
        return result.stdout

    def inspect(self, sound: Path) -> str:
        return self._run(["-p", str(sound)])

    def encoded_blocks(self, sound: Path) -> int:
        count = encoded_block_count(self.inspect(sound))
        if count is None:
            raise RuntimeError(f"ddrum4edit did not report encoded blocks for {sound}")
        return count

    def build(self, config: Path, output: Path, *, syx: bool = False, markers: bool = False) -> None:
        arguments = ["-c", str(config), "-o", str(output)]
        if syx:
            arguments.append("--syx")
        if markers:
            arguments.append("--markers")
        self._run(arguments)
