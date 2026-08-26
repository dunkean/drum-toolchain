"""Offline trace simulator for a ``rig-project/v1`` drum chain.

The simulator deliberately models routing and declared renderer destinations,
not audio or MIDI transport.  It never opens a MIDI port, loads a VST, or
contacts a hardware module.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from drum_domain.rig_project import RigProject, logical_route_variants, load_rig_project


class SimulationError(ValueError):
    """A requested virtual event cannot be resolved by the rig project."""


@dataclass(frozen=True)
class TraceStep:
    """One named stage in a deterministic, inspectable signal path."""

    stage: str
    detail: str
    message: Mapping[str, Any] | None = None

    def to_document(self) -> dict[str, Any]:
        document: dict[str, Any] = {"stage": self.stage, "detail": self.detail}
        if self.message is not None:
            document["message"] = dict(self.message)
        return document


@dataclass(frozen=True)
class SimulationResult:
    """The logical state and all renderer destinations for one virtual hit."""

    source: str
    raw_note: int
    velocity: int
    physical: str
    logical_target: str
    state: Mapping[str, Any]
    steps: tuple[TraceStep, ...]

    def to_document(self) -> dict[str, Any]:
        return {
            "kind": "drum-chain-simulation/v1",
            "hardware_io": "disabled",
            "source": self.source,
            "raw": {"note": self.raw_note, "velocity": self.velocity},
            "physical": self.physical,
            "logical_target": self.logical_target,
            "state": dict(self.state),
            "trace": [step.to_document() for step in self.steps],
        }

    def render_text(self) -> str:
        lines = [
            f"{self.source} raw note {self.raw_note}, velocity {self.velocity}",
            f"physical: {self.physical}",
            "state: " + ", ".join(f"{name}={value}" for name, value in self.state.items()),
            f"logical sound: {self.logical_target}",
            "",
        ]
        for index, step in enumerate(self.steps, start=1):
            suffix = ""
            if step.message:
                message = step.message
                suffix = " — " + " ".join(f"{name}={value}" for name, value in message.items())
            lines.append(f"{index}. {step.stage}: {step.detail}{suffix}")
        lines.append("\nSimulation only: no MIDI, VST, audio device, or hardware module was opened.")
        return "\n".join(lines)


class RigSimulator:
    """Resolve virtual pad hits through the complete declared renderer chain."""

    def __init__(self, project: RigProject) -> None:
        self.project = project
        self._state: dict[str, Any] = dict(project.defaults)

    @classmethod
    def from_path(cls, path: Path) -> "RigSimulator":
        return cls(load_rig_project(path))

    @property
    def state(self) -> Mapping[str, Any]:
        return dict(self._state)

    def set_state(self, *, scene: str | None = None, values: Mapping[str, int] | None = None) -> None:
        if scene is not None:
            if scene not in self.project.scenes:
                raise SimulationError(f"unknown scene {scene!r}")
            self._state["scene"] = scene
        for name, value in (values or {}).items():
            if name not in self.project.variables:
                raise SimulationError(f"unknown state variable {name!r}")
            if type(value) is not int or not 0 <= value <= 127:
                raise SimulationError(f"state variable {name!r} must be a MIDI value in 0..127")
            self._state[name] = value

    def simulate_pad(self, source: str, note: int, velocity: int = 100) -> SimulationResult:
        """Trace one virtual Note On from a declared source module."""
        if source not in self.project.sources:
            raise SimulationError(f"unknown source module {source!r}")
        if type(note) is not int or not 0 <= note <= 127:
            raise SimulationError("note must be a MIDI value in 0..127")
        if type(velocity) is not int or not 1 <= velocity <= 127:
            raise SimulationError("velocity must be a MIDI value in 1..127")
        decoder = self._note_decoder(source, note)
        if decoder is None:
            raise SimulationError(f"{source} note {note} has no declared physical-pad decoder")
        physical = decoder.physical
        logical = self._logical_target(physical)
        source_channel = self.project.sources[source].channel
        steps: list[TraceStep] = [
            TraceStep("raw MIDI", f"{source} emits its unchanged pad event", {
                "type": "note_on", "channel": source_channel, "note": note, "velocity": velocity,
            }),
            TraceStep("source profile", f"{source} note {note} resolves to {physical}"),
            TraceStep("logical state", "Scene and virtual palettes select the logical sound", dict(self._state)),
            TraceStep("logical sound", logical),
        ]
        ddrum = self.project.renderers["ddrum4"][logical]
        ddrum_channel = self.project.sources.get("ddrum4", self.project.sources[source]).channel
        ddrum_message = {"type": "note_on", "channel": ddrum_channel, "note": ddrum["note"], "velocity": velocity}
        steps.extend((
            TraceStep("Arduino DDrum4 renderer", "writes the converted event to DDrum4 MIDI IN", ddrum_message),
            TraceStep("DDrum4 audio", f"Local Off: the returned note renders {logical}"),
            TraceStep("DDrum4 echo guard", "suppresses the expected returned DDrum4 MIDI OUT echo", ddrum_message),
        ))
        sd3 = self.project.renderers["sd3"][logical]
        sd3_message = {"type": "note_on", "channel": sd3.get("channel", 10), "note": sd3["note"], "velocity": velocity}
        steps.extend((
            TraceStep("SD3 renderer", "sends the canonical MegaKit MIDI event", sd3_message),
            TraceStep("SD3 audio", f"MegaKit renders {logical}"),
        ))
        drumgizmo = self.project.renderers["drumgizmo"][logical]
        drumgizmo_message = {
            "type": "note_on", "channel": drumgizmo.get("channel", 10), "note": drumgizmo["note"],
            "velocity": velocity, "instrument": drumgizmo["instrument"], "articulation": drumgizmo["articulation"],
        }
        steps.extend((
            TraceStep("DrumGizmo renderer", "sends the declared note-only kit event", drumgizmo_message),
            TraceStep("DrumGizmo audio", f"Kit renders {drumgizmo['instrument']}/{drumgizmo['articulation']}"),
        ))
        return SimulationResult(source, note, velocity, physical, logical, dict(self._state), tuple(steps))

    def _note_decoder(self, source: str, note: int):
        for decoder in self.project.source_decoders:
            if decoder.source != source:
                continue
            if decoder.message_type == "note" and decoder.match["note"] == note:
                return decoder
            if decoder.message_type == "note_range":
                low, high = decoder.match["note_range"]
                if low <= note <= high:
                    return decoder
        return None

    def _logical_target(self, physical: str) -> str:
        scene = self._state["scene"]
        variants = logical_route_variants(self.project.logical_routes[scene][physical])
        ordered = sorted(variants, key=lambda variant: not variant.predicates)
        for variant in ordered:
            if all(self._state[name] == value for name, value in variant.predicates.items()):
                return variant.logical_target
        raise SimulationError(f"no logical route for {physical!r} in scene {scene!r}")
