"""Versioned, offline latency-run reports and deterministic statistics."""
from __future__ import annotations

import json
from math import sqrt
from pathlib import Path
from typing import Any


LATENCY_RUN_SCHEMA_VERSION = 1
LATENCY_RUN_KIND = "latency-run"
MILESTONES = (
    "t0_wire", "t1_wire", "t1_ready", "t2", "t3_enqueue", "t3_wire",
    "t4_ready", "t5", "t6",
)
METRICS = {
    "input_transport_us": ("t0_wire", "t1_ready"),
    "core_us": ("t1_ready", "t2"),
    "queue_driver_us": ("t2", "t3_wire"),
    "output_transport_us": ("t3_wire", "t4_ready"),
    "renderer_us": ("t4_ready", "t5"),
    "midi_to_captured_audio_us": ("t0_wire", "t6"),
}


def prepared_run(
    run_id: str,
    source: str,
    renderer: str,
    note: int,
    count: int,
    interval_ms: int,
    wiring: str,
    profile: str | None = None,
    sample_rate: int | None = None,
    buffer_frames: int | None = None,
) -> dict[str, Any]:
    """Create a declaration-only run. It intentionally does not touch hardware."""
    if not run_id or not source or not renderer or not wiring:
        raise ValueError("run_id, source, renderer, and wiring are required")
    if not _is_int(note) or not _is_int(count) or not _is_int(interval_ms) or not 0 <= note <= 127 or count <= 0 or interval_ms <= 0:
        raise ValueError("note must be 0..127; count and interval_ms must be positive")
    environment: dict[str, Any] = {}
    if profile:
        environment["profile"] = profile
    if sample_rate is not None:
        if not _is_int(sample_rate) or sample_rate < 8000:
            raise ValueError("sample_rate must be at least 8000")
        environment["sample_rate"] = sample_rate
    if buffer_frames is not None:
        if not _is_int(buffer_frames) or buffer_frames <= 0:
            raise ValueError("buffer_frames must be positive")
        environment["buffer_frames"] = buffer_frames
    return {
        "schema_version": LATENCY_RUN_SCHEMA_VERSION,
        "kind": LATENCY_RUN_KIND,
        "run_id": run_id,
        "status": "prepared",
        "stimulus": {"note": note, "count": count, "interval_ms": interval_ms},
        "path": {"source": source, "renderer": renderer},
        "wiring": wiring,
        "environment": environment,
        "observations": [],
    }


def validate_latency_run(document: object) -> dict[str, Any]:
    """Validate semantic invariants without reading ports, audio devices, or clocks."""
    if not isinstance(document, dict):
        raise ValueError("latency run must be an object")
    required = {"schema_version", "kind", "run_id", "status", "stimulus", "path", "wiring", "environment", "observations"}
    if set(document) != required:
        raise ValueError("latency run has missing or unknown fields")
    if document["schema_version"] != LATENCY_RUN_SCHEMA_VERSION or document["kind"] != LATENCY_RUN_KIND:
        raise ValueError("unsupported latency-run schema version or kind")
    if document["status"] not in ("prepared", "measured"):
        raise ValueError("latency run status must be prepared or measured")
    if not isinstance(document["run_id"], str) or not document["run_id"]:
        raise ValueError("run_id is required")
    stimulus = document["stimulus"]
    if not isinstance(stimulus, dict) or set(stimulus) != {"note", "count", "interval_ms"}:
        raise ValueError("stimulus must declare note, count, and interval_ms")
    if not _is_int(stimulus["note"]) or not 0 <= stimulus["note"] <= 127:
        raise ValueError("stimulus.note must be 0..127")
    if not _is_int(stimulus["count"]) or stimulus["count"] <= 0 or not _is_int(stimulus["interval_ms"]) or stimulus["interval_ms"] <= 0:
        raise ValueError("stimulus.count and stimulus.interval_ms must be positive integers")
    path = document["path"]
    if not isinstance(path, dict) or set(path) != {"source", "renderer"} or not all(isinstance(path[key], str) and path[key] for key in path):
        raise ValueError("path must declare non-empty source and renderer")
    if not isinstance(document["wiring"], str) or not document["wiring"]:
        raise ValueError("wiring is required")
    if not isinstance(document["environment"], dict):
        raise ValueError("environment must be an object")
    observations = document["observations"]
    if not isinstance(observations, list):
        raise ValueError("observations must be an array")
    for observation in observations:
        _validate_observation(observation)
    if document["status"] == "prepared" and observations:
        raise ValueError("prepared run must not contain observations")
    return document


def _validate_observation(observation: object) -> None:
    if not isinstance(observation, dict) or set(observation) != {"sequence", "timestamps_us", "clock_domains"}:
        raise ValueError("each observation must contain sequence, timestamps_us, and clock_domains")
    sequence = observation["sequence"]
    timestamps = observation["timestamps_us"]
    domains = observation["clock_domains"]
    if not _is_int(sequence) or sequence < 0:
        raise ValueError("observation sequence must be a non-negative integer")
    if not isinstance(timestamps, dict) or not timestamps:
        raise ValueError("observation timestamps_us is required")
    if set(timestamps) != set(domains) or not set(timestamps).issubset(MILESTONES):
        raise ValueError("timestamp and clock-domain milestones must match known instants")
    for instant, value in timestamps.items():
        if not _is_int(value) or value < 0 or not isinstance(domains[instant], str) or not domains[instant]:
            raise ValueError("timestamps must be non-negative integer microseconds with non-empty clock domains")


def analyze_latency_run(document: object) -> dict[str, Any]:
    """Summarise only timestamps that share a declared clock domain."""
    run = validate_latency_run(document)
    if run["status"] != "measured":
        raise ValueError("latency analysis requires a measured run")
    values: dict[str, list[int]] = {metric: [] for metric in METRICS}
    incompatible: dict[str, int] = {metric: 0 for metric in METRICS}
    sequences = [item["sequence"] for item in run["observations"]]
    for observation in run["observations"]:
        timestamps = observation["timestamps_us"]
        domains = observation["clock_domains"]
        for metric, (start, end) in METRICS.items():
            if start not in timestamps or end not in timestamps:
                continue
            if domains[start] != domains[end]:
                incompatible[metric] += 1
                continue
            delta = timestamps[end] - timestamps[start]
            if delta < 0:
                raise ValueError(f"{metric} is negative for sequence {observation['sequence']}")
            values[metric].append(delta)
    expected = run["stimulus"]["count"]
    valid_sequences = [sequence for sequence in sequences if 0 <= sequence < expected]
    return {
        "schema_version": 1,
        "kind": "latency-analysis",
        "run_id": run["run_id"],
        "expected_events": expected,
        "observed_events": len(sequences),
        "losses": expected - len(set(valid_sequences)),
        "duplicates": len(sequences) - len(set(sequences)),
        "out_of_range": len(sequences) - len(valid_sequences),
        "out_of_order": sum(current < previous for previous, current in zip(sequences, sequences[1:])),
        "metrics_us": {metric: _summary(samples, incompatible[metric]) for metric, samples in values.items()},
    }


def _summary(samples: list[int], incompatible: int) -> dict[str, int | float | None]:
    if not samples:
        return {"count": 0, "incompatible_clock_pairs": incompatible, "p50": None, "p95": None, "p99": None, "max": None, "stddev": None, "jitter_p99_p50": None}
    ordered = sorted(samples)
    p50 = _percentile(ordered, 50)
    p95 = _percentile(ordered, 95)
    p99 = _percentile(ordered, 99)
    average = sum(ordered) / len(ordered)
    return {"count": len(ordered), "incompatible_clock_pairs": incompatible, "p50": p50, "p95": p95, "p99": p99, "max": ordered[-1], "stddev": round(sqrt(sum((value - average) ** 2 for value in ordered) / len(ordered)), 3), "jitter_p99_p50": p99 - p50}


def _percentile(values: list[int], percentage: int) -> int:
    return values[max(0, (len(values) * percentage + 99) // 100 - 1)]


def _is_int(value: object) -> bool:
    """Match JSON Schema's integer type, which excludes JSON booleans."""
    return isinstance(value, int) and not isinstance(value, bool)


def read_latency_run(path: Path) -> dict[str, Any]:
    return validate_latency_run(json.loads(path.read_text(encoding="utf-8")))


def write_json_new(path: Path, document: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
