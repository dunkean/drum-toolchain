"""Explicit adapter around a user-installed ddrum4edit executable."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .ddrum4ui import encoded_block_count, run_edit


@dataclass(frozen=True)
class Ddrum4EditBackend:
    executable: Path

    def _run(self, arguments: list[str], *, cwd: Path | None = None) -> str:
        result = run_edit(self.executable, arguments, cwd=cwd)
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

    def sound_id(self, sound: Path) -> str:
        """Return the internal group-and-number ID reported by ddrum4edit."""
        match = re.search(r"Sound Name\s*:.*?\(([A-Z0-9]{3,4}_[0-9]{3})\)", self.inspect(sound))
        if match is None:
            raise RuntimeError(f"ddrum4edit did not report a DDrum4 Sound ID for {sound}")
        return match.group(1)

    def build(self, config: Path, output: Path, *, syx: bool = False, markers: bool = False) -> None:
        """Build a sound using the output path declared in a ddrum4edit cfg.

        ddrum4edit 1.3.0 reads the configuration with ``-c``; the destination
        is deliberately *inside* the configuration, rather than a command-line
        output switch. Requiring the caller to pass the same destination keeps
        a build request explicit and prevents an unnoticed overwrite.
        """
        if syx or markers:
            raise ValueError("ddrum4edit cfg builds currently support standard .mid output only")
        config = config.resolve()
        output = output.resolve()
        declared_output = _declared_output(config)
        if declared_output != output:
            raise RuntimeError(
                f"configuration declares output {declared_output}, not requested {output}"
            )
        if output.exists():
            raise FileExistsError(f"refusing to overwrite existing sound: {output}")
        self._run(["-c", str(config)], cwd=config.parent)
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError(f"ddrum4edit did not create expected sound: {output}")
        self.encoded_blocks(output)


def _declared_output(config: Path) -> Path:
    if not config.is_file():
        raise FileNotFoundError(f"ddrum4edit configuration not found: {config}")
    text = config.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"-Begin-Sound-File-Out-\s*\r?\n(.+?)\r?\n-End-Sound-File-Out-",
        text,
    )
    if match is None:
        raise RuntimeError(f"configuration has no output sound-file section: {config}")
    declared = Path(match.group(1).strip())
    return (config.parent / declared).resolve() if not declared.is_absolute() else declared.resolve()
