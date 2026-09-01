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
    """The logical state and declared renderer handling for one raw MIDI event."""

    source: str
    raw_note: int
    velocity: int
    physical: str
    logical_target: str
    state: Mapping[str, Any]
    steps: tuple[TraceStep, ...]
    raw_type: str = "note_on"
    # This class only proves a declared route.  It never opens an engine,
    # device, or module, therefore it must never be interpreted as audio
    # verification.
    renders_audio: bool = False

    def to_document(self) -> dict[str, Any]:
        return {
            "kind": "drum-chain-simulation/v1",
            "hardware_io": "disabled",
            "source": self.source,
            "raw": ({"type": "note_on", "note": self.raw_note, "velocity": self.velocity}
                    if self.raw_type == "note_on" else
                    {"type": self.raw_type, "data1": self.raw_note, "value": self.velocity}),
            "physical": self.physical,
            "logical_target": self.logical_target,
            "route_resolved": True,
            "renders_audio": self.renders_audio,
            "state": dict(self.state),
            "trace": [step.to_document() for step in self.steps],
        }

    def render_text(self) -> str:
        lines = [
            (f"{self.source} raw note {self.raw_note}, velocity {self.velocity}"
             if self.raw_type == "note_on" else
             f"{self.source} raw {self.raw_type} {self.raw_note}, value {self.velocity}"),
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
class _ActiveHit:
    """A bounded offline analogue of the firmware/runtime active-hit ledger."""

    physical: str
    logical_target: str
    state: Mapping[str, Any]
    ddrum_message: Mapping[str, Any]
    sd3_message: Mapping[str, Any]
    drumgizmo_message: Mapping[str, Any]


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
        # Same source/raw note replaces its prior entry, matching the bounded
        # live ledgers. This simulator never opens MIDI, so reset/reload is the
        # explicit boundary for an offline performance trace.
        self._active_hits: dict[tuple[str, int], _ActiveHit] = {}

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
        position: int | None = None
        if decoder.message_type == "note_range" and "position" in decoder.emit.get("expressions", ()):
            low, high = decoder.match["note_range"]
            position = ((note - low) * 127) // (high - low)
        ddrum_note = ddrum["note"]
        if position is not None and ddrum.get("position_policy") == "note_range_quantized":
            position_notes = ddrum["position_notes"]
            boundaries = ddrum["position_upper_boundaries"]
            zone = 0
            while zone < len(boundaries) and position > boundaries[zone]:
                zone += 1
            ddrum_note = position_notes[zone]
        ddrum_message = {"type": "note_on", "channel": ddrum_channel, "note": ddrum_note, "velocity": velocity}
        ddrum_detail = (f"; raw position {position}/127 quantized to note {ddrum_note}"
                         if position is not None and ddrum.get("position_policy") == "note_range_quantized" else "")
        steps.extend((
            TraceStep("Arduino DDrum4 renderer", "writes the converted event to DDrum4 MIDI IN" + ddrum_detail, ddrum_message),
            TraceStep("DDrum4 declared target", f"Local Off is declared; DDrum4 would receive {logical} when live"),
            TraceStep("DDrum4 echo guard", "suppresses the expected returned DDrum4 MIDI OUT echo", ddrum_message),
        ))
        sd3 = self.project.renderers["sd3"][logical]
        sd3_message = {"type": "note_on", "channel": sd3.get("channel", 10), "note": sd3["note"], "velocity": velocity}
        if position is not None and sd3.get("position_cc") is not None:
            steps.append(TraceStep(
                "SD3 position renderer",
                f"normalizes the DDrum4 NOTE P offset to CC{sd3['position_cc']} before the hit",
                {"type": "control_change", "channel": sd3.get("channel", 10),
                 "cc": sd3["position_cc"], "value": position},
            ))
        for controller, value in sd3.get("controllers", ()):
            steps.append(TraceStep(
                "SD3 fixed controller",
                f"sets CC{controller}={value} immediately before the selected hit",
                {"type": "control_change", "channel": sd3.get("channel", 10), "cc": controller, "value": value},
            ))
        steps.append(TraceStep("SD3 renderer", "sends the canonical MegaKit MIDI event", sd3_message))
        for layer_note in sd3.get("layers", ()):
            steps.append(TraceStep(
                "SD3 layer renderer",
                "adds the calibrated phase-safe layer at the same velocity",
                {"type": "note_on", "channel": sd3.get("channel", 10), "note": layer_note, "velocity": velocity},
            ))
        steps.append(TraceStep("SD3 declared target", f"The selected SD3 kit would receive {logical} when its runtime is live"))
        drumgizmo = self.project.renderers["drumgizmo"][logical]
        drumgizmo_note = drumgizmo["note"]
        drumgizmo_position_detail = ""
        if position is not None and drumgizmo.get("position_policy") == "note_range_quantized":
            position_notes = drumgizmo["position_notes"]
            boundaries = drumgizmo["position_upper_boundaries"]
            zone = 0
            while zone < len(boundaries) and position > boundaries[zone]:
                zone += 1
            drumgizmo_note = position_notes[zone]
            drumgizmo_position_detail = f"; raw position {position}/127 quantized to note {drumgizmo_note}"
        elif position is not None:
            drumgizmo_position_detail = "; positional input is intentionally ignored"
        drumgizmo_message = {
            "type": "note_on", "channel": drumgizmo.get("channel", 10), "note": drumgizmo_note,
            "velocity": velocity, "instrument": drumgizmo["instrument"], "articulation": drumgizmo["articulation"],
        }
        steps.extend((
            TraceStep("DrumGizmo renderer", "sends the declared kit event" + drumgizmo_position_detail,
                      drumgizmo_message),
            TraceStep("DrumGizmo declared target", f"The selected kit would receive {drumgizmo['instrument']}/{drumgizmo['articulation']} when live"),
        ))
        self._active_hits[(source, note)] = _ActiveHit(
            physical=physical,
            logical_target=logical,
            state=dict(self._state),
            ddrum_message=dict(ddrum_message),
            sd3_message=dict(sd3_message),
            drumgizmo_message=dict(drumgizmo_message),
        )
        return SimulationResult(source, note, velocity, physical, logical, dict(self._state), tuple(steps))

    def simulate_expression(self, source: str, message_type: str, data1: int, value: int = 64) -> SimulationResult:
        """Inspect a declared expression without inventing renderer support.

        A reviewed ``expression-routing/v1`` route can prove both available
        verticals: openness CC passthrough to SD3 and retained CC4 state that
        selects the next DDrum4 Note-P hit.  The latter never invents audio on
        a bare CC message: it previews the note chosen for the next declared
        bow/edge hit. Other targets remain explicit planned/unsupported steps.
        """
        if source not in self.project.sources:
            raise SimulationError(f"unknown source module {source!r}")
        if message_type not in {"cc", "poly_aftertouch"}:
            raise SimulationError("expression type must be cc or poly_aftertouch")
        if type(data1) is not int or type(value) is not int or not 0 <= data1 <= 127 or not 0 <= value <= 127:
            raise SimulationError("expression data must be MIDI bytes")
        decoder = self._expression_decoder(source, message_type, data1)
        if decoder is None:
            raise SimulationError(f"{source} {message_type} {data1} has no declared physical-pad decoder")
        active_hit: _ActiveHit | None = None
        if message_type == "poly_aftertouch" and decoder.match.get("active_note"):
            # The expression is valid only after an actual simulated Note-On.
            # Do not re-resolve Scene/VP here: pressure follows the renderer
            # destination selected when that preceding hit was played.
            active_hit = self._active_hits.get((source, data1))
            if active_hit is None or active_hit.physical != decoder.physical:
                raise SimulationError(
                    "poly_aftertouch active_note needs a preceding simulated Note-On for the same physical event"
                )
            physical, logical = active_hit.physical, active_hit.logical_target
        else:
            physical = decoder.physical
            logical = self._logical_target(physical)
        source_channel = self.project.sources[source].channel
        raw_type = "control_change" if message_type == "cc" else "poly_aftertouch"
        steps: list[TraceStep] = [
            TraceStep("raw MIDI", f"{source} emits its unchanged expression", {
                "type": raw_type, "channel": source_channel, "data1": data1, "value": value,
            }),
            TraceStep("source profile", f"{source} {message_type} {data1} resolves to {physical}"),
            TraceStep("logical state", "Scene and virtual palettes select the current logical sound", dict(self._state)),
            TraceStep("logical sound", logical),
        ]
        expression = self._expression_route(source, physical, decoder.emit.get("expressions", ()))
        if message_type == "poly_aftertouch" and expression is not None and expression["expression"] == "pressure":
            if expression.get("correlation") != "source_channel_note":
                raise SimulationError("pressure route must correlate source_channel_note")
            ddrum_target = expression["targets"]["ddrum4"]
            sd3_target = expression["targets"]["sd3"]
            drumgizmo_target = expression["targets"]["drumgizmo"]
            ddrum_event = ddrum_target.get("event", {})
            sd3_event = sd3_target.get("event", {})
            drumgizmo_event = drumgizmo_target.get("event", {})
            assert active_hit is not None
            ddrum = active_hit.ddrum_message
            sd3 = active_hit.sd3_message
            drumgizmo = active_hit.drumgizmo_message
            steps.append(TraceStep("active hit ledger", "uses the renderer destination selected by the preceding Note-On", {
                "physical": active_hit.physical, "logical_target": active_hit.logical_target,
                "hit_state": dict(active_hit.state), "raw_note": data1,
            }))
            if (ddrum_target.get("status") in {"planned", "measured", "user-confirmed"}
                    and ddrum_event.get("type") == "poly_aftertouch"
                    and ddrum_event.get("note_from") == "active_rendered_hit"):
                ddrum_status = ddrum_target["status"]
                ddrum_message = {
                    "type": "poly_aftertouch", "channel": ddrum["channel"],
                    "note": ddrum["note"], "value": value, "correlated_raw_note": data1,
                }
                if ddrum_status == "planned":
                    ddrum_message.update({
                        "declared_status": ddrum_status, "preview_only": True, "hardware_output": "disabled",
                    })
                ddrum_step = TraceStep(
                    "Arduino DDrum4 renderer",
                    ("planned preview only; pressure would follow the active rendered hit after physical choke measurement"
                     if ddrum_status == "planned" else "declared pressure follows the active rendered hit"), {
                        **ddrum_message,
                    })
            else:
                ddrum_step = TraceStep("Arduino DDrum4 renderer", "unsupported: no reviewed active-rendered-hit pressure route", ddrum_target)
            if (sd3_target.get("status") in {"planned", "measured", "user-confirmed"}
                    and sd3_event.get("type") == "poly_aftertouch"
                    and sd3_event.get("note_from") == "active_rendered_hit"):
                sd3_status = sd3_target["status"]
                sd3_message = {
                    "type": "poly_aftertouch", "channel": sd3["channel"],
                    "note": sd3["note"], "value": value, "correlated_raw_note": data1,
                }
                if sd3_status == "planned":
                    sd3_message.update({
                        "declared_status": sd3_status, "preview_only": True, "hardware_output": "disabled",
                    })
                sd3_step = TraceStep(
                    "SD3 renderer",
                    ("planned preview only; pressure would follow the active rendered hit after physical choke measurement"
                     if sd3_status == "planned" else "declared pressure follows the active rendered hit"), {
                        **sd3_message,
                    })
                sd3_target_step = TraceStep(
                    "SD3 declared target",
                    (f"Planned preview: the selected SD3 kit would receive {physical} pressure on its active hit"
                     if sd3_status == "planned" else
                     f"The selected SD3 kit would receive {physical} pressure on its active hit"),
                )
            else:
                sd3_step = TraceStep("SD3 renderer", "unsupported: no reviewed active-rendered-hit pressure route", sd3_target)
                sd3_target_step = TraceStep("SD3 declared target", "no SD3 pressure is emitted")
            if (drumgizmo_target.get("status") in {"measured", "user-confirmed"}
                    and drumgizmo_event.get("type") == "poly_aftertouch"
                    and drumgizmo_event.get("note_from") == "active_rendered_hit"):
                drumgizmo_step = TraceStep(
                    "DrumGizmo renderer", "reviewed pressure chokes the active rendered cymbal", {
                        "type": "poly_aftertouch", "channel": drumgizmo["channel"],
                        "note": drumgizmo["note"], "value": value,
                        "correlated_raw_note": data1,
                    },
                )
            else:
                drumgizmo_step = TraceStep(
                    "DrumGizmo renderer", "unsupported: no reviewed active-rendered-hit pressure route",
                    drumgizmo_target,
                )
            steps.extend((
                ddrum_step,
                sd3_step,
                sd3_target_step,
                drumgizmo_step,
            ))
        elif message_type == "cc" and expression is not None and expression["expression"] == "position":
            sd3_target = expression["targets"]["sd3"]
            sd3_event = sd3_target["event"]
            if (sd3_target.get("status") in {"measured", "user-confirmed"}
                    and sd3_event.get("type") == "cc" and sd3_event.get("transform") == "passthrough"):
                sd3_step = TraceStep("SD3 renderer", f"{sd3_target['status']} positional CC passthrough", {
                    "type": "control_change", "channel": sd3_event["channel"],
                    "cc": sd3_event["cc"], "value": value,
                })
                sd3_target_step = TraceStep(
                    "SD3 declared target", f"The selected snare receives {physical} position on CC{sd3_event['cc']}",
                )
            else:
                sd3_step = TraceStep("SD3 renderer", "unsupported: no reviewed positional CC route", sd3_target)
                sd3_target_step = TraceStep("SD3 declared target", "no SD3 position is emitted")
            steps.extend((
                TraceStep("Arduino DDrum4 renderer", "unsupported: positional thresholds are not physically measured",
                          expression["targets"]["ddrum4"]),
                sd3_step,
                sd3_target_step,
                TraceStep("DrumGizmo renderer", "unsupported: the exported kit has no reviewed positional runtime rule",
                          expression["targets"]["drumgizmo"]),
            ))
        elif message_type == "cc" and expression is not None and expression["expression"] == "openness":
            sd3_event = expression["targets"]["sd3"]["event"]
            sd3_status = expression["targets"]["sd3"]["status"]
            ddrum_target = expression["targets"]["ddrum4"]
            drumgizmo_target = expression["targets"]["drumgizmo"]
            ddrum_event = ddrum_target["event"]
            ddrum_status = ddrum_target["status"]
            preview = None
            if ddrum_status in {"planned", "measured", "user-confirmed"} and ddrum_event.get("type") == "quantized_note_p":
                try:
                    preview = self._quantized_hihat_preview(physical, value, ddrum_event)
                    preview.update({
                        "declared_status": ddrum_status,
                        "preview_only": ddrum_status == "planned",
                        "hardware_output": "disabled",
                        "next_hit_notes": self._quantized_hihat_notes(value, ddrum_event),
                    })
                except SimulationError:
                    if ddrum_status != "planned":
                        raise
            if preview is not None:
                detail = (
                    f"planned preview only; next {physical} hit would select DDrum4 Note-P note "
                    f"{preview['next_hit_note']} after physical CC4 measurement"
                    if ddrum_status == "planned" else
                    f"{ddrum_status} CC4 state; next {physical} hit selects DDrum4 Note-P note {preview['next_hit_note']}"
                )
                ddrum_step = TraceStep(
                    "Arduino DDrum4 renderer",
                    detail,
                    preview,
                )
            else:
                ddrum_step = TraceStep(
                    "Arduino DDrum4 renderer",
                    "planned: quantized NOTE P needs measured CC polarity and thresholds",
                    ddrum_target,
                )
            drumgizmo_event = drumgizmo_target["event"]
            drumgizmo_status = drumgizmo_target["status"]
            preview = None
            if (drumgizmo_status in {"planned", "measured", "user-confirmed"}
                    and drumgizmo_event.get("type") == "quantized_note"):
                try:
                    preview = self._quantized_hihat_preview(physical, value, drumgizmo_event)
                    preview.update({
                        "declared_status": drumgizmo_status,
                        "preview_only": drumgizmo_status == "planned",
                        "hardware_output": "disabled",
                        "next_hit_notes": self._quantized_hihat_notes(value, drumgizmo_event),
                    })
                except SimulationError:
                    if drumgizmo_status != "planned":
                        raise
            if preview is not None:
                detail = (
                    f"planned preview only; next {physical} hit would select DrumGizmo note "
                    f"{preview['next_hit_note']} after physical CC4 measurement"
                    if drumgizmo_status == "planned" else
                    f"{drumgizmo_status} CC4 state; next {physical} hit selects DrumGizmo note {preview['next_hit_note']}"
                )
                drumgizmo_step = TraceStep(
                    "DrumGizmo renderer",
                    detail,
                    preview,
                )
            else:
                drumgizmo_step = TraceStep(
                    "DrumGizmo renderer", "unsupported: declared DrumGizmo map is note-only", drumgizmo_target,
                )
            if (sd3_status in {"measured", "user-confirmed"}
                    and sd3_event.get("type") == "cc" and sd3_event.get("transform") == "passthrough"):
                sd3_step = TraceStep("SD3 renderer", f"{sd3_status} passthrough expression route", {
                    "type": "control_change", "channel": sd3_event["channel"], "cc": sd3_event["cc"], "value": value,
                })
                sd3_target_step = TraceStep(
                    "SD3 declared target", f"The selected SD3 kit would receive {physical} openness without a new hit",
                )
            else:
                sd3_step = TraceStep("SD3 renderer", "unsupported: no reviewed SD3 openness route", expression["targets"]["sd3"])
                sd3_target_step = TraceStep("SD3 declared target", "no SD3 expression is emitted")
            steps.extend((
                ddrum_step,
                sd3_step,
                sd3_target_step,
                drumgizmo_step,
            ))
        else:
            steps.extend((
                TraceStep("Arduino DDrum4 renderer", "unsupported: the verified firmware-project generator lowers exact Note decoders only"),
                TraceStep("SD3 renderer", "unverified here: no measured common expression-routing/v1 target is declared"),
                TraceStep("DrumGizmo renderer", "unsupported: the declared DrumGizmo map is note-only"),
            ))
        return SimulationResult(source, data1, value, physical, logical, dict(self._state), tuple(steps),
                                raw_type=raw_type, renders_audio=False)

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
        value. Every exact Note path is exercised at MIDI velocities 1 and
        127, and every declared logical-control channel is covered. It catches
        boundary and protocol drift without inventing the unbounded Cartesian
        product of arbitrary MIDI VP values.
        """
        cases: list[DiagnosticCase] = []
        for scene, values in self._diagnostic_state_vectors():
            for decoder in self.project.source_decoders:
                if decoder.message_type in {"note", "note_range"}:
                    notes = (decoder.match["note"],) if decoder.message_type == "note" else range(
                        decoder.match["note_range"][0], decoder.match["note_range"][1] + 1)
                    for note in notes:
                        for velocity in (1, 127):
                            identifier = self._diagnostic_id("pad", decoder.source, note, scene, values, velocity)
                            candidate = RigSimulator(self.project)
                            try:
                                candidate.set_state(scene=scene, values=values)
                                result = candidate.simulate_pad(decoder.source, note, velocity)
                                cases.append(DiagnosticCase(identifier, True,
                                    f"{result.physical} -> {result.logical_target} at v{velocity:03d}; DDrum4/SD3/DrumGizmo declared"))
                            except SimulationError as error:
                                cases.append(DiagnosticCase(identifier, False, str(error)))
                elif decoder.message_type in {"cc", "poly_aftertouch"}:
                    if decoder.message_type == "cc":
                        addresses = (decoder.match["cc"],)
                    elif decoder.match.get("active_note"):
                        addresses = tuple(item.match["note"] for item in self.project.source_decoders
                                          if item.source == decoder.source and item.physical == decoder.physical
                                          and item.message_type == "note")
                    else:
                        addresses = (decoder.match.get("note", 0),)
                    if not addresses:
                        addresses = (0,)
                    for data1 in addresses:
                        identifier = self._diagnostic_id(decoder.message_type, decoder.source, data1, scene, values)
                        candidate = RigSimulator(self.project)
                        try:
                            candidate.set_state(scene=scene, values=values)
                            if decoder.message_type == "poly_aftertouch" and decoder.match.get("active_note"):
                                candidate.simulate_pad(decoder.source, data1, 100)
                            result = candidate.simulate_expression(decoder.source, decoder.message_type, data1, 64)
                            declared_sd3 = next((step for step in result.steps if step.stage == "SD3 renderer"), None)
                            if declared_sd3 is None or "unverified" in declared_sd3.detail or "unsupported" in declared_sd3.detail:
                                raise SimulationError("no declared reviewed SD3 expression route")
                            cases.append(DiagnosticCase(identifier, True,
                                f"{result.physical} expression reaches its declared active renderer route"))
                        except SimulationError as error:
                            cases.append(DiagnosticCase(identifier, False, str(error)))
        scene_control = self.project.logical_control_protocol["scene"]
        for index, scene in enumerate(self.project.scenes):
            for channel_index, channel in enumerate(scene_control["channels"]):
                candidate = RigSimulator(self.project)
                suffix = "" if channel_index == 0 else f".ch{channel:02d}"
                identifier = f"logical.scene.pc{index:03d}{suffix}"
                try:
                    candidate.simulate_logical_control("simulator", channel, "program_change", index)
                    cases.append(DiagnosticCase(identifier, True, f"selects scene {scene} on CH{channel}"))
                except SimulationError as error:
                    cases.append(DiagnosticCase(identifier, False, str(error)))
        for variable, values in self._diagnostic_variable_values().items():
            control = self.project.logical_control_protocol[variable]
            for value in sorted(values):
                for channel_index, channel in enumerate(control["channels"]):
                    candidate = RigSimulator(self.project)
                    suffix = "" if channel_index == 0 else f".ch{channel:02d}"
                    identifier = f"logical.{variable}.cc{control['cc']:03d}.v{value:03d}{suffix}"
                    try:
                        candidate.simulate_logical_control("simulator", channel, "cc", control["cc"], value)
                        cases.append(DiagnosticCase(identifier, True, f"sets {variable}={value} on CH{channel}"))
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
    def _diagnostic_id(kind: str, source: str, note: int, scene: str, values: Mapping[str, int], velocity: int | None = None) -> str:
        suffix = ".".join(f"{name}{value}" for name, value in sorted(values.items()))
        velocity_suffix = f".v{velocity:03d}" if velocity is not None else ""
        return f"{kind}.{source}.n{note:03d}{velocity_suffix}.{scene}.{suffix or 'default'}"

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

    def _expression_decoder(self, source: str, message_type: str, data1: int):
        for decoder in self.project.source_decoders:
            if decoder.source != source or decoder.message_type != message_type:
                continue
            if message_type == "cc" and decoder.match["cc"] == data1:
                return decoder
            if message_type == "poly_aftertouch" and (
                    decoder.match.get("note") == data1 if "note" in decoder.match
                    else bool(decoder.match.get("active_note"))):
                return decoder
        return None

    def _expression_route(self, source: str, physical: str, expressions: object) -> Mapping[str, Any] | None:
        """Return one declared expression-routing/v1 route for this decoder."""
        if not isinstance(expressions, (list, tuple)):
            return None
        routes = self.project.raw.get("expression_routing", ())
        if not isinstance(routes, (list, tuple)):
            return None
        for expression in expressions:
            for route in routes:
                if (isinstance(route, Mapping) and route.get("source") == source
                        and route.get("physical") == physical and route.get("expression") == expression):
                    return route
        return None

    def _logical_target(self, physical: str) -> str:
        scene = self._state["scene"]
        variants = logical_route_variants(self.project.logical_routes[scene][physical])
        ordered = sorted(variants, key=lambda variant: not variant.predicates)
        for variant in ordered:
            if all(self._state[name] == value for name, value in variant.predicates.items()):
                return variant.logical_target
        raise SimulationError(f"no logical route for {physical!r} in scene {scene!r}")

    @staticmethod
    def _firmware_hihat_openness(value: int, closed: int, opened: int) -> int:
        """Normalize CC4 exactly like the integer-only Arduino implementation."""
        span = opened - closed
        if not span:
            return 0

        def trunc_div(numerator: int, denominator: int) -> int:
            quotient = abs(numerator) // abs(denominator)
            return -quotient if (numerator < 0) != (denominator < 0) else quotient

        half_span = trunc_div(span, 2)
        normalized = trunc_div((value - closed) * 127 + half_span, span)
        return min(127, max(0, normalized))

    @staticmethod
    def _quantized_hihat_preview(physical: str, value: int, event: Mapping[str, Any]) -> dict[str, Any]:
        """Preview the next discrete hi-hat hit for a reviewed CC4 calibration."""
        closed, opened = event.get("input_closed"), event.get("input_open")
        articulations = event.get("articulations")
        if not isinstance(closed, int) or not isinstance(opened, int) or closed == opened:
            raise SimulationError("reviewed hi-hat event has no valid pedal endpoints")
        if not isinstance(articulations, list):
            raise SimulationError("reviewed hi-hat event has no articulation zones")
        selected = next((item for item in articulations if isinstance(item, Mapping) and item.get("physical") == physical), None)
        if selected is None:
            raise SimulationError(f"reviewed hi-hat event has no zones for {physical}")
        notes, boundaries = selected.get("notes"), selected.get("upper_boundaries")
        if not isinstance(notes, list) or not notes or not isinstance(boundaries, list) or len(boundaries) != len(notes) - 1:
            raise SimulationError("reviewed hi-hat zones are invalid")
        normalized = RigSimulator._firmware_hihat_openness(value, closed, opened)
        zone = next((index for index, boundary in enumerate(boundaries) if normalized <= boundary), len(notes) - 1)
        return {
            "type": "cc4_state", "input_cc": 4, "value": value,
            "normalized_openness": normalized, "physical": physical,
            "zone": zone + 1, "next_hit_note": notes[zone], "notes": notes,
            "upper_boundaries": boundaries,
        }

    @classmethod
    def _quantized_hihat_notes(cls, value: int, event: Mapping[str, Any]) -> dict[str, int]:
        """Preview every declared bow/edge destination for one retained CC4 value."""
        articulations = event.get("articulations")
        if not isinstance(articulations, list):
            raise SimulationError("reviewed hi-hat event has no articulation zones")
        result: dict[str, int] = {}
        for articulation in articulations:
            physical = articulation.get("physical") if isinstance(articulation, Mapping) else None
            if not isinstance(physical, str):
                raise SimulationError("reviewed hi-hat articulation has no physical role")
            result[physical] = cls._quantized_hihat_preview(physical, value, event)["next_hit_note"]
        return result
