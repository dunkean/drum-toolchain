"""Deterministic capture-grid planning, independent from audio hardware."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CaptureRequest:
    instrument: str
    articulation: str
    note: int
    velocities: tuple[int, ...]
    repetitions: int
    channel: int = 10

    def __post_init__(self) -> None:
        if not self.instrument or not self.articulation:
            raise ValueError("instrument and articulation are required")
        if not 0 <= self.note <= 127 or not 1 <= self.channel <= 16:
            raise ValueError("note must be 0..127 and channel must be 1..16")
        if not self.velocities or any(not 1 <= value <= 127 for value in self.velocities):
            raise ValueError("velocities must contain MIDI values in 1..127")
        if tuple(sorted(set(self.velocities))) != self.velocities:
            raise ValueError("velocities must be unique and ascending")
        if self.repetitions < 1:
            raise ValueError("repetitions must be positive")


@dataclass(frozen=True)
class PlannedTake:
    request: CaptureRequest
    velocity: int
    repetition: int

    def raw_filename(self) -> str:
        return f"{self.request.instrument}__{self.request.articulation}__v{self.velocity:03d}__rr{self.repetition:02d}_raw.wav"


@dataclass(frozen=True)
class CaptureSessionPlan:
    midi_output: str
    audio_input: str
    channels: tuple[str, ...]
    requests: tuple[CaptureRequest, ...]
    sample_rate: int = 44100
    preroll_ms: int = 100
    gate_ms: int = 100
    tail_ms: int = 5000
    cooldown_ms: int = 300

    def __post_init__(self) -> None:
        if not self.midi_output or not self.audio_input:
            raise ValueError("MIDI output and audio input are required")
        if not self.channels or len(set(self.channels)) != len(self.channels):
            raise ValueError("capture channels must be a unique non-empty list")
        if self.sample_rate < 8000:
            raise ValueError("sample_rate is implausibly low")
        for name, value in (("preroll_ms", self.preroll_ms), ("gate_ms", self.gate_ms), ("tail_ms", self.tail_ms), ("cooldown_ms", self.cooldown_ms)):
            if value < 0:
                raise ValueError(f"{name} must not be negative")

    def takes(self) -> tuple[PlannedTake, ...]:
        planned: list[PlannedTake] = []
        for request in self.requests:
            for velocity in request.velocities:
                for repetition in range(1, request.repetitions + 1):
                    planned.append(PlannedTake(request, velocity, repetition))
        return tuple(planned)

    def incomplete_takes(self, raw_directory: Path) -> tuple[PlannedTake, ...]:
        return tuple(take for take in self.takes() if not (raw_directory / take.raw_filename()).is_file())
