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


@dataclass(frozen=True)
class StateChangeResult:
    """Offline trace of one logical control travelling from PC/controller to DDrum4."""

    source: str
    message: Mapping[str, Any]
    state: Mapping[str, Any]
    steps: tuple[TraceStep, ...]

    def to_document(self) -> dict[str, Any]:
        return {
            "kind": "drum-chain-state-change-simulation/v1",
            "hardware_io": "disabled",
            "source": self.source,
            "message": dict(self.message),
            "state": dict(self.state),
            "trace": [step.to_document() for step in self.steps],
        }

    def render_text(self) -> str:
        lines = [
            f"{self.source} logical control: " + " ".join(f"{key}={value}" for key, value in self.message.items()),
            "state: " + ", ".join(f"{name}={value}" for name, value in self.state.items()),
            "",
        ]
        lines.extend(f"{index}. {step.stage}: {step.detail}" for index, step in enumerate(self.steps, start=1))
        lines.append("\nSimulation only: no MIDI, SysEx, or hardware module was opened.")
        return "\n".join(lines)


@dataclass(frozen=True)
class DiagnosticCase:
    """One deterministic offline path checked against the declared rig."""

    identifier: str
    passed: bool
    detail: str

    def to_document(self) -> dict[str, Any]:
        return {"id": self.identifier, "status": "passed" if self.passed else "failed", "detail": self.detail}


@dataclass(frozen=True)
class DiagnosticReport:
    """Coverage report for a no-pad, no-port project verification run."""

    project: str
    cases: tuple[DiagnosticCase, ...]

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)

    @property
    def passed_count(self) -> int:
        return sum(case.passed for case in self.cases)

    def to_document(self) -> dict[str, Any]:
        return {
            "kind": "drum-chain-offline-diagnostic/v1",
            "hardware_io": "disabled",
            "project": self.project,
            "status": "passed" if self.passed else "failed",
            "summary": {"passed": self.passed_count, "total": len(self.cases)},
            "cases": [case.to_document() for case in self.cases],
        }

    def render_text(self) -> str:
        lines = [f"Offline diagnostic: {self.project}",
                 f"{self.passed_count}/{len(self.cases)} paths passed", ""]
        lines.extend(f"{'PASS' if case.passed else 'FAIL'} {case.identifier} - {case.detail}" for case in self.cases)
        lines.append("\nOffline only: no MIDI port, Arduino, DDrum4, VST, or audio device was opened.")
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
        ddrum_channel = self.project.ddrum4_output_channel
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

    def simulate_logical_control(
        self, source: str, channel: int, message_type: str, data1: int, value: int = 0,
    ) -> StateChangeResult:
        """Apply and trace a CH14/15 Scene or VP command without opening MIDI.

        The same logical command is what the PC converter and an external
        controller put on the future Master Merger.  A DDrum4 reconciliation
        action is rendered only when it is declared in the project, and SysEx
        payloads are displayed as captured data rather than synthesised.
        """
        if source not in {"pc", "external", "simulator"}:
            raise SimulationError("logical-control source must be pc, external, or simulator")
        if type(channel) is not int or not 1 <= channel <= 16:
            raise SimulationError("logical-control channel must be in 1..16")
        if message_type not in {"program_change", "cc"}:
            raise SimulationError("logical-control type must be program_change or cc")
        if type(data1) is not int or not 0 <= data1 <= 127 or type(value) is not int or not 0 <= value <= 127:
            raise SimulationError("logical-control data must be MIDI bytes")
        target: str | None = None
        for name, control in self.project.logical_control_protocol.items():
            if channel not in control["channels"] or control["type"] != message_type:
                continue
            if message_type == "program_change" or control.get("cc") == data1:
                target = name
                break
        if target is None:
            raise SimulationError("message is not a declared logical Scene/VP control")
        message = {"type": message_type, "channel": channel, "data1": data1, "value": value}
        if target == "scene":
            if data1 >= len(self.project.scenes):
                raise SimulationError(f"scene Program Change {data1} is not declared")
            self._state["scene"] = self.project.scenes[data1]
        else:
            self._state[target] = value
        actions = self.project.ddrum_state_actions.get(self._state["scene"], ())
        steps: list[TraceStep] = [
            TraceStep("logical control", f"{source} emits a declared {target} command", message),
            TraceStep("Arduino state", "updates Scene/VP idempotently", dict(self._state)),
        ]
        bus = self.project.control_bus
        if bus is None:
            steps.append(TraceStep("control bus", "no PC → Arduino control endpoint is declared; state remains local/offline"))
        elif bus["status"] == "user-confirmed" and self.project.deployment == "live":
            steps.append(TraceStep("control bus", "would send the logical command to the declared Master Merger input", {
                "endpoint": bus["endpoint"], "channel": bus["channel"], "status": bus["status"],
            }))
        else:
            steps.append(TraceStep("control bus", "declared for simulation/planning only; no hardware output is permitted", {
                "endpoint": bus["endpoint"], "channel": bus["channel"], "status": bus["status"],
            }))
        matching_actions = [action for action in actions
                            if all(self._state.get(name) == expected for name, expected in action.when.items())]
        for action in matching_actions:
            if action.action_type == "program_change":
                native = {"type": "program_change", "channel": action.channel, "program": action.program,
                          "status": action.status}
            else:
                native = {"type": "sysex", "data": list(action.data), "status": action.status}
            detail = action.description or "declared DDrum4 state reconciliation"
            steps.append(TraceStep("Arduino DDrum4 state", detail, native))
        if not matching_actions:
            steps.append(TraceStep("Arduino DDrum4 state", "no native action declared for this scene"))
        steps.append(TraceStep("PC state echo", "the returned logical control is idempotent", dict(self._state)))
        return StateChangeResult(source, message, dict(self._state), tuple(steps))

    def simulate_native_control(self, name: str) -> StateChangeResult:
        """Trace one exact native DDrum4 control observation into logical state.

        Native controls are observations only: the method intentionally never
        creates a return Program Change or SysEx message.  That makes a manual
        DDrum4 panel change safe to test without modelling a feedback loop.
        """
        native = self.project.native_control_map.get(name)
        if not isinstance(native, Mapping):
            raise SimulationError(f"unknown native control {name!r}")
        target = native["decode_to"]
        value = native["value"]
        if target == "scene":
            if value >= len(self.project.scenes):
                raise SimulationError(f"native control {name!r} selects undeclared scene {value}")
            self._state["scene"] = self.project.scenes[value]
        else:
            self._state[target] = value
        address_key = {"program_change": "program", "cc": "cc", "note": "note"}[native["type"]]
        message = {"type": native["type"], "channel": native["channel"],
                   "data1": native[address_key], "value": value}
        steps = (
            TraceStep("native DDrum4 control", f"{name} exactly matches the declared address", message),
            TraceStep("Arduino state", "updates Scene/VP without re-emitting the observed native control", dict(self._state)),
            TraceStep("PC state echo", "the returned state is idempotent", dict(self._state)),
        )
        return StateChangeResult("ddrum4", message, dict(self._state), steps)

    def run_offline_diagnostic(self) -> DiagnosticReport:
        """Exercise every declared playable input and state address offline.

        State coverage is intentionally finite: defaults, every scene, every
        conditional route/action predicate combination and each native-control
        value.  It catches broken mappings without inventing the unbounded
        Cartesian product of arbitrary MIDI VP values.
        """
        cases: list[DiagnosticCase] = []
        for decoder_index, decoder in enumerate(self.project.source_decoders, start=1):
            if decoder.message_type not in {"note", "note_range"}:
                cases.append(DiagnosticCase(
                    f"decoder.{decoder_index:03d}.{decoder.source}.{decoder.message_type}", False,
                    f"offline diagnostic does not yet exercise declared {decoder.message_type} decoder; no false PASS is emitted",
                ))
        for scene, values in self._diagnostic_state_vectors():
            for decoder in self.project.source_decoders:
                if decoder.message_type not in {"note", "note_range"}:
                    continue
                notes = (decoder.match["note"],) if decoder.message_type == "note" else range(
                    decoder.match["note_range"][0], decoder.match["note_range"][1] + 1)
                for note in notes:
                    identifier = self._diagnostic_id("pad", decoder.source, note, scene, values)
                    candidate = RigSimulator(self.project)
                    try:
                        candidate.set_state(scene=scene, values=values)
                        result = candidate.simulate_pad(decoder.source, note)
                        cases.append(DiagnosticCase(identifier, True,
                            f"{result.physical} -> {result.logical_target}; DDrum4/SD3/DrumGizmo declared"))
                    except SimulationError as error:
                        cases.append(DiagnosticCase(identifier, False, str(error)))
        for index, scene in enumerate(self.project.scenes):
            candidate = RigSimulator(self.project)
            identifier = f"logical.scene.pc{index:03d}"
            try:
                candidate.simulate_logical_control("simulator", 15, "program_change", index)
                cases.append(DiagnosticCase(identifier, True, f"selects scene {scene}"))
            except SimulationError as error:
                cases.append(DiagnosticCase(identifier, False, str(error)))
        for variable, values in self._diagnostic_variable_values().items():
            control = self.project.logical_control_protocol[variable]
            for value in sorted(values):
                candidate = RigSimulator(self.project)
                identifier = f"logical.{variable}.cc{control['cc']:03d}.v{value:03d}"
                try:
                    candidate.simulate_logical_control("simulator", 15, "cc", control["cc"], value)
                    cases.append(DiagnosticCase(identifier, True, f"sets {variable}={value}"))
                except SimulationError as error:
                    cases.append(DiagnosticCase(identifier, False, str(error)))
        for name in sorted(self.project.native_control_map):
            candidate = RigSimulator(self.project)
            try:
                result = candidate.simulate_native_control(name)
                cases.append(DiagnosticCase(f"native.{name}", True,
                    "updates " + ", ".join(f"{key}={value}" for key, value in result.state.items())))
            except SimulationError as error:
                cases.append(DiagnosticCase(f"native.{name}", False, str(error)))
        return DiagnosticReport(self.project.project, tuple(cases))

    def _diagnostic_variable_values(self) -> dict[str, set[int]]:
        values = {name: {self.project.defaults[name]} for name in self.project.variables}
        for scene in self.project.scenes:
            for route in self.project.logical_routes[scene].values():
                for variant in logical_route_variants(route):
                    for name, value in variant.predicates.items():
                        values[name].add(value)
            for action in self.project.ddrum_state_actions.get(scene, ()):
                for name, value in action.when.items():
                    values[name].add(value)
        for native in self.project.native_control_map.values():
            if native["decode_to"] in values:
                values[native["decode_to"]].add(native["value"])
        return values

    def _diagnostic_state_vectors(self) -> tuple[tuple[str, dict[str, int]], ...]:
        vectors: set[tuple[str, tuple[tuple[str, int], ...]]] = set()
        defaults = {name: self.project.defaults[name] for name in self.project.variables}
        for scene in self.project.scenes:
            vectors.add((scene, tuple(sorted(defaults.items()))))
            for route in self.project.logical_routes[scene].values():
                for variant in logical_route_variants(route):
                    values = {**defaults, **variant.predicates}
                    vectors.add((scene, tuple(sorted(values.items()))))
            for action in self.project.ddrum_state_actions.get(scene, ()):
                values = {**defaults, **action.when}
                vectors.add((scene, tuple(sorted(values.items()))))
        return tuple((scene, dict(values)) for scene, values in sorted(vectors))

    @staticmethod
    def _diagnostic_id(kind: str, source: str, note: int, scene: str, values: Mapping[str, int]) -> str:
        suffix = ".".join(f"{name}{value}" for name, value in sorted(values.items()))
        return f"{kind}.{source}.n{note:03d}.{scene}.{suffix or 'default'}"

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
