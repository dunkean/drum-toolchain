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
    layers: tuple[MatrixLayer, ...] = ()
    encoded_blocks: int | None = None
    mem_left_delta_blocks: int | None = None
    status: str | None = None
    provenance: str | None = None

    @property
    def layer_count(self) -> int | None:
        return len(self.layers) if self.sound_id is not None else None


@dataclass(frozen=True)
class Ddrum4KitMatrix:
    manifest: Path
    sounds: tuple[MatrixSound, ...]
    report_paths: tuple[Path, ...]

    def sound(self, slot: int) -> MatrixSound:
        return self.sounds[slot - 1]


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
        parsed.append(MatrixLayer(
            index=index, source=_text(item.get("source")) or _text(item.get("raw_file")),
            wav=_path(item.get("wav") or item.get("prepared_file") or item.get("file"), base),
            status=_text(item.get("status")), provenance=_text(item.get("provenance")),
        ))
    return tuple(parsed)


def _sound(value: dict[str, Any], slot: int, base: Path) -> MatrixSound:
    sound_id = _text(value.get("sound_id")) or _text(value.get("id"))
    return MatrixSound(
        slot=slot, sound_id=sound_id, source=_text(value.get("source")) or _text(value.get("instrument")),
        layers=_layers(value.get("layers"), base),
        encoded_blocks=_blocks(value.get("encoded_blocks"), "encoded_blocks"),
        mem_left_delta_blocks=_blocks(value.get("mem_left_delta_blocks", value.get("measured_mem_left_delta_blocks")), "mem_left_delta_blocks"),
        status=_text(value.get("status")), provenance=_text(value.get("provenance")),
    )


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
    declared = [_sound(item, index, manifest.parent) for index, item in enumerate(_declared_sounds(_document(manifest)), 1)]
    facts = _reports(report_paths)
    merged: list[MatrixSound] = []
    for row in declared:
        report = facts.get(row.sound_id or "")
        if report is not None:
            report_document, report_path = report
            observed = _sound(report_document, row.slot, report_path.parent)
            row = replace(row,
                source=row.source or observed.source, layers=row.layers or observed.layers,
                encoded_blocks=observed.encoded_blocks if observed.encoded_blocks is not None else row.encoded_blocks,
                mem_left_delta_blocks=(observed.mem_left_delta_blocks if observed.mem_left_delta_blocks is not None else row.mem_left_delta_blocks),
                status=row.status or observed.status, provenance=row.provenance or observed.provenance)
        merged.append(row)
    while len(merged) < MAX_SOUNDS:
        merged.append(MatrixSound(slot=len(merged) + 1, status=MISSING))
    return Ddrum4KitMatrix(manifest, tuple(merged), report_paths)


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
            lines.append(f"  L{layer.index} | {layer.wav or UNKNOWN} | {layer.source or UNKNOWN} | {layer.resource_status} | {layer.status or UNKNOWN} | {layer.provenance or UNKNOWN}")
    return "\n".join(lines)
