"""Port matching that refuses ambiguous hardware choices."""
from __future__ import annotations


def resolve_unique_port(names: list[str], query: str) -> str:
    normalized = query.casefold().strip()
    if not normalized:
        raise ValueError("port query must not be empty")
    exact = [name for name in names if name.casefold() == normalized]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValueError(f"multiple exact MIDI ports match {query!r}: {exact}")
    matches = [name for name in names if normalized in name.casefold()]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one MIDI port containing {query!r}, found {matches}")
    return matches[0]
