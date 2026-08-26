"""Offline preview of a locally encoded DDrum4 Sound.

The DDrum4 codec itself is not guessed here.  ``ddrum4edit -e -x`` decodes
the Sound that will be sent to a module and the preview plays those resulting
WAVs.  The module's real-time layer selection and DSP are represented from the
exported configuration where their format is documented; a caller must still
label that part as a model until it has been measured from module audio.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import gcd
from pathlib import Path
import re
from typing import Sequence

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

from .ddrum4edit_backend import DD4_ENCODED_BLOCK_FILE_BYTES, Ddrum4EditBackend


_SECTION = r"(?ms)^-Begin-{name}-\s*$.*?^-End-{name}-\s*$"
_LAYER = re.compile(r"^L([0-9A-F]{2})\s+((?:[0-9A-F]{2}\s*){50})$", re.MULTILINE)
_VARIATION = re.compile(r"^V([LS])([1-9A])\s+((?:[0-9A-F]{2}\s*){10})(?:\s+\(.*)?$", re.MULTILINE)
_SAMPLE_FILE = re.compile(r"^S([0-9A-F]{2})\s+(.+?)\s*$", re.MULTILINE)
_SOUND_NAME = re.compile(r"(?ms)^-Begin-Sample-Name-\s*$\s*(.*?)\s*^-End-Sample-Name-\s*$")


@dataclass(frozen=True)
class CodecLayer:
    """One Layer row exported by ddrum4edit, retaining its raw parameters."""

    index: int
    sample_index: int
    gain_velocity: tuple[int, ...]
    gain_position: tuple[int, ...]
    pitch_semitones: int
    pitch_fine_tenths: int
    amplitude: int
    filter_1: tuple[int, int, int, int, int, int]
    filter_2: tuple[int, int, int, int]
    raw_values: tuple[int, ...]


@dataclass(frozen=True)
class CodecVariation:
    """Enabled and sequenced layers for one DDrum4 Variation."""

    index: int
    enabled: tuple[bool, ...]
    sequenced: tuple[bool, ...]


@dataclass(frozen=True)
class CodecPreviewSound:
    """Decoded audio and exported config for exactly one local Sound file."""

    sound_name: str
    config_path: Path
    decoded_directory: Path
    source_sound: Path | None
    sample_file_names: tuple[str | None, ...]
    samples: tuple[Path | None, ...]
    layer_samples: tuple[Path | None, ...]
    layers: tuple[CodecLayer, ...]
    variations: tuple[CodecVariation, ...]

    @property
    def available_variations(self) -> tuple[int, ...]:
        return tuple(variation.index for variation in self.variations if any(variation.enabled))


@dataclass(frozen=True)
class PreviewRender:
    """One temporary WAV rendered from codec-decoded audio and layer model."""

    path: Path
    active_layers: tuple[int, ...]
    variation: int
    velocity_step: int
    note_p: int
    round_robin_step: int
    mode: str


def _section(text: str, name: str) -> str:
    match = re.search(_SECTION.format(name=re.escape(name)), text)
    if match is None:
        raise ValueError(f"ddrum4edit configuration has no {name} section")
    return match.group(0)


def _signed_pitch(value: int) -> int:
    """Decode documented DDrum4 coarse-pitch byte without inventing a range."""
    if 0 <= value <= 0x0C:
        return value
    if 0xD0 <= value <= 0xFF:
        return value - 0x100
    raise ValueError(f"unsupported DDrum4 coarse-pitch byte {value:02X}")


def load_codec_preview(
    config_path: Path,
    decoded_directory: Path,
    *,
    source_sound: Path | None = None,
    decoded_layer_directory: Path | None = None,
) -> CodecPreviewSound:
    """Read an exported config and matching ``ddrum4edit -x`` WAVs.

    The decoded samples have the conventional ``<Sound>_s01.wav`` names.  The
    config remains the source of truth for variation/layer selection; no MIDI
    port is opened by this function.
    """
    config_path = config_path.resolve()
    decoded_directory = decoded_directory.resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"ddrum4edit configuration not found: {config_path}")
    if not decoded_directory.is_dir():
        raise FileNotFoundError(f"codec-decoded sample directory not found: {decoded_directory}")
    text = config_path.read_text(encoding="utf-8", errors="replace")
    name_match = _SOUND_NAME.search(text)
    if name_match is None or not name_match.group(1).strip():
        raise ValueError("ddrum4edit configuration has no Sound name")
    sound_name = name_match.group(1).strip()

    sample_files: dict[int, str] = {}
    for match in _SAMPLE_FILE.finditer(_section(text, "Sample-Files")):
        sample_files[int(match.group(1), 16) - 1] = match.group(2).strip()
    if not sample_files:
        raise ValueError("ddrum4edit configuration has no sample files")
    samples: list[Path | None] = []
    sample_names: list[str | None] = []
    for sample_index in range(10):
        if sample_index not in sample_files:
            sample_names.append(None)
            samples.append(None)
            continue
        sample_names.append(sample_files[sample_index])
        candidates = sorted(decoded_directory.glob(f"{sound_name}_s{sample_index + 1}*.wav"))
        if not candidates:
            # An export may have used the encoded file stem rather than the
            # sample-name field.  The GUI passes the matching name in normal
            # operation, but retaining this fallback helps manually built
            # Sounds without weakening the sample-index validation.
            candidates = sorted(decoded_directory.glob(f"*_s{sample_index + 1}*.wav"))
        samples.append(candidates[0].resolve() if candidates else None)

    layers: list[CodecLayer] = []
    for match in _LAYER.finditer(_section(text, "Layers")):
        values = tuple(int(token, 16) for token in match.group(2).split())
        if len(values) != 50:
            raise ValueError("DDrum4 Layer row must contain exactly 50 bytes")
        sample_index = values[0]
        if not 0 <= sample_index < 10:
            raise ValueError("DDrum4 Layer points at a sample outside 0..9")
        layers.append(CodecLayer(
            index=int(match.group(1), 16), sample_index=sample_index,
            gain_velocity=values[4:12], gain_position=values[12:20],
            pitch_semitones=_signed_pitch(values[20]), pitch_fine_tenths=values[21],
            amplitude=values[28], filter_1=values[36:42], filter_2=values[42:46],
            raw_values=values,
        ))
    if not 1 <= len(layers) <= 10:
        raise ValueError("ddrum4edit configuration must expose 1..10 Layer rows")

    layer_samples: list[Path | None] = [None] * 10
    if decoded_layer_directory is not None:
        decoded_layer_directory = decoded_layer_directory.resolve()
        if not decoded_layer_directory.is_dir():
            raise FileNotFoundError(f"codec-decoded Layer directory not found: {decoded_layer_directory}")
        for layer in layers:
            candidates = sorted(decoded_layer_directory.glob(f"*_l{layer.index}.wav"))
            if not candidates:
                candidates = sorted(decoded_layer_directory.glob(f"*_l{layer.index:02d}.wav"))
            if candidates:
                layer_samples[layer.index - 1] = candidates[0].resolve()

    enabled_rows: dict[int, tuple[bool, ...]] = {}
    sequenced_rows: dict[int, tuple[bool, ...]] = {}
    for match in _VARIATION.finditer(_section(text, "Variations")):
        values = tuple(value != "00" for value in match.group(3).split())
        if match.group(1) == "L":
            enabled_rows[int(match.group(2), 16)] = values
        else:
            sequenced_rows[int(match.group(2), 16)] = values
    variations = tuple(
        CodecVariation(index, enabled_rows.get(index, (False,) * 10), sequenced_rows.get(index, (False,) * 10))
        for index in range(1, 11)
    )
    return CodecPreviewSound(
        sound_name=sound_name, config_path=config_path, decoded_directory=decoded_directory,
        source_sound=source_sound.resolve() if source_sound is not None else None,
        sample_file_names=tuple(sample_names), samples=tuple(samples),
        layer_samples=tuple(layer_samples),
        layers=tuple(sorted(layers, key=lambda layer: layer.index)), variations=variations,
    )


def export_codec_preview(
    backend: Ddrum4EditBackend,
    *,
    sound: Path,
    config: Path,
    output_directory: Path,
    sound_slot: str | None = None,
) -> CodecPreviewSound:
    """Decode one already-built Sound into a new local preview directory.

    ``config`` must be the exact config used to build ``sound``.  The method
    copies it with the generated preview metadata; it never changes either
    input and does not contact a DDrum4 module.
    """
    sound = sound.resolve()
    config = config.resolve()
    output_directory = output_directory.resolve()
    if output_directory.exists():
        raise FileExistsError(f"refusing to reuse codec-preview directory: {output_directory}")
    if not sound.is_file():
        raise FileNotFoundError(f"encoded DDrum4 Sound not found: {sound}")
    if not config.is_file():
        raise FileNotFoundError(f"matching ddrum4edit config not found: {config}")
    output_directory.mkdir(parents=True)
    copied_config = output_directory / f"{sound.stem}.cfg"
    copied_config.write_bytes(config.read_bytes())
    decoded_directory = output_directory / "decoded"
    decoded_layer_directory = output_directory / "decoded-layers"
    encoded_blocks = backend.encoded_blocks(sound)
    sample_encoded_blocks = backend.sample_block_counts(sound)
    backend.extract_decoded_samples(sound, decoded_directory)
    backend.extract_decoded_layers(sound, decoded_layer_directory)
    preview = load_codec_preview(
        copied_config, decoded_directory, source_sound=sound,
        decoded_layer_directory=decoded_layer_directory,
    )
    manifest = {
        "kind": "ddrum4-codec-preview/v1",
        "hardware_io": "disabled",
        "source_sound": str(sound),
        "source_sound_sha256": sha256(sound.read_bytes()).hexdigest(),
        "source_sound_bytes": sound.stat().st_size,
        "encoded_blocks": encoded_blocks,
        "sample_encoded_blocks": list(sample_encoded_blocks),
        "sample_encoded_bytes": [
            blocks * DD4_ENCODED_BLOCK_FILE_BYTES for blocks in sample_encoded_blocks
        ],
        "non_audio_file_bytes": sound.stat().st_size - sum(
            blocks * DD4_ENCODED_BLOCK_FILE_BYTES for blocks in sample_encoded_blocks
        ),
        "layer_parameter_bytes": 50,
        "variation_parameter_bytes": 20,
        "source_config": str(config),
        "source_config_sha256": sha256(config.read_bytes()).hexdigest(),
        "sound_name": preview.sound_name,
        "sound_slot": sound_slot,
        "preview_config": copied_config.name,
        "decoded_directory": "decoded",
        "decoded_layer_directory": "decoded-layers",
        "layers": [asdict(layer) for layer in preview.layers],
        "variations": [asdict(variation) for variation in preview.variations],
        "notes": [
            "Samples are decoded with ddrum4edit -e -x from the encoded local Sound.",
            "Layer WAVs are decoded with ddrum4edit --layers so documented Layer DSP is applied.",
            "Runtime layer selection, pitch and gain use the exported config model.",
            "DDrum4 filter/EQ parameters are retained as raw bytes but are not claimed as hardware-rendered EQ.",
        ],
    }
    (output_directory / "codec-preview.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return preview


def _velocity_step(velocity: int) -> int:
    if not 1 <= velocity <= 127:
        raise ValueError("velocity must be in 1..127")
    return min(7, (velocity - 1) * 8 // 127)


def _variation(sound: CodecPreviewSound, index: int) -> CodecVariation:
    if not 1 <= index <= 10:
        raise ValueError("Variation must be in 1..10")
    result = sound.variations[index - 1]
    if not any(result.enabled):
        raise ValueError(f"{sound.sound_name} Variation V{index} has no enabled layers")
    return result


def active_layers(
    sound: CodecPreviewSound, *, variation: int, velocity: int, note_p: int, round_robin_step: int = 1,
) -> tuple[CodecLayer, ...]:
    """Resolve layers using exported gain masks and the configured sequence mask.

    A ``VS`` row is represented as a deterministic click-to-click sequence.
    A Sound without sequenced matching layers has no DDrum4 round robin: raw
    capture RR files are intentionally not smuggled into a built Sound.
    """
    if not 1 <= note_p <= 8:
        raise ValueError("NOTE P must be in 1..8")
    if round_robin_step < 1:
        raise ValueError("round-robin step must be positive")
    selected_variation = _variation(sound, variation)
    velocity_step = _velocity_step(velocity)
    matching = tuple(
        layer for layer in sound.layers
        if selected_variation.enabled[layer.index - 1]
        and layer.gain_velocity[velocity_step] > 0
        and layer.gain_position[note_p - 1] > 0
    )
    if not matching:
        raise ValueError(
            f"{sound.sound_name} V{variation} has no enabled Layer at velocity step {velocity_step + 1}, NOTE P {note_p}"
        )
    sequence = tuple(layer for layer in matching if selected_variation.sequenced[layer.index - 1])
    return (sequence[(round_robin_step - 1) % len(sequence)],) if sequence else matching


def _as_float(samples: np.ndarray) -> np.ndarray:
    if np.issubdtype(samples.dtype, np.integer):
        scale = max(abs(np.iinfo(samples.dtype).min), np.iinfo(samples.dtype).max)
        return samples.astype(np.float32) / scale
    return samples.astype(np.float32)


def _decode_layer_audio(path: Path, output_rate: int, pitch_semitones: float) -> np.ndarray:
    rate, raw = wavfile.read(path)
    audio = _as_float(raw)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    if rate != output_rate:
        divisor = gcd(int(rate), output_rate)
        audio = resample_poly(audio, output_rate // divisor, int(rate) // divisor).astype(np.float32)
    ratio = 2 ** (pitch_semitones / 12.0)
    if ratio != 1.0:
        frames = max(1, round(len(audio) / ratio))
        source_indexes = np.linspace(0, len(audio) - 1, frames, dtype=np.float32)
        audio = np.interp(source_indexes, np.arange(len(audio), dtype=np.float32), audio).astype(np.float32)
    return audio


def render_preview(
    sound: CodecPreviewSound,
    output: Path,
    *,
    variation: int,
    velocity: int,
    note_p: int,
    round_robin_step: int = 1,
    variation_pitch_semitones: float = 0.0,
    decay_percent: float = 100.0,
) -> PreviewRender:
    """Render a temporary listenable WAV from DDrum4 codec output.

    Pitch uses the documented coarse/fine fields.  Gain masks and amplitude
    are modelled from config bytes.  Filter/EQ bytes are deliberately not
    mapped to an invented DSP curve, so this stays a codec-accurate preview
    with a clearly bounded runtime model rather than a claimed module render.
    """
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite preview WAV: {output}")
    if not 25.0 <= decay_percent <= 400.0:
        raise ValueError("decay_percent must be in 25..400")
    layers = active_layers(
        sound, variation=variation, velocity=velocity, note_p=note_p, round_robin_step=round_robin_step,
    )
    decoded_paths: list[tuple[Path, bool]] = []
    for layer in layers:
        rendered_layer = sound.layer_samples[layer.index - 1]
        sample = rendered_layer if rendered_layer is not None and rendered_layer.is_file() else sound.samples[layer.sample_index]
        if sample is None or not sample.is_file():
            raise FileNotFoundError(
                f"codec-decoded sample {layer.sample_index + 1} required by Layer {layer.index} is missing"
            )
        decoded_paths.append((sample, rendered_layer is not None and rendered_layer.is_file()))
    rates = [int(wavfile.read(path, mmap=True)[0]) for path, _processed in decoded_paths]
    output_rate = max(rates)
    rendered: list[np.ndarray] = []
    velocity_step = _velocity_step(velocity)
    uses_layer_dsp = False
    for layer, (path, processed) in zip(layers, decoded_paths):
        gain = (layer.gain_velocity[velocity_step] / 255.0) * (layer.gain_position[note_p - 1] / 255.0)
        if processed:
            uses_layer_dsp = True
            pitch = variation_pitch_semitones
        else:
            gain *= layer.amplitude / 99.0
            pitch = layer.pitch_semitones + layer.pitch_fine_tenths / 10.0 + variation_pitch_semitones
        rendered.append(_decode_layer_audio(path, output_rate, pitch) * gain)
    frames = max(len(audio) for audio in rendered)
    mixed = np.zeros(frames, dtype=np.float32)
    for audio in rendered:
        mixed[:len(audio)] += audio
    if decay_percent != 100.0 and mixed.size:
        # The module's exact decay curve is undocumented.  Keep the decoded
        # attack intact and apply an explicit, bounded tail-energy model so a
        # design variation is audible without pretending this is a hardware
        # render.  Fixed-length prepared sources leave enough clean tail for it.
        position = np.linspace(0.0, 1.0, len(mixed), dtype=np.float32)
        mixed *= np.power(decay_percent / 100.0, 3.0 * position).astype(np.float32)
    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    if peak > 1.0:
        mixed /= peak
    output.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(output, output_rate, np.round(np.clip(mixed, -1.0, 1.0) * 32767).astype(np.int16))
    return PreviewRender(
        path=output, active_layers=tuple(layer.index for layer in layers), variation=variation,
        velocity_step=velocity_step + 1, note_p=note_p, round_robin_step=round_robin_step,
        mode=(
            ("codec DDrum4 décodé + DSP Layer ddrum4edit" if uses_layer_dsp else "codec DDrum4 décodé")
            + f" + modèle pitch {variation_pitch_semitones:+.2f} st / "
            + f"decay {decay_percent:.0f} % / gain"
            + ("; enveloppe/filtres Layer rendus" if uses_layer_dsp else "; enveloppe/filtres Layer non rendus")
        ),
    )
