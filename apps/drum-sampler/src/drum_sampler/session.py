"""Deterministic capture-grid planning, independent from audio hardware."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class CaptureRequest:
    instrument: str
    articulation: str
    note: int
    velocities: tuple[int, ...]
    repetitions: int
    channel: int = 10
    controllers: tuple[tuple[int, int], ...] = ()

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
        if any(not 0 <= control <= 127 or not 0 <= value <= 127 for control, value in self.controllers):
            raise ValueError("controller numbers and values must be in 0..127")
        if len({control for control, _ in self.controllers}) != len(self.controllers):
            raise ValueError("a capture request cannot set one controller more than once")


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

    def to_document(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "capture-session",
            "midi_output": self.midi_output,
            "audio_input": self.audio_input,
            "channels": list(self.channels),
            "sample_rate": self.sample_rate,
            "preroll_ms": self.preroll_ms,
            "gate_ms": self.gate_ms,
            "tail_ms": self.tail_ms,
            "cooldown_ms": self.cooldown_ms,
            "requests": [{
                "instrument": request.instrument,
                "articulation": request.articulation,
                "note": request.note,
                "channel": request.channel,
                "controllers": [list(pair) for pair in request.controllers],
                "velocities": list(request.velocities),
                "repetitions": request.repetitions,
            } for request in self.requests],
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> "CaptureSessionPlan":
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("schema_version") != 1 or document.get("kind") != "capture-session":
            raise ValueError("unsupported capture-session document")
        requests = document.get("requests")
        channels = document.get("channels")
        if not isinstance(requests, list) or not isinstance(channels, list):
            raise ValueError("capture-session requests and channels must be lists")
        try:
            parsed_requests = tuple(CaptureRequest(
                instrument=item["instrument"], articulation=item["articulation"], note=item["note"],
                channel=item.get("channel", 10), velocities=tuple(item["velocities"]), repetitions=item["repetitions"],
                controllers=tuple(tuple(pair) for pair in item.get("controllers", [])),
            ) for item in requests)
            return cls(
                midi_output=document["midi_output"], audio_input=document["audio_input"],
                channels=tuple(channels), requests=parsed_requests,
                sample_rate=document.get("sample_rate", 44100), preroll_ms=document.get("preroll_ms", 100),
                gate_ms=document.get("gate_ms", 100), tail_ms=document.get("tail_ms", 5000), cooldown_ms=document.get("cooldown_ms", 300),
            )
        except (KeyError, TypeError) as error:
            raise ValueError("invalid capture-session document") from error

    def incomplete_takes(self, raw_directory: Path) -> tuple[PlannedTake, ...]:
        return tuple(take for take in self.takes() if not (raw_directory / take.raw_filename()).is_file())
