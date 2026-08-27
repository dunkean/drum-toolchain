"""Read-only DDrum4 kit matrix for declared local bank artefacts.

This module intentionally understands only files selected by the operator.  It
does not inspect MIDI devices, call ddrum4edit, or infer module memory use.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import sys
from typing import Any, Iterable

import yaml


UNKNOWN = "unknown"
MISSING = "missing"
MAX_SOUNDS = 10
MAX_LAYERS = 10


@dataclass(frozen=True)
class MatrixLayer:
    """One declared WAV layer; all descriptive fields may be unknown."""

    index: int
    source: str | None = None
    wav: Path | None = None
    status: str | None = None
    provenance: str | None = None
    position: int | None = None
    velocity: int | None = None
    variation: tuple[int, ...] = ()
    pitch: int | None = None
    round_robin: int | None = None
    sample: int | None = None

    @property
    def resource_status(self) -> str:
        if self.wav is None:
            return UNKNOWN
        return "available" if self.wav.is_file() else MISSING


@dataclass(frozen=True)
class MatrixSound:
    """One DDrum4 Sound slot, including independently reported measurements."""

    slot: int
    sound_id: str | None = None
    source: str | None = None
    note_base: int | None = None
    note_p: int | None = None
    physical_channel: str | None = None
    variations: tuple[tuple[int, str | None], ...] = ()
    layers: tuple[MatrixLayer, ...] = ()
    encoded_blocks: int | None = None
    mem_left_delta_blocks: int | None = None
    status: str | None = None
    provenance: str | None = None

    @property
    def layer_count(self) -> int | None:
        return len(self.layers) if self.sound_id is not None else None

    @property
    def unique_sample_count(self) -> int | None:
        """Count explicitly numbered encoded samples, not mapping rows.

        Repeated sample identifiers are legitimate: a pitch-shifted variation
        can reuse one stored sample in more than one mapping row.
        """
        if not self.layers or any(layer.sample is None for layer in self.layers):
            return None
        return len({layer.sample for layer in self.layers})

    def contains_note(self, note: int) -> bool:
        return self.note_base is not None and self.note_p is not None and self.note_base <= note < self.note_base + self.note_p


@dataclass(frozen=True)
class Ddrum4KitMatrix:
    manifest: Path
    sounds: tuple[MatrixSound, ...]
    report_paths: tuple[Path, ...]
    bank_id: str | None = None
    bank_status: str | None = None
    capacity_blocks: int | None = None
    used_blocks: int | None = None
    free_blocks: int | None = None
    midi_channel: int | None = None
    local_control: str | None = None

    def sound(self, slot: int) -> MatrixSound:
        return self.sounds[slot - 1]

    def sound_for_note(self, note: int) -> MatrixSound | None:
        return next((sound for sound in self.sounds if sound.contains_note(note)), None)


def _document(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"cannot read declared matrix resource: {path}") from error
    try:
        value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise ValueError(f"cannot parse declared matrix resource: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"declared matrix resource must be a mapping: {path}")
    return value


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _blocks(value: object, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer when declared")
    return value


def _path(value: object, base: Path) -> Path | None:
    text = _text(value)
    if text is None:
        return None
    candidate = Path(text)
    return candidate if candidate.is_absolute() else base / candidate


def _layers(value: object, base: Path) -> tuple[MatrixLayer, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_LAYERS:
        raise ValueError("layers must be a list of at most 10 declared layers")
    parsed: list[MatrixLayer] = []
    for index, item in enumerate(value, 1):
        if isinstance(item, str):
            item = {"wav": item}
        if not isinstance(item, dict):
            raise ValueError("each declared layer must be a mapping or WAV path")
        variation = item.get("variation", ())
        if isinstance(variation, int): variation = (variation,)
        if not isinstance(variation, list | tuple) or any(not isinstance(number, int) or not 1 <= number <= 10 for number in variation):
            raise ValueError("layer variation must be one variation number or a list of 1..10")
        def optional_int(key: str) -> int | None:
            raw = item.get(key)
            if raw is None: return None
            if not isinstance(raw, int): raise ValueError(f"layer {key} must be an integer")
            return raw
        parsed.append(MatrixLayer(
            index=index, source=_text(item.get("source")) or _text(item.get("raw_file")),
            wav=_path(item.get("wav") or item.get("prepared_file") or item.get("file"), base),
            status=_text(item.get("status")), provenance=_text(item.get("provenance")),
            position=optional_int("position"), velocity=optional_int("velocity"),
            variation=tuple(variation), pitch=optional_int("pitch"), round_robin=optional_int("rr"),
            sample=optional_int("sample"),
        ))
    return tuple(parsed)


def _variations(value: object) -> tuple[tuple[int, str | None], ...]:
    """Keep declared variation labels without pretending they are WAV copies."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("variations must be a list when declared")
    parsed: list[tuple[int, str | None]] = []
    declared_numbers: set[int] = set()
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("number"), int):
            raise ValueError("each variation must declare an integer number")
        number = item["number"]
        if not 1 <= number <= 10:
            raise ValueError("variation number must be 1..10")
        if number in declared_numbers:
            raise ValueError("variation numbers must be unique within a Sound")
        declared_numbers.add(number)
        parsed.append((number, _text(item.get("name"))))
    return tuple(parsed)


def _sound(value: dict[str, Any], slot: int, base: Path) -> MatrixSound:
    sound_id = _text(value.get("sound_id")) or _text(value.get("id"))
    note_base = _blocks(value.get("note_base"), "note_base")
    note_p = _blocks(value.get("note_p"), "note_p")
    if (note_base is None) != (note_p is None):
        raise ValueError("note_base and note_p must be declared together")
    if note_base is not None and (note_base > 127 or note_p is None or not 1 <= note_p <= 128 - note_base):
        raise ValueError("note_base/note_p must describe a MIDI range within 0..127")
    return MatrixSound(
        slot=slot, sound_id=sound_id, source=_text(value.get("source")) or _text(value.get("instrument")),
        note_base=note_base, note_p=note_p,
        physical_channel=_text(value.get("physical_channel")), variations=_variations(value.get("variations")),
        layers=_layers(value.get("layers"), base),
        encoded_blocks=_blocks(value.get("encoded_blocks"), "encoded_blocks"),
        mem_left_delta_blocks=_blocks(value.get("mem_left_delta_blocks", value.get("measured_mem_left_delta_blocks")), "mem_left_delta_blocks"),
        status=_text(value.get("status")), provenance=_text(value.get("provenance")),
    )


def _midi_channel(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or not 1 <= value <= 16:
        raise ValueError("midi_channel must be 1..16 when declared")
    return value


def _declared_sounds(document: dict[str, Any]) -> list[dict[str, Any]]:
    sounds = document.get("sounds")
    if sounds is None and isinstance(document.get("bank"), dict):
        sounds = document["bank"].get("sounds")
    if sounds is None:
        return []
    if not isinstance(sounds, list) or len(sounds) > MAX_SOUNDS:
        raise ValueError("manifest sounds must be a list of at most 10 declared Sounds")
    if not all(isinstance(item, dict) for item in sounds):
        raise ValueError("each declared Sound must be a mapping")
    return sounds


def _reports(paths: Iterable[Path]) -> dict[str, tuple[dict[str, Any], Path]]:
    merged: dict[str, tuple[dict[str, Any], Path]] = {}
    for path in paths:
        document = _document(path)
        rows: list[dict[str, Any]]
        if isinstance(document.get("sound_id"), str):
            rows = [document]
        elif document.get("kind") == "ddrum4-actual-bank-report" and isinstance(document.get("sounds"), list):
            rows = []
            for item in document["sounds"]:
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    rows.append({**item, "sound_id": Path(item["path"]).stem})
        else:
            rows = [item for item in document.get("sounds", []) if isinstance(item, dict)]
        for row in rows:
            identifier = _text(row.get("sound_id")) or _text(row.get("id"))
            if identifier:
                prior = merged.get(identifier)
                merged[identifier] = ({**(prior[0] if prior else {}), **row}, path)
    return merged


def load_kit_matrix(manifest: Path, reports: Iterable[Path] = ()) -> Ddrum4KitMatrix:
    """Load declarations plus reports, retaining absent facts as ``None``/unknown.

    A manifest declares ``sounds`` (at its root or under ``bank``).  Reports are
    ddrum4-bank-builder build reports or its actual-bank report.  Report facts
    supplement, rather than estimate, a declared sound.
    """
    manifest = manifest.resolve()
    report_paths = tuple(path.resolve() for path in reports)
    document = _document(manifest)
    declared = [_sound(item, index, manifest.parent) for index, item in enumerate(_declared_sounds(document), 1)]
    facts = _reports(report_paths)
    merged: list[MatrixSound] = []
    for row in declared:
        report = facts.get(row.sound_id or "")
        if report is not None:
            report_document, report_path = report
            observed = _sound(report_document, row.slot, report_path.parent)
            row = replace(row,
                source=row.source or observed.source, layers=row.layers or observed.layers,
                physical_channel=row.physical_channel or observed.physical_channel,
                variations=row.variations or observed.variations,
                encoded_blocks=observed.encoded_blocks if observed.encoded_blocks is not None else row.encoded_blocks,
                mem_left_delta_blocks=(observed.mem_left_delta_blocks if observed.mem_left_delta_blocks is not None else row.mem_left_delta_blocks),
                status=row.status or observed.status, provenance=row.provenance or observed.provenance)
        merged.append(row)
    while len(merged) < MAX_SOUNDS:
        merged.append(MatrixSound(slot=len(merged) + 1, status=MISSING))
    bank = document.get("bank") if isinstance(document.get("bank"), dict) else {}
    capacity_blocks = _blocks(bank.get("capacity_blocks"), "capacity_blocks")
    used_blocks = _blocks(bank.get("used_blocks"), "used_blocks")
    free_blocks = _blocks(bank.get("free_blocks"), "free_blocks")
    if (capacity_blocks is not None and used_blocks is not None and free_blocks is not None
            and capacity_blocks != used_blocks + free_blocks):
        raise ValueError("bank capacity_blocks must equal used_blocks + free_blocks")
    return Ddrum4KitMatrix(
        manifest, tuple(merged), report_paths,
        bank_id=_text(bank.get("id")), bank_status=_text(bank.get("status")),
        capacity_blocks=capacity_blocks, used_blocks=used_blocks, free_blocks=free_blocks,
        midi_channel=_midi_channel(bank.get("midi_channel")),
        local_control=_text(bank.get("local_control")),
    )


def audition_command(wav: Path, platform: str | None = None) -> tuple[str, ...]:
    """Return the explicit local default-player command; never execute it."""
    if wav.suffix.lower() != ".wav":
        raise ValueError("audition accepts local WAV files only")
    platform = platform or sys.platform
    if platform.startswith("win"):
        return ("cmd", "/c", "start", "", str(wav))
    if platform == "darwin":
        return ("open", str(wav))
    return ("xdg-open", str(wav))


def format_matrix(matrix: Ddrum4KitMatrix) -> str:
    """Render a compact, dependency-free matrix table for the CLI."""
    lines = ["slot | sound id | source | layers | encoded blocks | MEM.LEFT delta | status | provenance",
             "---: | --- | --- | ---: | ---: | ---: | --- | ---"]
    for item in matrix.sounds:
        lines.append(" | ".join((str(item.slot), item.sound_id or MISSING, item.source or UNKNOWN,
                                  str(item.layer_count) if item.layer_count is not None else MISSING,
                                  str(item.encoded_blocks) if item.encoded_blocks is not None else UNKNOWN,
                                  str(item.mem_left_delta_blocks) if item.mem_left_delta_blocks is not None else UNKNOWN,
                                  item.status or UNKNOWN, item.provenance or UNKNOWN)))
        for layer in item.layers:
            details = ", ".join(part for part in (
                f"P{layer.position}" if layer.position is not None else "",
                f"v{layer.velocity}" if layer.velocity is not None else "",
                "V" + "/".join(str(number) for number in layer.variation) if layer.variation else "",
                f"pitch {layer.pitch:+d}" if layer.pitch is not None else "",
                f"RR{layer.round_robin}" if layer.round_robin is not None else "",
            ) if part)
            lines.append(f"  L{layer.index} | {layer.wav or UNKNOWN} | {layer.source or UNKNOWN} | {details or UNKNOWN} | {layer.resource_status} | {layer.status or UNKNOWN} | {layer.provenance or UNKNOWN}")
    return "\n".join(lines)
