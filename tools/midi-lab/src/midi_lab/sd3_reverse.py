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
from typing import Any


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