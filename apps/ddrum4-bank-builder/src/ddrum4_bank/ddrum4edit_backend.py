"""Explicit adapter around a user-installed ddrum4edit executable."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Literal

from .ddrum4ui import encoded_block_count, run_edit


# Each encoded DD4 audio block is one fixed-size MIDI event: two delta-time
# bytes, F0, the two-byte SysEx length, and 1173 bytes of packet data.
DD4_ENCODED_BLOCK_FILE_BYTES = 1178


@dataclass(frozen=True)
class Ddrum4EditBackend:
    executable: Path

    def _run(self, arguments: list[str], *, cwd: Path | None = None) -> str:
        result = run_edit(self.executable, arguments, cwd=cwd)
        if result.returncode:
            # ddrum4edit 1.3 can raise EInvalidOp while printing details for a
            # final all-zero block.  The Sound header and block count have
            # already been parsed successfully at that point; accepting only
            # this narrowly identifiable partial `-p` result avoids rejecting
            # an otherwise valid, independently extractable Sound.
            partial_count = encoded_block_count(result.stdout)
            if arguments[:1] == ["-p"] and partial_count is not None:
                return result.stdout
            raise RuntimeError(result.stderr.strip() or f"ddrum4edit exited with code {result.returncode}")
        return result.stdout

    def inspect(self, sound: Path) -> str:
        return self._run(["-p", str(sound)])

    def encoded_blocks(self, sound: Path) -> int:
        count = encoded_block_count(self.inspect(sound))
        if count is None:
            raise RuntimeError(f"ddrum4edit did not report encoded blocks for {sound}")
        return count

    def sample_block_counts(self, sound: Path) -> tuple[int, ...]:
        """Return the exact encoded block allocation of each resident sample."""
        details = self.inspect(sound)
        rows = re.findall(
            r"Sample\s*\(\s*(\d+)\)\s*Start Block\s*:.*?"
            r"Blocks Count\s*:\s*[0-9A-F ]+\((\d+)\)",
            details,
            flags=re.DOTALL,
        )
        if not rows:
            raise RuntimeError(f"ddrum4edit did not report per-sample blocks for {sound}")
        ordered = sorted((int(index), int(blocks)) for index, blocks in rows)
        if [index for index, _blocks in ordered] != list(range(1, len(ordered) + 1)):
            raise RuntimeError(f"ddrum4edit reported a discontinuous sample allocation for {sound}")
        return tuple(blocks for _index, blocks in ordered)

    def sound_id(self, sound: Path) -> str:
        """Return the internal group-and-number ID reported by ddrum4edit."""
        match = re.search(r"Sound Name\s*:.*?\(([A-Z0-9]{3,4}_[0-9]{3})\)", self.inspect(sound))
        if match is None:
            raise RuntimeError(f"ddrum4edit did not report a DDrum4 Sound ID for {sound}")
        return match.group(1)

    def build(
        self, config: Path, output: Path, *, syx: bool = False, markers: bool = False,
        encoding_precision: Literal["dd4", "float"] = "dd4",
    ) -> None:
        """Build a sound using the output path declared in a ddrum4edit cfg.

        ddrum4edit 1.3.0 reads the configuration with ``-c``; the destination
        is deliberately *inside* the configuration, rather than a command-line
        output switch. Requiring the caller to pass the same destination keeps
        a build request explicit and prevents an unnoticed overwrite.
        """
        if syx or markers:
            raise ValueError("ddrum4edit cfg builds currently support standard .mid output only")
        if encoding_precision not in {"dd4", "float"}:
            raise ValueError("encoding_precision must be 'dd4' or 'float'")
        config = config.resolve()
        output = output.resolve()
        declared_output = _declared_output(config)
        if declared_output != output:
            raise RuntimeError(
                f"configuration declares output {declared_output}, not requested {output}"
            )
        if output.exists():
            raise FileExistsError(f"refusing to overwrite existing sound: {output}")
        # ddrum4edit 1.3 defaults to its newer floating-point encoder.  Its
        # block reconstruction is measurably discontinuous on hard attacks;
        # the original DD4-compatible precision keeps the predictor/block
        # state coherent and is therefore the safe default for module Sounds.
        self._run([f"--encpre={encoding_precision}", "-c", str(config)], cwd=config.parent)
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError(f"ddrum4edit did not create expected sound: {output}")
        self.encoded_blocks(output)

    def extract_decoded_samples(self, sound: Path, output_directory: Path) -> tuple[Path, ...]:
        """Export the DDrum4 codec-decoded WAVs from an encoded local Sound.

        ``ddrum4edit -e -x`` is the verified inverse of its local Sound
        builder: it decodes the packets in ``sound`` into 16-bit mono RIFF WAV
        files.  This does not open a MIDI port or transfer anything to a
        module.  The caller must provide a new directory, avoiding accidental
        replacement of a prior audition artefact.
        """
        sound = sound.resolve()
        output_directory = output_directory.resolve()
        if not sound.is_file() or sound.suffix.lower() not in {".mid", ".midi", ".syx"}:
            raise ValueError("encoded sound must be an existing .mid, .midi or .syx file")
        if output_directory.exists():
            raise FileExistsError(f"refusing to reuse decoded-sample directory: {output_directory}")
        output_directory.mkdir(parents=True)
        # ddrum4edit derives exported names from the input stem and writes to
        # its working directory. A local copy makes that behaviour explicit
        # and avoids any write beside the original auditable Sound.
        copied_sound = output_directory / sound.name
        copied_sound.write_bytes(sound.read_bytes())
        self._run(["-e", "-x", "-i", copied_sound.name], cwd=output_directory)
        samples = tuple(sorted(output_directory.glob(f"{sound.stem}_s*.wav")))
        if not samples:
            raise RuntimeError("ddrum4edit did not export any codec-decoded WAV sample")
        return samples

    def extract_decoded_layers(self, sound: Path, output_directory: Path) -> tuple[Path, ...]:
        """Decode WAVs with the DDrum4 Layer DSP implemented by ddrum4edit.

        ``--layers`` applies the documented pitch, amplitude envelope, decay
        and filter fields while exporting.  Keeping these files separate from
        raw codec samples makes the auditioner explicit about which stage is
        being played.
        """
        sound = sound.resolve()
        output_directory = output_directory.resolve()
        if not sound.is_file() or sound.suffix.lower() not in {".mid", ".midi", ".syx"}:
            raise ValueError("encoded sound must be an existing .mid, .midi or .syx file")
        if output_directory.exists():
            raise FileExistsError(f"refusing to reuse decoded-Layer directory: {output_directory}")
        output_directory.mkdir(parents=True)
        copied_sound = output_directory / sound.name
        copied_sound.write_bytes(sound.read_bytes())
        self._run(["-e", "-x", "--layers", "-i", copied_sound.name], cwd=output_directory)
        layers = tuple(sorted(output_directory.glob(f"{sound.stem}_s*_l*.wav")))
        if not layers:
            raise RuntimeError("ddrum4edit did not export any DSP-rendered Layer WAV")
        return layers


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
