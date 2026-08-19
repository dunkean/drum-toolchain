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

# A one-sample cymbal has no neighbouring layers with which to crossfade.
# Its eight gain-velocity points must therefore remain at full gain from soft
# to hard.  Reusing the first row of _SNARE_LAYER_ROWS would only activate it
# in the soft part of the range and makes a panel-button (hard-velocity) test
# silent.
_SINGLE_CYMBAL_FULL_RANGE_ROW = (
    "00 00 02 00 FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF "
    "00 00 00 00 00 00 00 00 63 63 00 00 63 00 00 00 09 00 06 00 "
    "04 63 32 00 04 00 00 00 00 00"
)


def snare_velocity_layers(sample_count: int) -> tuple[str, ...]:
    """Return the verified 1..7 layer velocity-crossfade layout."""
    if not 1 <= sample_count <= len(_SNARE_LAYER_ROWS):
        raise ValueError("snare velocity layout supports 1..7 samples")
    return _SNARE_LAYER_ROWS[:sample_count]


def positional_snare_layers() -> tuple[str, ...]:
    """Return a complete five-velocity by two-position ten-layer layout.

    DDrum4 exposes eight velocity gain points and eight center-to-edge gain
    points per layer.  The five velocity samples cover all eight points as
    2/2/1/2/1 bands.  Position samples 1..5 cover Note-P zones 1..4 and
    samples 6..10 cover zones 5..8, matching the split demonstrated by the
    ddrum4edit positional/dual-zone reference sounds.
    """
    velocity_zones = ((0, 1), (2, 3), (4,), (5, 6), (7,))
    position_zones = ((0, 1, 2, 3), (4, 5, 6, 7))
    rows: list[str] = []
    for position_indexes in position_zones:
        for velocity_indexes in velocity_zones:
            values = _SNARE_LAYER_ROWS[0].split()
            values[0] = f"{len(rows):02X}"
            values[4:12] = ["FF" if index in velocity_indexes else "00" for index in range(8)]
            values[12:20] = ["FF" if index in position_indexes else "00" for index in range(8)]
            rows.append(" ".join(values))
    return tuple(rows)


def hihat_position_layers(layer_counts: Sequence[int]) -> tuple[str, ...]:
    """Return a complete eight-position hi-hat matrix using at most ten layers.

    A position with one layer covers the full eight-point velocity axis.  A
    position with two layers splits that axis into soft (points 1..4) and hard
    (points 5..8) timbres.  Every position/velocity cell is therefore covered
    exactly once and no layer can leak into an adjacent nested branch.
    """
    if len(layer_counts) != 8 or any(count not in (1, 2) for count in layer_counts):
        raise ValueError("hi-hat layout requires eight positions with one or two layers each")
    if sum(layer_counts) > 10:
        raise ValueError("DDrum4 sounds support at most ten hi-hat layers")
    rows: list[str] = []
    for position_index, count in enumerate(layer_counts):
        velocity_groups = ((0, 1, 2, 3, 4, 5, 6, 7),) if count == 1 else (
            (0, 1, 2, 3), (4, 5, 6, 7)
        )
        for velocity_indexes in velocity_groups:
            values = _SNARE_LAYER_ROWS[0].split()
            values[0] = f"{len(rows):02X}"
            values[4:12] = ["FF" if index in velocity_indexes else "00" for index in range(8)]
            values[12:20] = ["FF" if index == position_index else "00" for index in range(8)]
            rows.append(" ".join(values))
    return tuple(rows)


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
        return (_SINGLE_CYMBAL_FULL_RANGE_ROW,)
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
