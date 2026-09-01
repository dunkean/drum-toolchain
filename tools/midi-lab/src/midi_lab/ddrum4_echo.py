"""Pure analysis for an isolated DDrum4 performance soft-through probe."""
from __future__ import annotations

from collections import Counter
from typing import Mapping, Sequence

REQUIRED_KINDS = frozenset({"note_on", "poly_aftertouch", "zero_velocity_note_on"})


def summarize_echo_probe(samples: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Classify exact or transformed returns without inferring an echo window."""
    if not samples:
        raise ValueError("echo probe needs at least one transmitted sample")
    sent = Counter()
    exact = Counter()
    duplicate_exact = Counter()
    transformed = Counter()
    latencies: list[int] = []
    received_total = 0
    for sample in samples:
        kind = sample.get("kind")
        signature = sample.get("sent")
        received = sample.get("received")
        if not isinstance(kind, str) or not isinstance(signature, Mapping) or not isinstance(received, Sequence):
            raise ValueError("invalid echo probe sample")
        sent[kind] += 1
        exact_events: list[Mapping[str, object]] = []
        transformed_events: list[Mapping[str, object]] = []
        for event in received:
            if not isinstance(event, Mapping):
                raise ValueError("invalid received echo event")
            received_total += 1
            same_address = all(event.get(field) == signature.get(field)
                               for field in ("message_type", "channel", "data1"))
            if not same_address:
                continue
            if event.get("data2") == signature.get("data2"):
                exact_events.append(event)
                latency = event.get("latency_ms")
                if isinstance(latency, int) and not isinstance(latency, bool) and latency >= 0:
                    latencies.append(latency)
            else:
                transformed_events.append(event)
        if exact_events:
            exact[kind] += 1
            duplicate_exact[kind] += len(exact_events) - 1
        if transformed_events:
            transformed[kind] += 1
    exact_total = sum(exact.values())
    duplicate_total = sum(duplicate_exact.values())
    transformed_total = sum(transformed.values())
    if set(sent) != REQUIRED_KINDS or len(set(sent.values())) != 1:
        raise ValueError("echo probe must contain the same non-zero sample count for all three performance message types")
    per_type: dict[str, str] = {}
    for kind in sorted(sent):
        if exact[kind] == sent[kind] and duplicate_exact[kind] == 0 and transformed[kind] == 0:
            per_type[kind] = "complete-exact"
        elif duplicate_exact[kind]:
            per_type[kind] = "duplicate-return-observed"
        elif exact[kind]:
            per_type[kind] = "partial-exact"
        elif transformed[kind]:
            per_type[kind] = "transformed-only"
        else:
            per_type[kind] = "no-return"
    conclusion = (
        "complete-performance-soft-through-observed"
        if all(verdict == "complete-exact" for verdict in per_type.values()) else
        "loop-or-duplicate-return-observed" if duplicate_total else
        "partial-or-type-selective-performance-return-observed" if exact_total else
        "transformed-performance-return-observed" if transformed_total else
        "no-performance-soft-through-observed"
    )
    return {
        "conclusion": conclusion,
        "sent_by_type": dict(sorted(sent.items())),
        "exact_returns_by_type": {kind: exact.get(kind, 0) for kind in sorted(sent)},
        "duplicate_exact_returns_by_type": {kind: duplicate_exact.get(kind, 0) for kind in sorted(sent)},
        "transformed_returns_by_type": {kind: transformed.get(kind, 0) for kind in sorted(sent)},
        "verdict_by_type": per_type,
        "sent_total": sum(sent.values()),
        "received_total": received_total,
        "exact_return_total": exact_total,
        "duplicate_exact_return_total": duplicate_total,
        "transformed_return_total": transformed_total,
        "max_exact_latency_ms": max(latencies) if latencies else None,
    }
