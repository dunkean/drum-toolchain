"""Offline helpers for black-box reverse engineering of SD3 save files.

The module intentionally avoids any product-specific parsing assumptions.
It focuses on deterministic binary facts: hashes, byte-distribution summaries,
and controlled diffs between two or more files.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from math import log2
from pathlib import Path
import re
from typing import Any

import yaml


@dataclass(frozen=True)
class DiffRun:
    """A contiguous differing region between two files."""

    offset: int
    length_a: int
    length_b: int
    preview_a_hex: str
    preview_b_hex: str


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def byte_entropy(payload: bytes) -> float:
    if not payload:
        return 0.0
    counts = Counter(payload)
    total = float(len(payload))
    return -sum((count / total) * log2(count / total) for count in counts.values())


def scan_binary(path: Path) -> dict[str, Any]:
    payload = read_bytes(path)
    size = len(payload)
    unique = len(set(payload))
    zero_bytes = payload.count(0)
    ascii_printable = sum(1 for byte in payload if 32 <= byte <= 126)
    entropy = byte_entropy(payload)
    return {
        "path": str(path),
        "size_bytes": size,
        "sha256": sha256_hex(payload),
        "header_hex": payload[:32].hex(),
        "footer_hex": payload[-32:].hex() if payload else "",
        "unique_byte_values": unique,
        "zero_byte_ratio": round(zero_bytes / size, 6) if size else 0.0,
        "ascii_printable_ratio": round(ascii_printable / size, 6) if size else 0.0,
        "entropy_bits_per_byte": round(entropy, 6),
        "high_entropy_hint": entropy >= 7.5,
    }


def _preview_hex(payload: bytes, limit: int = 16) -> str:
    return payload[:limit].hex()


def diff_binaries(payload_a: bytes, payload_b: bytes) -> list[DiffRun]:
    runs: list[DiffRun] = []
    shared = min(len(payload_a), len(payload_b))
    index = 0
    while index < shared:
        if payload_a[index] == payload_b[index]:
            index += 1
            continue
        start = index
        while index < shared and payload_a[index] != payload_b[index]:
            index += 1
        chunk_a = payload_a[start:index]
        chunk_b = payload_b[start:index]
        runs.append(DiffRun(start, len(chunk_a), len(chunk_b), _preview_hex(chunk_a), _preview_hex(chunk_b)))
    if len(payload_a) != len(payload_b):
        start = shared
        tail_a = payload_a[start:]
        tail_b = payload_b[start:]
        runs.append(DiffRun(start, len(tail_a), len(tail_b), _preview_hex(tail_a), _preview_hex(tail_b)))
    return runs


def diff_files(path_a: Path, path_b: Path) -> dict[str, Any]:
    payload_a = read_bytes(path_a)
    payload_b = read_bytes(path_b)
    runs = diff_binaries(payload_a, payload_b)
    changed_a = sum(run.length_a for run in runs)
    changed_b = sum(run.length_b for run in runs)
    return {
        "base": str(path_a),
        "variant": str(path_b),
        "base_size_bytes": len(payload_a),
        "variant_size_bytes": len(payload_b),
        "base_sha256": sha256_hex(payload_a),
        "variant_sha256": sha256_hex(payload_b),
        "diff_run_count": len(runs),
        "changed_bytes_from_base": changed_a,
        "changed_bytes_from_variant": changed_b,
        "runs": [run.__dict__ for run in runs],
    }


def compare_set(base: Path, variants: list[Path], bin_size: int = 256, top_bins: int = 20) -> dict[str, Any]:
    if bin_size <= 0:
        raise ValueError("bin_size must be positive")
    if top_bins <= 0:
        raise ValueError("top_bins must be positive")
    base_payload = read_bytes(base)
    bins: dict[int, dict[str, int]] = {}
    file_summaries: list[dict[str, Any]] = []
    for variant in variants:
        diff = diff_binaries(base_payload, read_bytes(variant))
        changed = sum(run.length_a for run in diff)
        file_summaries.append({
            "path": str(variant),
            "diff_run_count": len(diff),
            "changed_bytes_from_base": changed,
        })
        seen_bins: set[int] = set()
        for run in diff:
            start = run.offset
            end = run.offset + max(run.length_a, run.length_b)
            cursor = start
            while cursor < end:
                bin_index = cursor // bin_size
                bin_start = bin_index * bin_size
                bin_end = bin_start + bin_size
                segment = min(end, bin_end) - cursor
                bucket = bins.setdefault(bin_index, {"byte_touches": 0, "file_hits": 0})
                bucket["byte_touches"] += segment
                if bin_index not in seen_bins:
                    bucket["file_hits"] += 1
                    seen_bins.add(bin_index)
                cursor += segment
    ranked = sorted(
        (
            {
                "bin_index": index,
                "offset_start": index * bin_size,
                "offset_end_exclusive": index * bin_size + bin_size,
                "byte_touches": facts["byte_touches"],
                "file_hits": facts["file_hits"],
            }
            for index, facts in bins.items()
        ),
        key=lambda item: (item["file_hits"], item["byte_touches"]),
        reverse=True,
    )
    return {
        "base": str(base),
        "base_size_bytes": len(base_payload),
        "variant_count": len(variants),
        "bin_size": bin_size,
        "top_bins": ranked[:top_bins],
        "files": file_summaries,
    }


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


_INSTBOX_RE = re.compile(r"^instbox\s+(\d+)\s+\{$")
_XPAD_RE = re.compile(r"^xpad\s+\d+\s+(\S+)\s+\{$")
_POS_RE = re.compile(r'^pos\s+"([^"]+)"')
_DRUM_RE = re.compile(r'^drum\s+"([^"]*)"\s+"([^"]*)"\s+(-?\d+)')
_ALIAS_RE = re.compile(r"^alias\s+(\S+)\s+(.+)$")


def _preset_lines(path: Path) -> tuple[list[str], bool]:
    payload = path.read_bytes()
    trailing_nul = payload.endswith(b"\x00")
    if trailing_nul:
        payload = payload[:-1]
    try:
        text = payload.decode("latin-1")
    except UnicodeDecodeError as error:  # pragma: no cover - latin-1 is total
        raise ValueError(f"cannot decode SD3 preset {path}") from error
    if not text.startswith("PlugVersion "):
        raise ValueError(f"not a supported text SD3 preset: {path}")
    return text.splitlines(keepends=True), trailing_nul


def _block_end(lines: list[str], start: int) -> int:
    depth = 0
    opened = False
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if stripped.endswith("{"):
            depth += 1
            opened = True
        elif stripped == "}":
            depth -= 1
            if opened and depth == 0:
                return index + 1
    raise ValueError(f"unterminated SD3 block beginning at line {start + 1}")


def _instrument_spans(lines: list[str]) -> dict[int, tuple[int, int]]:
    spans: dict[int, tuple[int, int]] = {}
    for index, line in enumerate(lines):
        match = _INSTBOX_RE.match(line.strip())
        if match:
            number = int(match.group(1))
            if number in spans:
                raise ValueError(f"duplicate instbox {number}")
            spans[number] = (index, _block_end(lines, index))
    return spans


def _block_inventory(number: int, block: list[str]) -> dict[str, Any]:
    library = ""
    position = ""
    drum_id = ""
    beater = ""
    aliases: list[dict[str, Any]] = []
    for line in block:
        stripped = line.strip()
        if match := _XPAD_RE.match(stripped):
            library = match.group(1)
        elif match := _POS_RE.match(stripped):
            position = match.group(1)
        elif match := _DRUM_RE.match(stripped):
            drum_id, beater = match.group(1), match.group(2)
        elif match := _ALIAS_RE.match(stripped):
            values = match.group(2).split()
            aliases.append({
                "pad": match.group(1),
                "values": [int(value) if value.isdigit() else value for value in values],
            })
    return {
        "instbox": number,
        "library": library,
        "position": position,
        "drum_id": drum_id,
        "beater": beater,
        "aliases": aliases,
    }


def preset_inventory(path: Path) -> dict[str, Any]:
    """Return the editable instrument/note facts from a text SD3 preset."""
    lines, trailing_nul = _preset_lines(path)
    instruments = [
        _block_inventory(number, lines[start:end])
        for number, (start, end) in sorted(_instrument_spans(lines).items())
    ]
    notes: dict[int, list[dict[str, Any]]] = {}
    for instrument in instruments:
        for alias in instrument["aliases"]:
            for value in alias["values"]:
                if isinstance(value, int):
                    notes.setdefault(value, []).append({
                        "instbox": instrument["instbox"],
                        "pad": alias["pad"],
                        "library": instrument["library"],
                        "drum_id": instrument["drum_id"],
                    })
    return {
        "path": str(path),
        "sha256": sha256_hex(path.read_bytes()),
        "trailing_nul": trailing_nul,
        "instrument_count": len(instruments),
        "instruments": instruments,
        "notes": {str(note): owners for note, owners in sorted(notes.items())},
    }


def _named_block(block: list[str], name: str) -> tuple[int, int]:
    marker = f"{name} {{"
    for index, line in enumerate(block):
        if line.strip() == marker:
            return index, _block_end(block, index)
    raise ValueError(f"missing {name} block")


def _rewrite_aliases(block: list[str], aliases: dict[str, list[Any]], drop_unspecified: bool) -> list[str]:
    rewritten: list[str] = []
    seen: set[str] = set()
    newline = "\r\n" if any(line.endswith("\r\n") for line in block) else "\n"
    for line in block:
        match = _ALIAS_RE.match(line.strip())
        if not match:
            rewritten.append(line)
            continue
        pad = match.group(1)
        if pad in aliases:
            values = " ".join(str(value) for value in aliases[pad])
            rewritten.append(f"alias {pad} {values}{newline}")
            seen.add(pad)
        elif not drop_unspecified:
            rewritten.append(line)
    missing = set(aliases) - seen
    if missing:
        raise ValueError(f"aliases do not exist in source block: {sorted(missing)}")
    return rewritten


def _clone_block(source: Path, source_instbox: int, target_instbox: int,
                 aliases: dict[str, list[Any]], base_mastermics: list[str]) -> list[str]:
    lines, _ = _preset_lines(source)
    spans = _instrument_spans(lines)
    if source_instbox not in spans:
        raise ValueError(f"instbox {source_instbox} not found in {source}")
    start, end = spans[source_instbox]
    block = list(lines[start:end])
    newline = "\r\n" if block[0].endswith("\r\n") else "\n"
    block[0] = f"instbox {target_instbox} {{{newline}"
    master_start, master_end = _named_block(block, "mastermics")
    block[master_start:master_end] = base_mastermics
    return _rewrite_aliases(block, aliases, drop_unspecified=True)


def build_megakit_preset(base: Path, recipe_path: Path, preset_library: Path,
                         output: Path, force: bool = False) -> dict[str, Any]:
    """Build a MegaKit from reviewed SD3 blocks without mutating source presets."""
    recipe = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    if not isinstance(recipe, dict) or recipe.get("kind") != "sd3-preset-build":
        raise ValueError("recipe must be an sd3-preset-build document")
    expected_base = str(recipe["base_sha256"]).lower()
    actual_base = sha256_hex(base.read_bytes())
    if actual_base != expected_base:
        raise ValueError(f"base SHA256 mismatch: expected {expected_base}, got {actual_base}")
    if output.exists() and not force:
        raise FileExistsError(f"output exists (pass force to replace generated output): {output}")

    lines, trailing_nul = _preset_lines(base)
    spans = _instrument_spans(lines)
    master_start, master_end = _named_block(lines[slice(*spans[0])], "mastermics")
    base_block = lines[slice(*spans[0])]
    base_mastermics = base_block[master_start:master_end]

    replacements: list[tuple[int, int, list[str]]] = []
    for number_text, aliases in recipe.get("base_aliases", {}).items():
        number = int(number_text)
        if number not in spans:
            raise ValueError(f"base instbox {number} does not exist")
        start, end = spans[number]
        replacements.append((start, end, _rewrite_aliases(lines[start:end], aliases, drop_unspecified=False)))
    for start, end, replacement in sorted(replacements, reverse=True):
        lines[start:end] = replacement

    clones: list[str] = []
    source_hashes: dict[str, str] = {}
    for clone in recipe.get("clones", []):
        source = preset_library / clone["source"]
        if not source.is_file():
            raise FileNotFoundError(f"required source preset is missing: {source}")
        actual_source = sha256_hex(source.read_bytes())
        expected_source = str(clone["source_sha256"]).lower()
        if actual_source != expected_source:
            raise ValueError(f"source SHA256 mismatch for {source}: expected {expected_source}, got {actual_source}")
        source_hashes[str(clone["source"])] = actual_source
        clones.extend(_clone_block(
            source,
            int(clone["source_instbox"]),
            int(clone["target_instbox"]),
            clone["aliases"],
            base_mastermics,
        ))

    mixer_index = next((index for index, line in enumerate(lines) if line.strip() == "mixer {"), None)
    if mixer_index is None:
        raise ValueError("base preset has no mixer block")
    lines[mixer_index:mixer_index] = clones
    payload = "".join(lines).encode("latin-1") + (b"\x00" if trailing_nul else b"")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)

    inventory = preset_inventory(output)
    expected_notes = {int(value) for value in recipe.get("expected_unique_notes", [])}
    duplicate_notes = {
        note: owners for note, owners in inventory["notes"].items()
        if int(note) in expected_notes and len(owners) != 1
    }
    missing_notes = sorted(expected_notes - {int(note) for note in inventory["notes"]})
    if missing_notes or duplicate_notes:
        output.unlink(missing_ok=True)
        raise ValueError(f"generated mapping invalid; missing={missing_notes}, duplicate={duplicate_notes}")
    return {
        "output": str(output),
        "sha256": inventory["sha256"],
        "size_bytes": output.stat().st_size,
        "instrument_count": inventory["instrument_count"],
        "base_sha256": actual_base,
        "source_sha256": source_hashes,
        "validated_unique_notes": sorted(expected_notes),
    }


def _midi_note_name(note: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{names[note % 12]}{note // 12 - 1}"


def megakit_markdown(plan_path: Path, note_map_path: Path, preset_path: Path) -> str:
    """Render the complete logical/capture/scene table from generated facts."""
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    note_map = json.loads(note_map_path.read_text(encoding="utf-8"))
    inventory = preset_inventory(preset_path)
    if not isinstance(plan, dict) or plan.get("kind") != "sd3-megakit-plan":
        raise ValueError("unsupported SD3 MegaKit plan")
    if not isinstance(note_map, dict) or note_map.get("format") != "drum-note-map/v1":
        raise ValueError("unsupported SD3 note map")
    velocity_sets = plan.get("velocity_sets", {})
    routes_by_logical: dict[str, list[str]] = {}
    for mapping in note_map.get("mappings", []):
        if isinstance(mapping, dict) and isinstance(mapping.get("logical_target"), str):
            routes_by_logical.setdefault(mapping["logical_target"], []).append(str(mapping.get("id", "")))
    lines = [
        "# Greg Hybrid r15 — SD3 MegaKit",
        "",
        f"- Preset: `{preset_path.name}`",
        f"- Preset SHA-256: `{inventory['sha256']}`",
        f"- Instruments SD3: **{inventory['instrument_count']}**",
        "Convention de nommage: MIDI 0 = C-1.",
        "",
        "Une ligne `variation partagée` ne duplique aucun WAV : elle réutilise exactement la note et le son indiqués par `shared_with`.",
        "",
        "| Son logique | Note | Source SD3 réelle | Layers de capture | RR | Kits / palettes | Statut |",
        "| --- | ---: | --- | --- | ---: | --- | --- |",
    ]
    for articulation in plan.get("articulations", []):
        if not isinstance(articulation, dict):
            continue
        logical = str(articulation["logical"])
        note = int(articulation["note"])
        owners = inventory["notes"].get(str(note), [])
        if len(owners) == 1:
            owner = owners[0]
            actual = f"{owner['library']} / {owner['drum_id'] or owner['pad']} / {owner['pad']}"
        else:
            actual = "ERREUR: note absente" if not owners else "ERREUR: collision"
        velocities = velocity_sets.get(articulation.get("velocities"), [])
        layers = ", ".join(str(value) for value in velocities) if velocities else "0"
        rr = articulation.get("rr", 0)
        routes = sorted(set(routes_by_logical.get(logical, [])))
        usages: list[str] = []
        for route in routes:
            scene, _, detail = route.partition(".")
            label = scene
            if "when-" in detail:
                condition = detail.split("when-", 1)[1].rsplit("-", 1)[0]
                label += f" ({condition})"
            usages.append(label)
        usage_text = ", ".join(sorted(set(usages))) or "partagé uniquement"
        if articulation.get("capture") is True:
            variants = articulation.get("capture_variants")
            if isinstance(variants, list) and variants:
                positions = []
                for variant in variants:
                    controllers = variant.get("controllers", []) if isinstance(variant, dict) else []
                    cc_text = "+".join(f"CC{pair[0]}={pair[1]}" for pair in controllers
                                       if isinstance(pair, list) and len(pair) == 2)
                    positions.append(f"{variant.get('articulation')} {cc_text} → DG {variant.get('drumgizmo_note')}")
                status = "captures positionnelles: " + "; ".join(positions)
            else:
                status = "capture dédiée"
        else:
            status = f"variation partagée → {articulation.get('shared_with', 'même note')}"
        lines.append(
            f"| `{logical}` | {note} ({_midi_note_name(note)}) | {actual} | {layers} | {rr} | {usage_text} | {status} |"
        )
    lines.extend([
        "",
        "## Réserve de position de caisse claire",
        "",
        "Ces notes existent réellement dans le preset mais ne sont pas routées avant la mesure du message de position des pads.",
        "",
        "| Son réservé | Note | Source SD3 réelle | État |",
        "| --- | ---: | --- | --- |",
    ])
    for articulation in plan.get("positional_reserve", []):
        note = int(articulation["note"])
        owners = inventory["notes"].get(str(note), [])
        if len(owners) == 1:
            owner = owners[0]
            actual = f"{owner['library']} / {owner['drum_id'] or owner['pad']} / {owner['pad']}"
        else:
            actual = "ERREUR: note absente ou collision"
        lines.append(f"| `{articulation['logical']}` | {note} ({_midi_note_name(note)}) | {actual} | {articulation['status']} |")
    lines.extend([
        "",
        "## Contrôle global",
        "",
        "- Scene: Program Change sur CH14 ou CH15.",
        "- VP1 Snare 1: CC20; VP2 surface flexible: CC21; VP3 famille Stack: CC22; VP4 variante Perc: CC23.",
        "- Hi-hat SD3: notes 64/65 et ouverture continue CC4 sur le canal 10; pédale 66/67.",
        "- Les modules physiques gardent des notes brutes stables. Le Converter et Arduino appliquent la scène et les palettes.",
        "",
    ])
    return "\n".join(lines)
