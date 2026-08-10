"""Generate auditable ddrum4edit configurations from original WAV selections.

The emitted configuration uses the documented ddrum4edit text format.  It
contains no encoded audio and never reads a factory sound at build time.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Sequence


_SECTION = r"(?ms)^-Begin-{name}-\s*$.*?^-End-{name}-\s*$"

# Seven velocity crossfade curves transcribed once from the *structure* of a
# reference multisample and expressed here as parameters. They are not sample
# data. Values 05..12 in each layer are the DDrum4 gain-velocity curve.
_SNARE_LAYER_ROWS = (
    "00 00 02 00 00 00 00 00 00 00 00 00 FF FF FF FF FF FF FF FF 00 00 00 00 00 00 00 00 63 63 00 00 63 00 00 00 09 00 06 00 04 63 32 00 04 00 00 00 00 00",
    "01 00 02 00 00 00 00 00 00 FF FF 00 FF FF FF FF FF FF FF FF 00 00 00 00 00 00 00 00 63 63 00 00 63 00 00 00 09 00 06 00 04 63 32 00 04 00 00 00 00 00",
    "02 00 02 00 00 00 00 00 FF 00 00 00 FF FF FF FF FF FF FF FF 00 00 00 00 00 00 00 00 63 63 00 00 63 00 00 00 09 00 06 00 04 63 32 00 04 00 00 00 00 00",
    "03 00 02 00 00 00 00 FF 00 00 00 00 FF FF FF FF FF FF FF FF 00 00 00 00 00 00 00 00 63 63 00 00 63 00 00 00 09 00 06 00 04 63 32 00 04 00 00 00 00 00",
    "04 00 02 00 00 00 FF 00 00 00 00 00 FF FF FF FF FF FF FF FF 00 00 00 00 00 00 00 00 63 63 00 00 63 00 00 00 09 00 06 00 04 63 32 00 04 00 00 00 00 00",
    "05 00 02 00 00 FF 00 00 00 00 00 00 FF FF FF FF FF FF FF FF 00 00 00 00 00 00 00 00 63 63 00 00 63 00 00 00 09 00 06 00 04 63 32 00 04 00 00 00 00 00",
    "06 00 02 00 FF 00 00 00 00 00 00 00 FF FF FF FF FF FF FF FF 00 00 00 00 00 00 00 00 63 63 00 00 63 00 00 00 09 00 06 00 04 63 32 00 04 00 00 00 00 00",
)


def snare_velocity_layers(sample_count: int) -> tuple[str, ...]:
    """Return the verified 1..7 layer velocity-crossfade layout."""
    if not 1 <= sample_count <= len(_SNARE_LAYER_ROWS):
        raise ValueError("snare velocity layout supports 1..7 samples")
    return _SNARE_LAYER_ROWS[:sample_count]


def cymbal_velocity_layers(sample_count: int) -> tuple[str, ...]:
    """Return an audited cymbal layout, refusing invented partial curves.

    The stored seven-row curve was transcribed from one reference *snare*
    structure.  Taking its first 2..6 rows for a cymbal leaves the upper
    velocity range undocumented, which is exactly how the old CYMB_995 build
    could sound abrupt or behave as if its response was flat.  A one-layer
    cymbal is unambiguous; a seven-layer layout uses the complete audited
    reference curve.  Intermediate cymbal layouts must first be verified in
    ddrum4ui with the module's panel-button velocity sweep.
    """
    if sample_count == 1:
        return _SNARE_LAYER_ROWS[:1]
    if sample_count == len(_SNARE_LAYER_ROWS):
        return _SNARE_LAYER_ROWS
    raise ValueError(
        "no audited DDrum4 cymbal velocity layout for 2..6 samples; "
        "use one or seven layers, or add a panel-verified cymbal layout"
    )


def materialize_sound_config(
    template: Path,
    output_config: Path,
    *,
    sound_name: str,
    output_sound: Path,
    sample_files: Sequence[str],
    layer_rows: Sequence[str],
) -> Path:
    """Create a non-overwriting config for up to ten local WAV/SMP files.

    ``sample_files`` are deliberately relative names. This makes the build
    directory portable and prevents machine-specific source paths entering a
    generated DDrum4 configuration.
    """
    if output_config.exists():
        raise FileExistsError(f"refusing to overwrite configuration: {output_config}")
    if not template.is_file():
        raise FileNotFoundError(f"template configuration not found: {template}")
    if not sound_name or len(sample_files) != len(layer_rows) or not 1 <= len(sample_files) <= 10:
        raise ValueError("sound name and 1..10 matching sample files/layer rows are required")
    if any(Path(sample).is_absolute() or Path(sample).name != sample for sample in sample_files):
        raise ValueError("sample file entries must be simple relative filenames")
    text = template.read_text(encoding="utf-8", errors="replace")
    layers = [f"L{index:02X} {row} " for index, row in enumerate(layer_rows, 1)]
    text = _replace_section(text, "Layers", "\n".join(layers))
    enabled = " ".join("01" if index < len(layer_rows) else "00" for index in range(10))
    text = re.sub(r"(?m)^VL1 .*?$", f"VL1 {enabled} (01 = Layer enabled in this variation)", text)
    files = "\n".join(f"S{index:02X} {sample}" for index, sample in enumerate(sample_files, 1))
    text = _replace_section(text, "Sample-Files", files)
    text = _replace_section(text, "Sample-Name", sound_name)
    text = _replace_section(text, "Sound-File-Out", str(output_sound.resolve()))
    output_config.parent.mkdir(parents=True, exist_ok=True)
    output_config.write_text(text, encoding="utf-8", newline="\n")
    return output_config


def _replace_section(text: str, name: str, body: str) -> str:
    pattern = _SECTION.format(name=re.escape(name))
    replacement = f"-Begin-{name}-\n{body}\n-End-{name}-"
    result, count = re.subn(pattern, lambda _: replacement, text)
    if count != 1:
        raise ValueError(f"template must contain exactly one {name} section")
    return result
