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
from math import isfinite, log2
from pathlib import Path
import re
from typing import Any

import yaml


MAX_PAD_VOLUME = 4.0


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
_XPAD_RE = re.compile(r"^xpad\s+(\d+)\s+(\S+)\s+\{$")
_POS_RE = re.compile(r'^pos\s+"([^"]+)"')
_DRUM_RE = re.compile(r'^drum\s+"([^"]*)"(?:\s+"([^"]*)")?(?:\s+-?\d+)?')
_ALIAS_RE = re.compile(r"^alias\s+(\S+)\s+(.+)$")
_MIC_ENTRY_RE = re.compile(r'^("([^"]+)"\s+"[^"]*"\s+[01]\s+)-?\d+$')
_STACK_RE = re.compile(r"^stack\s+(\d+)\s+(\d+)\s+(\S+)\s+(\d+)\s+(\S+)\s+(active|inactive)$")


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


def _xpad_spans(block: list[str]) -> dict[int, tuple[int, int]]:
    """Return xpad spans that are direct children of one instbox block."""
    spans: dict[int, tuple[int, int]] = {}
    depth = 0
    for index, line in enumerate(block):
        stripped = line.strip()
        if depth == 1 and (match := _XPAD_RE.match(stripped)):
            number = int(match.group(1))
            if number in spans:
                raise ValueError(f"duplicate xpad {number}")
            spans[number] = (index, _block_end(block, index))
        if stripped.endswith("{"):
            depth += 1
        elif stripped == "}":
            depth -= 1
    return spans


def _xpad_inventory(number: int, xpad_number: int, block: list[str]) -> dict[str, Any]:
    library = ""
    position = ""
    drum_id = ""
    beater = ""
    aliases: list[dict[str, Any]] = []
    pads_start, pads_end = _named_block(block, "pads")
    pad_alias_lines = {index for index in range(pads_start + 1, pads_end - 1)}
    for index, line in enumerate(block):
        stripped = line.strip()
        if match := _XPAD_RE.match(stripped):
            library = match.group(2)
        elif match := _POS_RE.match(stripped):
            position = match.group(1)
        elif match := _DRUM_RE.match(stripped):
            drum_id, beater = match.group(1), match.group(2) or ""
        elif index in pad_alias_lines and (match := _ALIAS_RE.match(stripped)):
            values = match.group(2).split()
            aliases.append({
                "pad": match.group(1),
                "values": [int(value) if value.isdigit() else value for value in values],
            })
    return {
        "instbox": number,
        "xpad": xpad_number,
        "library": library,
        "position": position,
        "drum_id": drum_id,
        "beater": beater,
        "aliases": aliases,
    }


def _block_inventory(number: int, block: list[str]) -> dict[str, Any]:
    xpads = [
        _xpad_inventory(number, xpad_number, block[start:end])
        for xpad_number, (start, end) in sorted(_xpad_spans(block).items())
    ]
    if not xpads:
        raise ValueError(f"instbox {number} has no xpad")
    # Keep the historical summary fields for reports, but expose xpad-level
    # ownership so aliases can never be attributed to another stacked sound.
    summary = dict(xpads[-1])
    summary["xpads"] = xpads
    summary["aliases"] = [alias for xpad in xpads for alias in xpad["aliases"]]
    summary["stack_routes"] = [
        {
            "index": int(match.group(1)),
            "source_xpad": int(match.group(2)),
            "source_pad": match.group(3),
            "target_xpad": int(match.group(4)),
            "target_pad": match.group(5),
            "active": match.group(6) == "active",
        }
        for line in block
        if (match := _STACK_RE.match(line.strip()))
    ]
    return summary


def preset_inventory(path: Path) -> dict[str, Any]:
    """Return the editable instrument/note facts from a text SD3 preset."""
    lines, trailing_nul = _preset_lines(path)
    instruments = [
        _block_inventory(number, lines[start:end])
        for number, (start, end) in sorted(_instrument_spans(lines).items())
    ]
    notes: dict[int, list[dict[str, Any]]] = {}
    for instrument in instruments:
        for xpad in instrument["xpads"]:
            for alias in xpad["aliases"]:
                for value in alias["values"]:
                    if isinstance(value, int):
                        notes.setdefault(value, []).append({
                            "instbox": instrument["instbox"],
                            "xpad": xpad["xpad"],
                            "pad": alias["pad"],
                            "library": xpad["library"],
                            "drum_id": xpad["drum_id"],
                        })
    return {
        "path": str(path),
        "sha256": sha256_hex(path.read_bytes()),
        "trailing_nul": trailing_nul,
        "instrument_count": len(instruments),
        "instruments": instruments,
        "notes": {str(note): owners for note, owners in sorted(notes.items())},
    }


def _direct_child_spans(block: list[str]) -> list[tuple[str, int, int]]:
    """Return the direct named children of a brace-delimited SD3 block."""
    children: list[tuple[str, int, int]] = []
    depth = 0
    index = 0
    while index < len(block):
        stripped = block[index].strip()
        if stripped.endswith("{"):
            if depth == 1:
                end = _block_end(block, index)
                children.append((stripped[:-1].strip(), index, end))
                index = end
                continue
            depth += 1
        elif stripped == "}":
            depth -= 1
        index += 1
    return children


def _direct_properties(block: list[str]) -> dict[str, str]:
    properties: dict[str, str] = {}
    depth = 0
    for line in block:
        stripped = line.strip()
        if stripped.endswith("{"):
            depth += 1
            continue
        if stripped == "}":
            depth -= 1
            continue
        if depth != 1 or not stripped:
            continue
        key, separator, value = stripped.partition(" ")
        if separator:
            properties[key] = value
    return properties


def mixer_inventory(path: Path) -> dict[str, Any]:
    """Return top-level SD3 mixer channels, buses, routes, gains and effects."""
    lines, _ = _preset_lines(path)
    mixer_start, mixer_end = _named_block(lines, "mixer")
    mixer = lines[mixer_start:mixer_end]
    entries: list[dict[str, Any]] = []
    for name, start, end in _direct_child_spans(mixer):
        child = mixer[start:end]
        properties = _direct_properties(child)
        if name.startswith("buss "):
            kind = "bus"
        elif name.startswith("output "):
            kind = "output"
        else:
            kind = "channel"
        entries.append({
            "name": name,
            "kind": kind,
            "volume": float(properties["volume"]) if "volume" in properties else None,
            "route": properties.get("route"),
            "mute": int(properties["mute"]) if "mute" in properties else None,
            "hidden": any(line.strip() == "hidden" for line in child),
            "effect_count": sum(
                1 for child_name, _, _ in _direct_child_spans(child)
                if child_name.startswith("effect ")
            ),
        })
    return {
        "path": str(path),
        "sha256": sha256_hex(path.read_bytes()),
        "entry_count": len(entries),
        "entries": entries,
    }


def _validate_mixer_routes(path: Path) -> list[str]:
    """Prove that every audible channel reaches a real stereo bus and output."""
    entries = {entry["name"]: entry for entry in mixer_inventory(path)["entries"]}
    validated: set[str] = set()

    def visit(name: str, stack: tuple[str, ...]) -> None:
        if name in validated:
            return
        if name in stack:
            raise ValueError(f"mixer route cycle: {' -> '.join((*stack, name))}")
        entry = entries.get(name)
        if entry is None:
            raise ValueError(f"mixer route target does not exist: {name}")
        route = entry.get("route")
        if not isinstance(route, str):
            raise ValueError(f"mixer entry has no route: {name}")
        kind, separator, number_text = route.partition(" ")
        if not separator or not number_text.lstrip("-").isdigit():
            raise ValueError(f"unsupported mixer route for {name}: {route}")
        number = int(number_text)
        if number < 0:
            raise ValueError(f"mixer entry is disconnected: {name} -> {route}")
        if kind == "output":
            target = f"output {number}"
            if target not in entries:
                raise ValueError(f"mixer output does not exist: {name} -> {target}")
        elif kind == "buss":
            # SD3 route buss N points to the serialized stereo pair 2N / 2N+1.
            for target in (f"buss {2 * number}", f"buss {2 * number + 1}"):
                visit(target, (*stack, name))
        else:
            raise ValueError(f"unsupported mixer route for {name}: {route}")
        validated.add(name)

    for name, entry in entries.items():
        if entry["kind"] == "channel" and entry.get("route") is not None and entry.get("mute") != 1:
            visit(name, ())
    return sorted(validated)


def _validate_expected_mappings(inventory: dict[str, Any], expected: dict[Any, Any]) -> list[int]:
    """Validate semantic note ownership, not merely note uniqueness."""
    validated: list[int] = []
    for note_text, requested in expected.items():
        note = int(note_text)
        owners = inventory["notes"].get(str(note), [])
        if len(owners) != 1:
            raise ValueError(f"expected mapping note {note} has {len(owners)} owners")
        if not isinstance(requested, dict):
            raise ValueError(f"expected mapping note {note} must be an object")
        owner = owners[0]
        mismatches = {
            key: (owner.get(key), value)
            for key, value in requested.items()
            if owner.get(key) != value
        }
        if mismatches:
            raise ValueError(f"expected mapping mismatch for note {note}: {mismatches}")
        validated.append(note)
    return sorted(validated)


def _validate_expected_stack_mappings(inventory: dict[str, Any], expected: dict[Any, Any]) -> list[int]:
    """Prove that an aliased source reaches every intended stacked voice."""
    instruments = {instrument["instbox"]: instrument for instrument in inventory["instruments"]}
    validated: list[int] = []
    for note_text, requested in expected.items():
        note = int(note_text)
        owners = inventory["notes"].get(str(note), [])
        if len(owners) != 1:
            raise ValueError(f"expected stack mapping note {note} has {len(owners)} owners")
        owner = owners[0]
        instrument = instruments[owner["instbox"]]
        active = [
            route for route in instrument["stack_routes"]
            if route["active"]
            and route["source_xpad"] == owner["xpad"]
            and route["source_pad"] == owner["pad"]
        ]
        if not active:
            raise ValueError(f"expected stack mapping note {note} has no active target")
        source_facts = {
            "instbox": owner["instbox"],
            "source_xpad": owner["xpad"],
            "source_pad": owner["pad"],
        }
        expected_targets = requested.get("targets") if isinstance(requested, dict) else None
        if expected_targets is not None:
            if not isinstance(expected_targets, list) or not expected_targets:
                raise ValueError(f"expected stack mapping note {note} targets must be a non-empty list")
            actual_targets: list[dict[str, Any]] = []
            for route in active:
                targets = [xpad for xpad in instrument["xpads"] if xpad["xpad"] == route["target_xpad"]]
                if len(targets) != 1:
                    raise ValueError(f"expected stack mapping note {note} target xpad is missing")
                target = targets[0]
                actual_targets.append({
                    "target_xpad": route["target_xpad"],
                    "target_pad": route["target_pad"],
                    "target_library": target["library"],
                    "target_drum_id": target["drum_id"],
                })
            normalize = lambda values: sorted(values, key=lambda value: (
                int(value["target_xpad"]), str(value["target_pad"]),
                str(value["target_library"]), str(value["target_drum_id"]),
            ))
            if normalize(actual_targets) != normalize(expected_targets):
                raise ValueError(
                    f"expected stack mapping targets mismatch for note {note}: "
                    f"actual={normalize(actual_targets)}, expected={normalize(expected_targets)}"
                )
            facts = source_facts
            requested_facts = {key: value for key, value in requested.items() if key != "targets"}
        else:
            if len(active) != 1:
                raise ValueError(f"expected stack mapping note {note} has {len(active)} active targets")
            route = active[0]
            targets = [xpad for xpad in instrument["xpads"] if xpad["xpad"] == route["target_xpad"]]
            if len(targets) != 1:
                raise ValueError(f"expected stack mapping note {note} target xpad is missing")
            target = targets[0]
            facts = {
                **source_facts,
                "target_xpad": route["target_xpad"],
                "target_pad": route["target_pad"],
                "target_library": target["library"],
                "target_drum_id": target["drum_id"],
            }
            requested_facts = requested
        mismatches = {
            key: (facts.get(key), value)
            for key, value in requested_facts.items()
            if facts.get(key) != value
        }
        if mismatches:
            raise ValueError(f"expected stack mapping mismatch for note {note}: {mismatches}")
        validated.append(note)
    return sorted(validated)


def _apply_mixer_overrides(lines: list[str], overrides: dict[str, dict[str, Any]]) -> list[str]:
    if not overrides:
        return lines
    mixer_start, mixer_end = _named_block(lines, "mixer")
    mixer = list(lines[mixer_start:mixer_end])
    children = {name: (start, end) for name, start, end in _direct_child_spans(mixer)}
    missing = sorted(set(overrides) - set(children))
    if missing:
        raise ValueError(f"mixer entries do not exist in base preset: {missing}")

    replacements: list[tuple[int, int, list[str]]] = []
    supported = {"volume", "route", "mute", "solo", "username", "clear_effects"}
    for name, requested in overrides.items():
        unsupported = sorted(set(requested) - supported)
        if unsupported:
            raise ValueError(f"unsupported mixer overrides for {name}: {unsupported}")
        start, end = children[name]
        block = list(mixer[start:end])
        clear_effects = requested.get("clear_effects", False)
        if not isinstance(clear_effects, bool):
            raise ValueError(f"mixer clear_effects override for {name} must be boolean")
        if clear_effects:
            effect_spans = [
                (effect_start, effect_end)
                for child_name, effect_start, effect_end in _direct_child_spans(block)
                if child_name.startswith("effect ")
            ]
            for effect_start, effect_end in sorted(effect_spans, reverse=True):
                block[effect_start:effect_end] = []
        newline = "\r\n" if block[0].endswith("\r\n") else "\n"
        depth = 0
        found: set[str] = set()
        for index, line in enumerate(block):
            stripped = line.strip()
            if stripped.endswith("{"):
                depth += 1
                continue
            if stripped == "}":
                depth -= 1
                continue
            if depth != 1:
                continue
            key = stripped.partition(" ")[0]
            if key in requested and key != "clear_effects":
                value = f'"{requested[key]}"' if key == "username" else requested[key]
                block[index] = f"{key} {value}{newline}"
                found.add(key)
        if "username" in requested and "username" not in found:
            route_index = next(
                (index for index, line in enumerate(block) if line.strip().startswith("route ")),
                len(block) - 1,
            )
            block.insert(route_index, f'username "{requested["username"]}"{newline}')
            found.add("username")
        absent = sorted(set(requested) - found - {"clear_effects"})
        if absent:
            raise ValueError(f"mixer properties do not exist for {name}: {absent}")
        replacements.append((start, end, block))
    for start, end, replacement in sorted(replacements, reverse=True):
        mixer[start:end] = replacement
    lines[mixer_start:mixer_end] = mixer
    return lines


def _apply_mixer_effect_imports(lines: list[str], imports: list[dict[str, Any]],
                                preset_library: Path) -> dict[str, str]:
    source_hashes: dict[str, str] = {}
    for item in imports:
        source = preset_library / item["source"]
        if not source.is_file():
            raise FileNotFoundError(f"required mixer source preset is missing: {source}")
        actual_source = sha256_hex(source.read_bytes())
        expected_source = str(item["source_sha256"]).lower()
        if actual_source != expected_source:
            raise ValueError(
                f"mixer source SHA256 mismatch for {source}: expected {expected_source}, got {actual_source}"
            )
        source_hashes[str(item["source"])] = actual_source
        source_lines, _ = _preset_lines(source)
        source_mixer_start, source_mixer_end = _named_block(source_lines, "mixer")
        source_mixer = source_lines[source_mixer_start:source_mixer_end]
        source_children = {
            name: (start, end) for name, start, end in _direct_child_spans(source_mixer)
        }
        source_name = str(item["source_entry"])
        if source_name not in source_children:
            raise ValueError(f"mixer source entry does not exist: {source_name}")
        source_start, source_end = source_children[source_name]
        source_block = source_mixer[source_start:source_end]
        effects = [
            source_block[start:end]
            for name, start, end in _direct_child_spans(source_block)
            if name.startswith("effect ")
        ]

        mixer_start, mixer_end = _named_block(lines, "mixer")
        mixer = list(lines[mixer_start:mixer_end])
        target_children = {name: (start, end) for name, start, end in _direct_child_spans(mixer)}
        target_name = str(item["target_entry"])
        if target_name not in target_children:
            raise ValueError(f"mixer target entry does not exist: {target_name}")
        target_start, target_end = target_children[target_name]
        target = list(mixer[target_start:target_end])
        existing_effects = [
            (start, end) for name, start, end in _direct_child_spans(target)
            if name.startswith("effect ")
        ]
        for start, end in sorted(existing_effects, reverse=True):
            target[start:end] = []
        insert_at = next(
            (index for index, line in enumerate(target) if line.strip().startswith("solo ")),
            len(target) - 1,
        )
        imported_lines = [line for effect in effects for line in effect]
        target[insert_at:insert_at] = imported_lines
        mixer[target_start:target_end] = target
        lines[mixer_start:mixer_end] = mixer
    return source_hashes


def _named_block(block: list[str], name: str) -> tuple[int, int]:
    marker = f"{name} {{"
    for index, line in enumerate(block):
        if line.strip() == marker:
            return index, _block_end(block, index)
    raise ValueError(f"missing {name} block")


def _rewrite_all_named_blocks(block: list[str], name: str, replacement: list[str]) -> list[str]:
    """Replace every named block, including one inside each stacked xpad."""
    rewritten = list(block)
    starts = [index for index, line in enumerate(rewritten) if line.strip() == f"{name} {{"]
    if not starts:
        raise ValueError(f"missing {name} block")
    for start in reversed(starts):
        end = _block_end(rewritten, start)
        rewritten[start:end] = replacement
    return rewritten


def _rewrite_aliases(block: list[str], aliases: dict[str, list[Any]], drop_unspecified: bool,
                     add_missing: bool = False) -> list[str]:
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
    if missing and add_missing:
        pads = {
            match.group(1)
            for line in rewritten
            if (match := re.match(r"^pad\s+(\S+)\s+\{$", line.strip()))
        }
        unknown_pads = missing - pads
        if unknown_pads:
            raise ValueError(f"aliases reference pads absent from selected xpad: {sorted(unknown_pads)}")
        xpad_spans = _xpad_spans(rewritten)
        if len(xpad_spans) != 1:
            raise ValueError("adding aliases requires exactly one selected xpad")
        pads_start, pads_end = _named_block(rewritten, "pads")
        additions = [
            f"alias {pad} {' '.join(str(value) for value in aliases[pad])}{newline}"
            for pad in sorted(missing)
        ]
        rewritten[pads_end - 1:pads_end - 1] = additions
        seen.update(missing)
        missing = set()
    if missing:
        raise ValueError(f"aliases do not exist in source block: {sorted(missing)}")
    return rewritten


def _rewrite_xpad_aliases(block: list[str], aliases_by_xpad: dict[int, dict[str, list[Any]]]) -> list[str]:
    """Rewrite aliases independently while preserving a multi-xpad instrument stack."""
    rewritten = list(block)
    spans = _xpad_spans(rewritten)
    unknown = sorted(set(aliases_by_xpad) - set(spans))
    if unknown:
        raise ValueError(f"xpad aliases reference absent xpads: {unknown}")
    newline = "\r\n" if rewritten[0].endswith("\r\n") else "\n"
    for number, (start, end) in sorted(spans.items(), reverse=True):
        requested = aliases_by_xpad.get(number, {})
        wrapped = [f"instbox 0 {{{newline}", *rewritten[start:end], f"}}{newline}"]
        wrapped = _rewrite_aliases(
            wrapped,
            requested,
            drop_unspecified=True,
            add_missing=bool(requested),
        )
        rewritten[start:end] = wrapped[1:-1]
    return rewritten


def _rewrite_stack_routes(block: list[str], routes: list[dict[str, Any]]) -> list[str]:
    """Replace native SD3 stack links with reviewed proxy-to-xpad routes."""
    if not routes:
        return block
    spans = _xpad_spans(block)
    pad_names: dict[int, set[str]] = {}
    for number, (start, end) in spans.items():
        pad_names[number] = {
            match.group(1)
            for line in block[start:end]
            if (match := re.match(r"^pad\s+(\S+)\s+\{$", line.strip()))
        }
    normalized: list[tuple[int, str, int, str, bool]] = []
    for index, route in enumerate(routes):
        if not isinstance(route, dict):
            raise ValueError(f"stack route {index} must be an object")
        unknown = sorted(set(route) - {"source_xpad", "source_pad", "target_xpad", "target_pad", "active"})
        if unknown:
            raise ValueError(f"stack route {index} has unsupported fields: {unknown}")
        source_xpad = int(route["source_xpad"])
        target_xpad = int(route["target_xpad"])
        source_pad = str(route["source_pad"])
        target_pad = str(route["target_pad"])
        active = route.get("active", True)
        if not isinstance(active, bool):
            raise ValueError(f"stack route {index} active must be boolean")
        if source_xpad not in spans or source_pad not in pad_names[source_xpad]:
            raise ValueError(f"stack route {index} source pad does not exist: xpad {source_xpad}.{source_pad}")
        if target_xpad not in spans or target_pad not in pad_names[target_xpad]:
            raise ValueError(f"stack route {index} target pad does not exist: xpad {target_xpad}.{target_pad}")
        normalized.append((source_xpad, source_pad, target_xpad, target_pad, active))

    rewritten = [line for line in block if not _STACK_RE.match(line.strip())]
    newline = "\r\n" if rewritten[0].endswith("\r\n") else "\n"
    additions = [
        f"stack {index} {source_xpad} {source_pad} {target_xpad} {target_pad} "
        f"{'active' if active else 'inactive'}{newline}"
        for index, (source_xpad, source_pad, target_xpad, target_pad, active) in enumerate(normalized)
    ]
    rewritten[-1:-1] = additions
    return rewritten


def _rewrite_pad_overrides(block: list[str], overrides: dict[str, dict[str, Any]]) -> list[str]:
    """Apply reviewed per-articulation scalar properties to a cloned instrument."""
    supported = {"pitch", "pvolume"}
    unknown_properties = {
        property_name
        for values in overrides.values()
        for property_name in values
        if property_name not in supported
    }
    if unknown_properties:
        raise ValueError(f"unsupported pad override properties: {sorted(unknown_properties)}")
    rewritten = list(block)
    seen: set[str] = set()
    # Work backwards because inserting a missing property changes later spans.
    pad_spans: list[tuple[str, int, int]] = []
    for index, line in enumerate(rewritten):
        match = re.match(r"^pad\s+(\S+)\s+\{$", line.strip())
        if match:
            pad_spans.append((match.group(1), index, _block_end(rewritten, index)))
    for pad, start, end in reversed(pad_spans):
        if pad not in overrides:
            continue
        seen.add(pad)
        for property_name, raw_value in overrides[pad].items():
            value = float(raw_value)
            if not isfinite(value) or not 0 < value <= MAX_PAD_VOLUME:
                raise ValueError(
                    f"pad override {pad}.{property_name} must be finite and in (0, {MAX_PAD_VOLUME}]"
                )
            value_text = f"{value:.6f}".rstrip("0").rstrip(".")
            newline = "\r\n" if rewritten[start].endswith("\r\n") else "\n"
            property_index = next(
                (index for index in range(start + 1, end - 1)
                 if rewritten[index].strip().startswith(f"{property_name} ")),
                None,
            )
            replacement = f"{property_name} {value_text}{newline}"
            if property_index is not None:
                rewritten[property_index] = replacement
            else:
                insert_at = next(
                    (index for index in range(start + 1, end - 1)
                     if rewritten[index].strip().startswith("maxpoly ")),
                    end - 1,
                )
                rewritten.insert(insert_at, replacement)
    missing = set(overrides) - seen
    if missing:
        raise ValueError(f"pad overrides do not exist in source block: {sorted(missing)}")
    return rewritten


def _master_entries(mastermics: list[str]) -> dict[str, int]:
    entries: dict[str, int] = {}
    for line in mastermics:
        match = _MIC_ENTRY_RE.match(line.strip())
        if match:
            name = match.group(2)
            if name in entries:
                raise ValueError(f"duplicate master mic name: {name}")
            # Stereo master channels reserve two serialized ordinals, so the
            # visible entry position is not its routable micmap index.
            entries[name] = int(line.strip().rsplit(" ", 1)[1])
    return entries


def _rewrite_micmaps(block: list[str], base_mastermics: list[str], base_mic_count: int,
                     overrides: dict[str, Any], exact_match: bool,
                     require_explicit: bool,
                     require_used_explicit_pads: set[str] | None = None,
                     require_used_explicit_xpad_pads: dict[int, set[str]] | None = None,
                     preserve_disabled: bool = False) -> list[str]:
    entries = _master_entries(base_mastermics)
    resolved: dict[str, int] = {}
    for source_name, target in overrides.items():
        if target is None:
            resolved[source_name] = -1
        elif isinstance(target, int):
            if target < 0 or target >= base_mic_count:
                raise ValueError(f"master mic index out of range for {source_name}: {target}")
            resolved[source_name] = target
        else:
            target_name = str(target)
            if target_name not in entries:
                raise ValueError(f"master mic does not exist for {source_name}: {target_name}")
            resolved[source_name] = entries[target_name]

    micmap_starts = [index for index, line in enumerate(block) if line.strip() == "micmap {"]
    source_names: set[str] = set()
    for start in micmap_starts:
        end = _block_end(block, start)
        depth = 0
        for line in block[start:end]:
            stripped = line.strip()
            if stripped.endswith("{"):
                depth += 1
                continue
            if stripped == "}":
                depth -= 1
                continue
            if depth == 1 and (match := _MIC_ENTRY_RE.match(stripped)):
                source_names.add(match.group(2))
    if require_explicit:
        missing_explicit = sorted(source_names - set(overrides))
        if missing_explicit:
            raise ValueError(f"micmap entries require explicit map or null: {missing_explicit}")
    if require_used_explicit_pads or require_used_explicit_xpad_pads:
        used_sources: set[str] = set()
        found_pads: set[str] = set()

        def collect_used_mics(start: int, end: int, requested: set[str], label: str) -> None:
            for index in range(start, end):
                match = re.match(r"^pad\s+(\S+)\s+\{$", block[index].strip())
                if not match or match.group(1) not in requested:
                    continue
                pad = match.group(1)
                found_pads.add(f"{label}{pad}")
                pad_end = _block_end(block, index)
                for pad_line in block[index:pad_end]:
                    if not pad_line.strip().startswith("usemic "):
                        continue
                    for used_name in re.findall(r'"([^"]+)"', pad_line):
                        if used_name in source_names:
                            used_sources.add(used_name)
                        elif used_name.endswith("R") and used_name[:-1] in source_names:
                            used_sources.add(used_name[:-1])

        requested_labels: set[str] = set()
        if require_used_explicit_pads:
            requested_labels.update(require_used_explicit_pads)
            collect_used_mics(0, len(block), require_used_explicit_pads, "")
        if require_used_explicit_xpad_pads:
            spans = _xpad_spans(block)
            for xpad, pads in require_used_explicit_xpad_pads.items():
                if xpad not in spans:
                    raise ValueError(f"used-mic validation references absent xpad: {xpad}")
                label = f"xpad {xpad}:"
                requested_labels.update(f"{label}{pad}" for pad in pads)
                collect_used_mics(*spans[xpad], pads, label)
        missing_pads = sorted(requested_labels - found_pads)
        if missing_pads:
            raise ValueError(f"aliased pads have no source pad block: {missing_pads}")
        missing_used = sorted(used_sources - set(overrides))
        if missing_used:
            raise ValueError(f"used micmap entries require explicit map or null: {missing_used}")

    rewritten = list(block)
    micmap_starts = [index for index, line in enumerate(rewritten) if line.strip() == "micmap {"]
    for start in micmap_starts:
        end = _block_end(rewritten, start)
        depth = 0
        for index in range(start, end):
            stripped = rewritten[index].strip()
            if stripped.endswith("{"):
                depth += 1
                continue
            if stripped == "}":
                depth -= 1
                continue
            newline = "\r\n" if rewritten[index].endswith("\r\n") else "\n"
            if depth == 1 and stripped.startswith("nrmaster "):
                rewritten[index] = f"nrmaster {base_mic_count}{newline}"
                continue
            match = _MIC_ENTRY_RE.match(stripped)
            if depth == 1 and match:
                source_name = match.group(2)
                source_index = int(stripped.rsplit(" ", 1)[1])
                if source_name in resolved:
                    # An explicit map/null always wins. preserve_disabled only
                    # protects source mics that the recipe did not review.
                    target_index = resolved[source_name]
                elif preserve_disabled and source_index < 0:
                    target_index = -1
                else:
                    target_index = entries.get(source_name, -1) if exact_match else -1
                rewritten[index] = f"{match.group(1)}{target_index}{newline}"
    unknown = sorted(set(resolved) - source_names)
    if unknown:
        raise ValueError(f"micmap overrides do not exist in source block: {unknown}")
    return rewritten


def _clone_block(source: Path, source_instbox: int, target_instbox: int,
                 aliases: dict[str, list[Any]], base_mastermics: list[str], base_mic_count: int,
                 micmap_overrides: dict[str, Any], micmap_exact_match: bool,
                 micmap_require_explicit: bool,
                 micmap_require_used_explicit: bool,
                 micmap_preserve_disabled: bool,
                 pad_overrides: dict[str, dict[str, Any]],
                 source_xpad: int | None = None,
                 aliases_by_xpad: dict[int, dict[str, list[Any]]] | None = None,
                 stack_routes: list[dict[str, Any]] | None = None) -> list[str]:
    lines, _ = _preset_lines(source)
    spans = _instrument_spans(lines)
    if source_instbox not in spans:
        raise ValueError(f"instbox {source_instbox} not found in {source}")
    start, end = spans[source_instbox]
    block = list(lines[start:end])
    newline = "\r\n" if block[0].endswith("\r\n") else "\n"
    if source_xpad is not None and aliases_by_xpad is not None:
        raise ValueError("source_xpad and xpad_aliases are mutually exclusive")
    if source_xpad is not None:
        xpads = _xpad_spans(block)
        if source_xpad not in xpads:
            raise ValueError(f"xpad {source_xpad} not found in source instbox {source_instbox}")
        xpad_start, xpad_end = xpads[source_xpad]
        selected = list(block[xpad_start:xpad_end])
        # A complete retained stack keeps its original xpad identifiers, but
        # one extracted xpad becomes a standalone instrument and must start at
        # zero or SD3 crashes while parsing it.
        selected[0] = re.sub(r"^xpad\s+\d+", "xpad 0", selected[0])
        block = [f"instbox {target_instbox} {{{newline}", *selected, f"}}{newline}"]
    else:
        block[0] = f"instbox {target_instbox} {{{newline}"
    required_xpad_pads: dict[int, set[str]] | None = None
    if micmap_require_used_explicit and stack_routes:
        required_xpad_pads = {}
        for route in stack_routes:
            required_xpad_pads.setdefault(int(route["target_xpad"]), set()).add(str(route["target_pad"]))
    elif micmap_require_used_explicit and aliases_by_xpad is not None:
        required_xpad_pads = {
            number: set(xpad_aliases)
            for number, xpad_aliases in aliases_by_xpad.items()
        }
    block = _rewrite_all_named_blocks(block, "mastermics", base_mastermics)
    block = _rewrite_micmaps(
        block,
        base_mastermics,
        base_mic_count,
        micmap_overrides,
        micmap_exact_match,
        micmap_require_explicit,
        set(aliases) if micmap_require_used_explicit and aliases_by_xpad is None else None,
        required_xpad_pads,
        micmap_preserve_disabled,
    )
    block = _rewrite_pad_overrides(block, pad_overrides)
    block = _rewrite_stack_routes(block, stack_routes or [])
    if aliases_by_xpad is not None:
        return _rewrite_xpad_aliases(block, aliases_by_xpad)
    return _rewrite_aliases(block, aliases, drop_unspecified=True, add_missing=source_xpad is not None)


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
    micmap_start, micmap_end = _named_block(base_block, "micmap")
    base_mic_count_line = next(
        (line.strip() for line in base_block[micmap_start:micmap_end] if line.strip().startswith("nrmaster ")),
        None,
    )
    if base_mic_count_line is None:
        raise ValueError("base preset micmap has no nrmaster count")
    base_mic_count = int(base_mic_count_line.split()[1])

    replacements: list[tuple[int, int, list[str]]] = []
    base_aliases = {int(number): aliases for number, aliases in recipe.get("base_aliases", {}).items()}
    base_pad_overrides = {
        int(number): overrides for number, overrides in recipe.get("base_pad_overrides", {}).items()
    }
    for number in sorted(set(base_aliases) | set(base_pad_overrides)):
        if number not in spans:
            raise ValueError(f"base instbox {number} does not exist")
        start, end = spans[number]
        replacement = list(lines[start:end])
        if number in base_aliases:
            replacement = _rewrite_aliases(replacement, base_aliases[number], drop_unspecified=False)
        if number in base_pad_overrides:
            replacement = _rewrite_pad_overrides(replacement, base_pad_overrides[number])
        replacements.append((start, end, replacement))
    for start, end, replacement in sorted(replacements, reverse=True):
        lines[start:end] = replacement

    lines = _apply_mixer_overrides(lines, recipe.get("mixer_overrides", {}))
    mixer_source_hashes = _apply_mixer_effect_imports(
        lines,
        recipe.get("mixer_effect_imports", []),
        preset_library,
    )

    clone_specs = list(recipe.get("clones", []))
    target_instboxes = [int(clone["target_instbox"]) for clone in clone_specs]
    duplicate_targets = sorted({number for number in target_instboxes if target_instboxes.count(number) > 1})
    if duplicate_targets:
        raise ValueError(f"duplicate clone target instbox values: {duplicate_targets}")
    colliding_targets = sorted(set(target_instboxes) & set(spans))
    if colliding_targets:
        raise ValueError(f"clone target instbox values collide with the base preset: {colliding_targets}")

    clones: list[str] = []
    source_hashes: dict[str, str] = dict(mixer_source_hashes)
    # Recipe order is editorial. SD3 requires appended instboxes to be
    # serialized in ascending numeric order; 30,42,31,43 crashes its loader.
    for clone in sorted(clone_specs, key=lambda item: int(item["target_instbox"])):
        source_name = str(clone["source"])
        source = base if source_name == "@base" else preset_library / source_name
        if not source.is_file():
            raise FileNotFoundError(f"required source preset is missing: {source}")
        actual_source = sha256_hex(source.read_bytes())
        expected_source = str(clone["source_sha256"]).lower()
        if actual_source != expected_source:
            raise ValueError(f"source SHA256 mismatch for {source}: expected {expected_source}, got {actual_source}")
        source_hashes[source_name] = actual_source
        clones.extend(_clone_block(
            source,
            int(clone["source_instbox"]),
            int(clone["target_instbox"]),
            clone.get("aliases", {}),
            base_mastermics,
            base_mic_count,
            clone.get("micmap_overrides", {}),
            bool(clone.get("micmap_exact_match", True)),
            bool(clone.get("micmap_require_explicit", False)),
            bool(clone.get("micmap_require_used_explicit", False)),
            bool(clone.get("micmap_preserve_disabled", False)),
            clone.get("pad_overrides", {}),
            int(clone["source_xpad"]) if "source_xpad" in clone else None,
            {
                int(number): aliases
                for number, aliases in clone.get("xpad_aliases", {}).items()
            } if "xpad_aliases" in clone else None,
            list(clone.get("stack_routes", [])),
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
    try:
        validated_mappings = _validate_expected_mappings(
            inventory,
            recipe.get("expected_mappings", {}),
        )
        validated_stack_mappings = _validate_expected_stack_mappings(
            inventory,
            recipe.get("expected_stack_mappings", {}),
        )
        validated_mixer_routes = _validate_mixer_routes(output)
    except ValueError:
        output.unlink(missing_ok=True)
        raise
    return {
        "output": str(output),
        "sha256": inventory["sha256"],
        "size_bytes": output.stat().st_size,
        "instrument_count": inventory["instrument_count"],
        "base_sha256": actual_base,
        "source_sha256": source_hashes,
        "validated_unique_notes": sorted(expected_notes),
        "validated_mappings": validated_mappings,
        "validated_stack_mappings": validated_stack_mappings,
        "validated_mixer_routes": validated_mixer_routes,
    }


def _sd3_note_name(note: int) -> str:
    """Return the octave convention displayed by Superior Drummer 3.

    SD3 labels MIDI note 60 as C3, one octave below the common scientific
    convention used by many generic MIDI utilities (C4).  Reports dedicated
    to SD3 must follow the UI so an operator never inspects the wrong key.
    """
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{names[note % 12]}{note // 12 - 2}"


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
    trigger_by_logical: dict[str, tuple[int, ...]] = {}
    for mapping in note_map.get("mappings", []):
        if isinstance(mapping, dict) and isinstance(mapping.get("logical_target"), str):
            routes_by_logical.setdefault(mapping["logical_target"], []).append(str(mapping.get("id", "")))
            if isinstance(mapping.get("note"), int):
                layers = mapping.get("layers", [])
                if isinstance(layers, list) and all(isinstance(note, int) for note in layers):
                    trigger_by_logical.setdefault(mapping["logical_target"], (mapping["note"], *layers))
    lines = [
        "# Greg Hybrid r15 — SD3 MegaKit",
        "",
        f"- Preset: `{preset_path.name}`",
        f"- Preset SHA-256: `{inventory['sha256']}`",
        f"- Instruments SD3: **{inventory['instrument_count']}**",
        "Convention de nommage SD3: MIDI 0 = C-2 (MIDI 60 = C3).",
        "",
        "Une ligne `variation partagée` ne duplique aucun WAV : elle réutilise exactement la note et le son indiqués par `shared_with`.",
        "",
        "| Son logique | Déclenchement SD3 live | Source SD3 réelle | Layers de capture | RR | Kits / palettes | Statut |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for articulation in plan.get("articulations", []):
        if not isinstance(articulation, dict):
            continue
        logical = str(articulation["logical"])
        note = int(articulation["note"])
        trigger = trigger_by_logical.get(logical, (note,))
        trigger_text = " + ".join(f"{value} ({_sd3_note_name(value)})" for value in trigger)
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
            f"| `{logical}` | {trigger_text} | {actual} | {layers} | {rr} | {usage_text} | {status} |"
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
        lines.append(f"| `{articulation['logical']}` | {note} ({_sd3_note_name(note)}) | {actual} | {articulation['status']} |")
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
