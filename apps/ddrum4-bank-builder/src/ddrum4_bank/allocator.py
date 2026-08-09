"""Deterministic offline comparison of DDrum4 nested-sound allocations."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AllocationOption:
    """One possible rendering of a logical articulation into a sound slot."""
    identifier: str
    logical_id: str
    sound_id: str
    quality: int
    priority: int
    sample_slots: int
    layers: int
    estimated_blocks: int
    source_take_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.identifier or not self.logical_id or not self.sound_id or not self.source_take_ids:
            raise ValueError("option identifiers, sound_id, and source_take_ids are required")
        for label, value, lower in (("quality", self.quality, 0), ("priority", self.priority, 0), ("sample_slots", self.sample_slots, 1), ("layers", self.layers, 1), ("estimated_blocks", self.estimated_blocks, 1)):
            if value < lower:
                raise ValueError(f"{label} must be at least {lower}")


@dataclass(frozen=True)
class AllocationResult:
    strategy: str
    selected: tuple[AllocationOption, ...]
    omitted_logical_ids: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def estimated_blocks(self) -> int:
        return sum(option.estimated_blocks for option in self.selected)


def compare_allocations(options: tuple[AllocationOption, ...], memory_blocks: int) -> tuple[AllocationResult, AllocationResult]:
    """Compare quality-first and compact-first choices under known hard limits.

    Estimated blocks are planning data only. A real encoded count must replace
    them before a bank can be declared to fit a physical DDrum4.
    """
    if memory_blocks < 1:
        raise ValueError("memory_blocks must be positive")
    logical_ids = tuple(dict.fromkeys(option.logical_id for option in options))
    return (
        _allocate("quality-first", options, logical_ids, memory_blocks, key=lambda option: (-option.quality, -option.priority, option.estimated_blocks, option.identifier)),
        _allocate("compact-first", options, logical_ids, memory_blocks, key=lambda option: (option.estimated_blocks, -option.quality, -option.priority, option.identifier)),
    )


def _allocate(strategy: str, options: tuple[AllocationOption, ...], logical_ids: tuple[str, ...], memory_blocks: int, key: object) -> AllocationResult:
    selected: list[AllocationOption] = []
    sound_slots: dict[str, int] = {}
    sound_layers: dict[str, int] = {}
    used = 0
    omitted: list[str] = []
    warnings: list[str] = []
    for logical_id in sorted(logical_ids, key=lambda item: (-max(option.priority for option in options if option.logical_id == item), item)):
        alternatives = sorted((option for option in options if option.logical_id == logical_id), key=key)  # type: ignore[arg-type]
        chosen = next((option for option in alternatives if used + option.estimated_blocks <= memory_blocks and sound_slots.get(option.sound_id, 0) + option.sample_slots <= 10 and sound_layers.get(option.sound_id, 0) + option.layers <= 10), None)
        if chosen is None:
            omitted.append(logical_id)
            warnings.append(f"{logical_id}: omitted; no option fits the estimated memory or DDrum4 ten-slot/ten-layer limits")
            continue
        selected.append(chosen)
        used += chosen.estimated_blocks
        sound_slots[chosen.sound_id] = sound_slots.get(chosen.sound_id, 0) + chosen.sample_slots
        sound_layers[chosen.sound_id] = sound_layers.get(chosen.sound_id, 0) + chosen.layers
        best_quality = max(option.quality for option in alternatives)
        if chosen.quality < best_quality:
            warnings.append(f"{logical_id}: selected reduced quality {chosen.quality}/{best_quality} for {strategy}")
    return AllocationResult(strategy, tuple(selected), tuple(omitted), tuple(warnings))
