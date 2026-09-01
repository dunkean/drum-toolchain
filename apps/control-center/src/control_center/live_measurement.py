"""File-backed verification of a configured rig before live deployment.

Endpoint names are discovered on the live host. Source channels, Notes,
controllers and ranges are prescribed by the rig project and written to the
modules; traces verify exact equality and never rewrite that contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Callable, Mapping, Sequence

import yaml

from drum_domain.rig_project import RigProject, SourceDecoder, load_rig_project
from midi_lab.traces import MidiTrace


def discover_midi_port_inventory(
    get_input_names: Callable[[], Sequence[str]] | None = None,
    get_output_names: Callable[[], Sequence[str]] | None = None,
) -> dict[str, tuple[str, ...]]:
    """List currently visible ports without opening an input or output stream.

    Callers must still explicitly bind and measure a port in a campaign.  The
    inventory is deliberately a momentary OS observation, never proof that a
    similarly named cable has the expected source or destination.
    """
    if get_input_names is None or get_output_names is None:
        try:
            import mido
        except ImportError as error:  # pragma: no cover - optional live dependency
            raise RuntimeError("mido is required to inspect visible MIDI ports") from error
        get_input_names, get_output_names = mido.get_input_names, mido.get_output_names
    inputs = get_input_names()
    outputs = get_output_names()
    if not all(isinstance(name, str) and name for name in (*inputs, *outputs)):
        raise ValueError("MIDI port inventory must contain non-empty names")
    return {"inputs": tuple(inputs), "outputs": tuple(outputs)}


@dataclass(frozen=True)
class HihatCalibration:
    """Operator-confirmed CC4 endpoints and normalized renderer zone boundaries."""

    input_closed: int
    input_open: int
    boundaries: Mapping[str, Mapping[str, Sequence[int]]]

    def __post_init__(self) -> None:
        for name, value in (("input_closed", self.input_closed), ("input_open", self.input_open)):
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 127:
                raise ValueError(f"{name} must be a MIDI value from 0 to 127")
        if self.input_closed == self.input_open:
            raise ValueError("hi-hat closed and open endpoints must be distinct")


@dataclass(frozen=True)
class PressureConfirmation:
    """Explicit renderer acceptance after raw choke traces were reviewed.

    A source trace proves only what the trigger module emitted.  It cannot
    prove how DDrum4 or SD3 reacts, so promotion requires a separate operator
    confirmation for each renderer target instead of calling it measured.
    """

    targets: frozenset[str]

    def __post_init__(self) -> None:
        if not self.targets or not self.targets <= {"ddrum4", "sd3"}:
            raise ValueError("pressure confirmation targets must be ddrum4 and/or sd3")


@dataclass(frozen=True)
class LiveMeasurementCampaign:
    """A deterministic checklist for creating a measured ``deployment: live`` rig."""

    project_path: Path
    project_sha256: str
    project: RigProject

    @classmethod
    def from_path(cls, path: Path) -> "LiveMeasurementCampaign":
        source = path.resolve()
        content = source.read_bytes()
        return cls(source, sha256(content).hexdigest(), load_rig_project(source))

    def to_document(self) -> dict[str, object]:
        inputs = []
        for name, source in self.project.sources.items():
            physical = sorted({decoder.physical for decoder in self.project.source_decoders if decoder.source == name})
            inputs.append({
                "id": name,
                "declared_endpoint": source.endpoint,
                "declared_channel": source.channel,
                "physical_events": physical,
                "required": [
                    "record the exact operating-system port name",
                    "select whether the observed source reaches the PC over DIN/THRU or direct USB",
                    "verify one isolated MIDI trace for every physical event and zone against the prescribed address",
                    "record CC/aftertouch/choke separately where the module exposes it",
                ],
                "status": "needs-live-measurement",
            })
        trace_requests = []
        for decoder in self.project.source_decoders:
            if decoder.message_type not in {"note", "note_range", "cc", "poly_aftertouch"}:
                continue
            expression = decoder.message_type in {"cc", "poly_aftertouch"}
            trace_requests.append({
                "id": self.trace_identifier(decoder),
                "source": decoder.source,
                "physical": decoder.physical,
                "message_type": decoder.message_type,
                "matcher": dict(decoder.match),
                "trace": self.trace_relative_path(decoder),
                "acceptance": ("one isolated Note On address (channel + note)" if decoder.message_type == "note" else
                               "one isolated positional sweep on one channel containing every contiguous Note On code"
                               if decoder.message_type == "note_range" else
                               "one isolated Note On followed by poly-aftertouch on the same channel/note, with no other active hit"
                               if decoder.message_type == "poly_aftertouch" else
                               "one isolated controller/aftertouch address (channel + data1); retain every observed value"),
                "status": "pending",
            })
        for name, native in self.project.native_control_map.items():
            native_type = native["type"]
            source = native.get("source")
            address_key = "program" if native_type == "program_change" else "cc" if native_type == "cc" else "note"
            trace_requests.append({
                "id": self.native_trace_identifier(name),
                "source": source,
                "physical": f"native_control.{native['decode_to']}",
                "message_type": native_type,
                "matcher": {"source": source, "type": native_type, address_key: native[address_key]},
                "trace": self.native_trace_relative_path(name, native),
                "acceptance": "one isolated native panel command (channel + exact address)",
                "status": "pending",
            })
        state_actions = []
        for scene, actions in self.project.ddrum_state_actions.items():
            for index, action in enumerate(actions, start=1):
                state_actions.append({
                    "id": f"{scene}.action{index}", "scene": scene, "type": action.action_type,
                    "status": action.status,
                    "required": "observe the DDrum4 panel/result and retain a trace before marking user-confirmed",
                })
        return {
            "kind": "drum-live-measurement-campaign/v1",
            "hardware_io": "disabled",
            "source_project": str(self.project_path),
            "source_sha256": self.project_sha256,
            "source_deployment": self.project.deployment,
            "target_deployment": "live",
            "do_not_copy_simulation_endpoints": True,
            "source_addresses_are_prescribed": True,
            "inputs": inputs,
            "trace_requests": trace_requests,
            "control_bus": ({"declared_endpoint": self.project.control_bus["endpoint"],
                             "declared_channel": self.project.control_bus["channel"],
                             "status": self.project.control_bus["status"],
                             "required": "measure the exact PC/Master Merger endpoint and prove the return path"}
                            if self.project.control_bus is not None else
                            {"status": "missing", "required": "declare and measure the PC/Master Merger control endpoint"}),
            "ddrum4": {"output_channel": self.project.ddrum4_output_channel,
                       "required": "confirm DDrum4 MIDI IN channel and Local Off behavior with a no-pad trace"},
            "state_actions": state_actions,
            "flash_gate": [
                "replace SIM_* endpoint names while preserving every prescribed source channel/note/CC address",
                "compile a deployment: live project with no lowering blockers",
                "require firmware-project-mapping.json status=ready and hardware_flash=ready",
                "only then build and flash the Arduino",
            ],
        }

    def render_markdown(self) -> str:
        document = self.to_document()
        lines = [
            "# Live rig measurement campaign", "",
            f"Source project: `{self.project_path}`", f"SHA-256: `{self.project_sha256}`", "",
            "## Rule", "", "Replace `SIM_*` endpoint names only. Source channels, Notes, CCs and ranges are prescribed; every trace must match them exactly.", "",
            "## Inputs", "",
        ]
        for item in document["inputs"]:  # type: ignore[index]
            lines.append(f"- **{item['id']}** — declared {item['declared_endpoint']} / C{item['declared_channel']}; "
                         f"measure: {', '.join(item['physical_events']) or 'no input declared'}.")
        lines.extend(["", "## Isolated traces", ""])
        for request in document["trace_requests"]:  # type: ignore[index]
            trace = f"`{request['trace']}`" if request["trace"] else "**manual calibration**"
            lines.append(f"- {trace} — **{request['id']}**: {request['acceptance']}.")
        lines.extend([
            "", "## Guided capture", "",
            "From the repository root, preview the next missing trace without opening MIDI:", "",
            "```powershell",
            "./scripts/capture-greg-hybrid-live-trace.ps1 -Campaign <this-directory>",
            "```", "",
            "Then capture exactly that pad/zone from one explicit raw input:", "",
            "```powershell",
            "./scripts/capture-greg-hybrid-live-trace.ps1 -Campaign <this-directory> -InputPort '<exact-port-name>' -Capture",
            "```", "",
            "The helper listens only; it never opens a MIDI output, writes a module, or flashes Arduino.",
            "", "All native Scene/Palette controls can instead be captured in one exact atomic sequence:", "",
            "```powershell",
            "./scripts/capture-greg-hybrid-native-controls.ps1 -Campaign <this-directory>",
            "./scripts/capture-greg-hybrid-native-controls.ps1 -Campaign <this-directory> -InputPort '<exact-port-name>' -Capture -ConfirmSequence",
            "```", "",
            "The bulk helper publishes no isolated trace unless the complete ordered sequence matches the contract.",
        ])
        lines.extend(["", "## Flash gate", ""])
        lines.extend(f"1. {step}" for step in document["flash_gate"])  # type: ignore[index]
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def trace_relative_path(decoder: SourceDecoder) -> str:
        """Stable trace location for one exact source-decoder address.

        Physical IDs are deliberately insufficient: a positional pad can have
        several raw Note decoders for the same physical event.  The matcher is
        therefore part of the capture identity.
        """
        safe_physical = decoder.physical.replace(".", "-")
        return f"traces/{decoder.source}__{safe_physical}__{LiveMeasurementCampaign._matcher_identifier(decoder)}.jsonl"

    @staticmethod
    def trace_identifier(decoder: SourceDecoder) -> str:
        """Stable review/promote key for one declared source decoder."""
        return f"{decoder.source}.{decoder.physical}.{LiveMeasurementCampaign._matcher_identifier(decoder)}"

    @staticmethod
    def native_trace_identifier(name: str) -> str:
        return f"native.{name}"

    @staticmethod
    def native_trace_relative_path(name: str, native: Mapping[str, object]) -> str:
        native_type = str(native["type"])
        address = native["program"] if native_type == "program_change" else native["cc"] if native_type == "cc" else native["note"]
        source = str(native.get("source") or "global")
        safe_name = "".join(character if character.isalnum() or character in "-_" else "-" for character in name)
        kind = "program" if native_type == "program_change" else native_type
        return f"traces/{source}__native__{safe_name}__{kind}-{int(address):03d}.jsonl"

    @staticmethod
    def _matcher_identifier(decoder: SourceDecoder) -> str:
        match = decoder.match
        if decoder.message_type == "note":
            return f"note-n{match['note']:03d}"
        if decoder.message_type == "note_range":
            low, high = match["note_range"]
            return f"note-range-n{low:03d}-n{high:03d}"
        if decoder.message_type == "cc":
            return f"cc-{match['cc']:03d}"
        if "note" in match:
            return f"poly-aftertouch-n{match['note']:03d}"
        if match.get("active_note"):
            return "poly-aftertouch-active-note"
        return "poly-aftertouch-unresolved"

    @classmethod
    def read(cls, directory: Path) -> "LiveMeasurementCampaign":
        """Reload a campaign and reject a changed source project before review."""
        plan = directory.resolve() / "live-measurement-plan.json"
        try:
            document = json.loads(plan.read_text(encoding="utf-8"))
            source = Path(document["source_project"])
            expected = document["source_sha256"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid live measurement campaign: {plan}") from error
        if not isinstance(expected, str):
            raise ValueError("live measurement campaign has no source SHA-256")
        campaign = cls.from_path(source)
        if campaign.project_sha256 != expected:
            raise ValueError("source rig project changed since this measurement campaign was created")
        return campaign

    def import_native_control_sequence(self, directory: Path, sequence_trace: Path) -> tuple[Path, ...]:
        """Split one exact panel sequence into isolated native-control proofs.

        The operator can exercise every Scene/Palette button during one bounded
        receive-only recording.  Nothing is published unless the supported
        MIDI events match the complete declared sequence exactly.  Existing
        isolated evidence is never overwritten by this bulk helper.
        """
        root = directory.resolve()
        trace = MidiTrace.read(sequence_trace.resolve())
        expected: list[tuple[str, Mapping[str, object], str, int, int]] = []
        event_type_by_native = {
            "program_change": "program_change",
            "cc": "control_change",
            "note": "note_on",
        }
        address_key_by_native = {"program_change": "program", "cc": "cc", "note": "note"}
        for name, native in self.project.native_control_map.items():
            native_type = str(native["type"])
            event_type = event_type_by_native[native_type]
            source = native.get("source")
            channel = (self.project.sources[str(source)].channel if source is not None
                       else int(native["channel"]))
            address = int(native[address_key_by_native[native_type]])
            expected.append((name, native, event_type, channel, address))

        supported = set(event_type_by_native.values())
        observed = [event for event in trace.events
                    if event.message_type in supported
                    and not (event.message_type == "note_on" and (event.data2 is None or event.data2 == 0))]
        if len(observed) != len(expected):
            raise ValueError(
                f"native control sequence needs exactly {len(expected)} supported events; observed {len(observed)}"
            )
        for index, ((name, _native, event_type, channel, address), event) in enumerate(
                zip(expected, observed), start=1):
            actual = (event.message_type, event.channel, event.data1)
            wanted = (event_type, channel, address)
            if actual != wanted:
                raise ValueError(
                    f"native control sequence item {index} ({name}) expected "
                    f"{event_type} C{channel} data1={address}; observed "
                    f"{event.message_type} C{event.channel} data1={event.data1}"
                )

        destinations = tuple(root / self.native_trace_relative_path(name, native)
                             for name, native, _event_type, _channel, _address in expected)
        existing = [path for path in destinations if path.exists()]
        if existing:
            raise FileExistsError(
                "bulk native-control import never overwrites evidence; already exists: " + str(existing[0])
            )
        temporary = tuple(path.with_suffix(path.suffix + ".importing") for path in destinations)
        stale = [path for path in temporary if path.exists()]
        if stale:
            raise FileExistsError(f"stale native-control import file exists: {stale[0]}")

        committed: list[Path] = []
        try:
            for path, event in zip(temporary, observed):
                MidiTrace(trace.source, (event,)).write(path)
            for staging, destination in zip(temporary, destinations):
                staging.replace(destination)
                committed.append(destination)
        except Exception:
            for path in temporary:
                path.unlink(missing_ok=True)
            for path in committed:
                path.unlink(missing_ok=True)
            raise
        return destinations

    def review_traces(self, directory: Path) -> dict[str, object]:
        """Review isolated capture files without changing the rig project.

        A route becomes *observed* only when an isolated trace contains one
        unambiguous MIDI address. Controller and aftertouch rows retain their
        real observed value range but do not infer pedal thresholds, choke
        semantics, or renderer support. A review is evidence for a later
        human edit of ``deployment: live``; it never writes that profile.
        """
        rows = []
        for decoder in self.project.source_decoders:
            if decoder.message_type not in {"note", "note_range", "cc", "poly_aftertouch"}:
                continue
            identifier = self.trace_identifier(decoder)
            relative = self.trace_relative_path(decoder)
            trace_path = directory / relative
            if not trace_path.is_file():
                rows.append({"id": identifier, "trace": relative, "message_type": decoder.message_type,
                             "status": "missing", "reason": "capture one isolated MIDI event"})
                continue
            try:
                trace = MidiTrace.read(trace_path)
                expected_type = {"note": "note_on", "note_range": "note_on", "cc": "control_change",
                                 "poly_aftertouch": "poly_aftertouch"}[decoder.message_type]
                addresses = {(event.channel, event.data1) for event in trace.events
                             if event.message_type == expected_type and event.channel is not None and event.data1 is not None
                             and event.data2 is not None and (expected_type != "note_on" or event.data2 > 0)}
                values = sorted({event.data2 for event in trace.events
                                 if event.message_type == expected_type and event.channel is not None
                                 and event.data1 is not None and event.data2 is not None
                                 and (expected_type != "note_on" or event.data2 > 0)})
            except (OSError, ValueError, json.JSONDecodeError) as error:
                rows.append({"id": identifier, "trace": relative, "message_type": decoder.message_type,
                             "status": "invalid", "reason": str(error)})
                continue
            if decoder.message_type == "note_range":
                channels = sorted({channel for channel, _note in addresses})
                observed_notes = sorted({note for _channel, note in addresses})
                expected_low, expected_high = decoder.match["note_range"]
                expected_count = expected_high - expected_low + 1
                contiguous = bool(observed_notes) and observed_notes == list(
                    range(observed_notes[0], observed_notes[-1] + 1)
                )
                if len(channels) != 1:
                    rows.append({"id": identifier, "trace": relative, "message_type": decoder.message_type,
                                 "status": "ambiguous" if channels else "empty",
                                 "addresses": [{"channel": channel, "note": note}
                                               for channel, note in sorted(addresses)],
                                 "reason": "one MIDI channel is required for a positional sweep"})
                    continue
                if len(observed_notes) != expected_count or not contiguous:
                    rows.append({"id": identifier, "trace": relative, "message_type": decoder.message_type,
                                 "status": "incomplete-range", "channel": channels[0],
                                 "observed_notes": observed_notes, "expected_position_count": expected_count,
                                 "reason": "capture every contiguous positional Note On code at least once"})
                    continue
                rows.append({"id": identifier, "trace": relative, "message_type": decoder.message_type,
                             "status": "observed", "channel": channels[0], "data1": observed_notes[0],
                             "note_range": [observed_notes[0], observed_notes[-1]],
                             "observed_notes": observed_notes})
                continue
            if len(addresses) != 1:
                rows.append({"id": identifier, "trace": relative, "message_type": decoder.message_type,
                             "status": "ambiguous" if addresses else "empty",
                             "addresses": [{"channel": channel, "note": note} for channel, note in sorted(addresses)],
                             "reason": "one isolated MIDI address is required"})
                continue
            channel, note = next(iter(addresses))
            if decoder.message_type == "poly_aftertouch":
                first_pressure = next(
                    (index for index, event in enumerate(trace.events)
                     if event.message_type == "poly_aftertouch" and
                     (event.channel, event.data1) == (channel, note) and event.data2 is not None),
                    None,
                )
                active: dict[tuple[int, int], int] = {}
                target_note_ons = 0
                for event in trace.events[:first_pressure] if first_pressure is not None else ():
                    if event.channel is None or event.data1 is None:
                        continue
                    address = (event.channel, event.data1)
                    if event.message_type == "note_on" and event.data2 is not None and event.data2 > 0:
                        active[address] = active.get(address, 0) + 1
                        if address == (channel, note):
                            target_note_ons += 1
                    elif event.message_type == "note_off" or (
                            event.message_type == "note_on" and event.data2 == 0):
                        active[address] = max(0, active.get(address, 0) - 1)
                active = {address: count for address, count in active.items() if count}
                if (first_pressure is None or target_note_ons != 1 or
                        active != {(channel, note): 1}):
                    rows.append({
                        "id": identifier, "trace": relative, "message_type": decoder.message_type,
                        "status": "invalid-choke-sequence", "channel": channel, "data1": note,
                        "reason": "capture exactly one Note On followed by same-address poly-aftertouch with no other active hit",
                    })
                    continue
            row = {"id": identifier, "trace": relative, "message_type": decoder.message_type,
                   "status": "observed", "channel": channel, "data1": note}
            if decoder.message_type == "note":
                row["note"] = note
            else:
                row["observed_values"] = values
            rows.append(row)
        # The active-hit ledger can correlate pressure only when the measured
        # aftertouch address is the exact primary Note address for that same
        # source/physical event. Keep this cross-trace invariant visible in
        # review rather than discovering it during firmware generation.
        rows_by_id = {row["id"]: row for row in rows}
        for decoder in self.project.source_decoders:
            if decoder.message_type != "poly_aftertouch":
                continue
            pressure_row = rows_by_id.get(self.trace_identifier(decoder))
            primaries = [item for item in self.project.source_decoders
                         if item.source == decoder.source and item.physical == decoder.physical
                         and item.message_type == "note"]
            if not isinstance(pressure_row, dict) or pressure_row.get("status") != "observed":
                continue
            if len(primaries) != 1:
                pressure_row.update({
                    "status": "invalid-primary-correlation",
                    "reason": "a choke requires exactly one exact primary Note decoder for the same source/physical event",
                })
                continue
            primary_row = rows_by_id.get(self.trace_identifier(primaries[0]))
            if (not isinstance(primary_row, dict) or primary_row.get("status") != "observed" or
                    (pressure_row.get("channel"), pressure_row.get("data1")) !=
                    (primary_row.get("channel"), primary_row.get("data1"))):
                pressure_row.update({
                    "status": "mismatched-primary-note",
                    "reason": "poly-aftertouch channel/note must equal the separately observed primary Note On address",
                })
        for name, native in self.project.native_control_map.items():
            identifier = self.native_trace_identifier(name)
            relative = self.native_trace_relative_path(name, native)
            trace_path = directory / relative
            native_type = native["type"]
            expected_type = {"program_change": "program_change", "cc": "control_change", "note": "note_on"}[native_type]
            if not trace_path.is_file():
                rows.append({"id": identifier, "trace": relative, "message_type": native_type,
                             "status": "missing", "reason": "capture the isolated native panel command"})
                continue
            try:
                trace = MidiTrace.read(trace_path)
                matching = [event for event in trace.events if event.message_type == expected_type
                            and event.channel is not None and event.data1 is not None
                            and (expected_type != "note_on" or event.data2 is not None and event.data2 > 0)]
                addresses = {(event.channel, event.data1) for event in matching}
                values = sorted({event.data2 for event in matching if event.data2 is not None})
            except (OSError, ValueError, json.JSONDecodeError) as error:
                rows.append({"id": identifier, "trace": relative, "message_type": native_type,
                             "status": "invalid", "reason": str(error)})
                continue
            if len(addresses) != 1:
                rows.append({"id": identifier, "trace": relative, "message_type": native_type,
                             "status": "ambiguous" if addresses else "empty",
                             "addresses": [{"channel": channel, "data1": data1} for channel, data1 in sorted(addresses)],
                             "reason": "one isolated native command address is required"})
                continue
            channel, data1 = next(iter(addresses))
            row = {"id": identifier, "trace": relative, "message_type": native_type,
                   "status": "observed", "channel": channel, "data1": data1}
            if values:
                row["observed_values"] = values
            rows.append(row)
        self._enforce_prescribed_source_contract(rows)
        passed = bool(rows) and all(row["status"] == "observed" for row in rows)
        return {"kind": "drum-live-measurement-review/v1", "hardware_io": "disabled",
                "source_project": str(self.project_path), "source_sha256": self.project_sha256,
                "status": "capture-complete-not-live" if passed else "incomplete",
                "rows": rows,
                "next": ("review every observed address, then manually create a deployment: live project"
                         if passed else "capture or re-capture every non-observed trace")}

    def _enforce_prescribed_source_contract(self, rows: list[dict[str, object]]) -> None:
        """Turn any captured address divergence into a hard review failure.

        Module configuration owns the raw address. A trace proves that the
        configured module emitted the prescribed value; it is never an input
        to a remapping algorithm.
        """
        expected: dict[str, dict[str, object]] = {}
        for decoder in self.project.source_decoders:
            if decoder.message_type not in {"note", "note_range", "cc", "poly_aftertouch"}:
                continue
            contract: dict[str, object] = {
                "channel": self.project.sources[decoder.source].channel,
            }
            if decoder.message_type == "note":
                contract["data1"] = decoder.match["note"]
            elif decoder.message_type == "note_range":
                contract["note_range"] = list(decoder.match["note_range"])
            elif decoder.message_type == "cc":
                contract["data1"] = decoder.match["cc"]
            elif "note" in decoder.match:
                contract["data1"] = decoder.match["note"]
            expected[self.trace_identifier(decoder)] = contract
        for name, native in self.project.native_control_map.items():
            source = native.get("source")
            address_key = ("program" if native["type"] == "program_change" else
                           "cc" if native["type"] == "cc" else "note")
            expected[self.native_trace_identifier(name)] = {
                "channel": self.project.sources[source].channel if source is not None else native.get("channel"),
                "data1": native[address_key],
            }
        for row in rows:
            if row.get("status") != "observed":
                continue
            contract = expected.get(str(row.get("id")))
            if contract is None:
                continue
            mismatches = {
                field: {"expected": value, "observed": row.get(field)}
                for field, value in contract.items()
                if row.get(field) != value
            }
            if mismatches:
                row["status"] = "contract-mismatch"
                row["expected"] = contract
                row["reason"] = "captured address differs from the prescribed module configuration"
                row["mismatches"] = mismatches

    def hihat_calibration_requirements(self, review: Mapping[str, object]) -> dict[str, object] | None:
        """Describe the explicit CC4 calibration still needed for live promotion.

        Raw endpoints come only from the isolated CC trace. Renderer thresholds
        remain an operator choice in normalized 0..127 openness space; proposed
        simulation values are exposed for comparison but are never accepted
        implicitly.
        """
        routes = self.project.raw.get("expression_routing", ())
        if not isinstance(routes, Sequence):
            return None
        route = next((item for item in routes
                      if isinstance(item, Mapping) and item.get("expression") == "openness"
                      and any(isinstance(target, Mapping) and target.get("status") == "planned"
                              and isinstance(target.get("event"), Mapping)
                              and target["event"].get("type") in {"quantized_note_p", "quantized_note"}
                              for target in item.get("targets", {}).values())), None)
        if route is None:
            return None
        decoder = next((item for item in self.project.source_decoders
                        if item.source == route.get("source") and item.physical == route.get("physical")
                        and item.message_type == "cc"), None)
        if decoder is None:
            raise ValueError("planned hi-hat quantization has no matching CC decoder")
        identifier = self.trace_identifier(decoder)
        rows = review.get("rows")
        if not isinstance(rows, Sequence):
            raise ValueError("measurement review has no trace rows")
        row = next((item for item in rows if isinstance(item, Mapping) and item.get("id") == identifier), None)
        if row is None or row.get("status") not in {"observed", "configured"}:
            raise ValueError("hi-hat CC trace must be observed before calibration")
        values = row.get("observed_values")
        if (not isinstance(values, list) or len(set(values)) < 2 or
                not all(isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 127 for value in values)):
            raise ValueError("hi-hat CC trace must contain at least two distinct MIDI values")
        targets: dict[str, dict[str, object]] = {}
        for target_name in ("ddrum4", "drumgizmo"):
            target = route["targets"].get(target_name)
            if not isinstance(target, Mapping):
                continue
            event = target.get("event")
            if not isinstance(event, Mapping) or event.get("type") not in {"quantized_note_p", "quantized_note"}:
                continue
            articulations: dict[str, dict[str, object]] = {}
            for articulation in event.get("articulations", ()):
                physical = articulation.get("physical") if isinstance(articulation, Mapping) else None
                notes = articulation.get("notes") if isinstance(articulation, Mapping) else None
                proposed = articulation.get("upper_boundaries") if isinstance(articulation, Mapping) else None
                if not isinstance(physical, str) or not isinstance(notes, list):
                    raise ValueError(f"{target_name} hi-hat articulation is incomplete")
                articulations[physical] = {
                    "count": len(notes) - 1,
                    "proposed": list(proposed) if isinstance(proposed, list) else [],
                }
            targets[target_name] = {"articulations": articulations}
        return {
            "trace_id": identifier,
            "input_cc": row.get("data1"),
            "observed_values": sorted(set(values)),
            "targets": targets,
        }

    def _apply_hihat_calibration(
        self,
        document: dict[str, object],
        review: Mapping[str, object],
        calibration: HihatCalibration | None,
    ) -> None:
        requirements = self.hihat_calibration_requirements(review)
        if requirements is None:
            if calibration is not None:
                raise ValueError("hi-hat calibration was supplied but this project has no planned quantization")
            return
        if calibration is None:
            raise ValueError(
                "planned hi-hat quantization requires measured --hihat-input-closed/open values and explicit renderer boundaries"
            )
        observed_values = set(requirements["observed_values"])
        for endpoint in (calibration.input_closed, calibration.input_open):
            if endpoint not in observed_values:
                raise ValueError(f"hi-hat endpoint {endpoint} was not present in the isolated CC trace")
        expected_targets = requirements["targets"]
        if set(calibration.boundaries) != set(expected_targets):
            raise ValueError("hi-hat calibration must cover exactly the planned ddrum4 and drumgizmo targets")
        routes = document.get("expression_routing")
        if not isinstance(routes, list):
            raise ValueError("live project has no expression_routing list")
        route = next(item for item in routes if item.get("expression") == "openness")
        for target_name, target_requirement in expected_targets.items():
            provided = calibration.boundaries[target_name]
            articulation_requirements = target_requirement["articulations"]
            if set(provided) != set(articulation_requirements):
                raise ValueError(f"{target_name} hi-hat boundaries must cover every planned articulation")
            target = route["targets"][target_name]
            event = target["event"]
            event["input_closed"] = calibration.input_closed
            event["input_open"] = calibration.input_open
            by_physical = {item["physical"]: item for item in event["articulations"]}
            for physical, requirement in articulation_requirements.items():
                boundaries = list(provided[physical])
                expected_count = requirement["count"]
                if (len(boundaries) != expected_count or
                        not all(isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 127
                                for value in boundaries) or
                        any(right <= left for left, right in zip(boundaries, boundaries[1:]))):
                    raise ValueError(
                        f"{target_name}/{physical} needs {expected_count} strictly ascending normalized boundaries from 0 to 126"
                    )
                by_physical[physical]["upper_boundaries"] = boundaries
            target["status"] = "user-confirmed"
            target.pop("reason", None)

    def pressure_confirmation_requirements(self, review: Mapping[str, object]) -> dict[str, object] | None:
        """Return planned choke targets after proving every raw hit/pressure pair."""
        routes = self.project.raw.get("expression_routing", ())
        rows = review.get("rows")
        if not isinstance(routes, Sequence) or not isinstance(rows, Sequence):
            return None
        rows_by_id = {item.get("id"): item for item in rows if isinstance(item, Mapping)}
        planned_routes: list[dict[str, object]] = []
        targets: set[str] = set()
        for route in routes:
            if not isinstance(route, Mapping) or route.get("expression") != "pressure":
                continue
            decoder = next((item for item in self.project.source_decoders
                            if item.source == route.get("source") and item.physical == route.get("physical")
                            and item.message_type == "poly_aftertouch"), None)
            if decoder is None:
                raise ValueError("planned pressure route has no matching poly-aftertouch decoder")
            row = rows_by_id.get(self.trace_identifier(decoder))
            if not isinstance(row, Mapping) or row.get("status") not in {"observed", "configured"}:
                raise ValueError(f"pressure trace for {route.get('source')}.{route.get('physical')} is not observed")
            route_targets = route.get("targets")
            if not isinstance(route_targets, Mapping):
                raise ValueError("planned pressure route has no renderer targets")
            planned = {name for name, target in route_targets.items()
                       if isinstance(target, Mapping) and target.get("status") == "planned"}
            if planned:
                targets.update(planned)
                planned_routes.append({
                    "source": route.get("source"), "physical": route.get("physical"),
                    "trace_id": self.trace_identifier(decoder), "targets": sorted(planned),
                })
        if not planned_routes:
            return None
        return {"routes": planned_routes, "targets": sorted(targets)}

    def _apply_pressure_confirmation(
        self,
        document: dict[str, object],
        review: Mapping[str, object],
        confirmation: PressureConfirmation | None,
    ) -> None:
        requirements = self.pressure_confirmation_requirements(review)
        if requirements is None:
            if confirmation is not None:
                raise ValueError("pressure confirmation was supplied but no planned choke target exists")
            return
        expected = set(requirements["targets"])
        if confirmation is None or set(confirmation.targets) != expected:
            raise ValueError(
                "raw choke traces do not prove renderer behavior; explicitly confirm every planned pressure target: "
                + ", ".join(sorted(expected))
            )
        routes = document.get("expression_routing")
        if not isinstance(routes, list):
            raise ValueError("live project has no expression_routing list")
        for route in routes:
            if not isinstance(route, dict) or route.get("expression") != "pressure":
                continue
            targets = route.get("targets")
            if not isinstance(targets, dict):
                raise ValueError("pressure route has no renderer targets")
            for target_name in confirmation.targets:
                target = targets.get(target_name)
                if isinstance(target, dict) and target.get("status") == "planned":
                    target["status"] = "user-confirmed"
                    target.pop("reason", None)

    def promote_live(
        self,
        directory: Path,
        output: Path,
        *,
        endpoints: Mapping[str, str],
        control_endpoint: str,
        transports: Mapping[str, str] | None = None,
        hihat_calibration: HihatCalibration | None = None,
        pressure_confirmation: PressureConfirmation | None = None,
    ) -> Path:
        """Create a live profile after traces match the configured source map.

        This is intentionally a narrow, one-way hand-off.  It never edits the
        source simulation project, opens a MIDI port, stages a DDTi dump, or
        changes firmware.  A later compiler pass remains the hardware-flash
        gate, especially for unmeasured expression and native state actions.
        """
        review = self.review_traces(directory)
        if review["status"] != "capture-complete-not-live":
            raise ValueError("cannot promote live profile until every isolated MIDI trace is observed")
        output = output.resolve()
        if output.exists():
            raise FileExistsError(f"refusing to overwrite live rig project: {output}")
        required_sources = set(self.project.sources)
        if set(endpoints) != required_sources:
            missing, extra = required_sources - set(endpoints), set(endpoints) - required_sources
            details = []
            if missing:
                details.append("missing endpoint for " + ", ".join(sorted(missing)))
            if extra:
                details.append("unknown endpoint source " + ", ".join(sorted(extra)))
            raise ValueError("; ".join(details))
        if not isinstance(control_endpoint, str) or not control_endpoint.strip() or control_endpoint.upper().startswith("SIM_"):
            raise ValueError("control_endpoint must be a measured non-SIM MIDI output name")
        for source, endpoint in endpoints.items():
            if not isinstance(endpoint, str) or not endpoint.strip() or endpoint.upper().startswith("SIM_"):
                raise ValueError(f"endpoint for {source} must be a measured non-SIM MIDI port name")
        if transports is not None:
            if set(transports) != required_sources:
                missing, extra = required_sources - set(transports), set(transports) - required_sources
                details = []
                if missing:
                    details.append("missing transport for " + ", ".join(sorted(missing)))
                if extra:
                    details.append("unknown transport source " + ", ".join(sorted(extra)))
                raise ValueError("; ".join(details))
            invalid_transports = {source: value for source, value in transports.items() if value not in {"din", "usb"}}
            if invalid_transports:
                source, value = next(iter(invalid_transports.items()))
                raise ValueError(f"transport for {source} must be 'din' or 'usb', got {value!r}")

        observed = {row["id"]: row for row in review["rows"] if isinstance(row, dict)}
        source_channels = {name: source.channel for name, source in self.project.sources.items()}

        document = yaml.safe_load(self.project_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):  # defensive; the project was validated at campaign creation.
            raise ValueError("source rig project is not a YAML object")
        document["deployment"] = "live"
        document["validation_stage"] = "hardware-verified"
        self._apply_hihat_calibration(document, review, hihat_calibration)
        self._apply_pressure_confirmation(document, review, pressure_confirmation)
        if self.project.ddrum4_bank_facts is not None and isinstance(document.get("ddrum4_bank"), dict):
            # A promoted profile may live outside ``profiles/projects``. Keep
            # the immutable bank reference valid from its new location rather
            # than silently dropping its SHA-checked r15 identity.
            bank_path = self.project.ddrum4_bank_facts.manifest
            try:
                manifest_reference = os.path.relpath(bank_path, output.parent).replace("\\", "/")
            except ValueError:  # Windows cannot make a relative path across drives.
                manifest_reference = str(bank_path)
            document["ddrum4_bank"]["manifest"] = manifest_reference
        for identifier, source in document["sources"].items():
            source["endpoint"] = endpoints[identifier]
            source["channel"] = source_channels[identifier]
            if transports is not None:
                transport = transports[identifier]
                source["primary"] = transport
                conventional_profile = "DIN_ONLY" if transport == "din" else "LIVE_USB_PRIMARY"
                if conventional_profile in document["connection_profiles"]:
                    source["connection_profile"] = conventional_profile
                else:
                    profile_name = source.get("connection_profile")
                    policy = document["connection_profiles"].get(profile_name, {})
                    capability = "din_sources" if transport == "din" else "usb_sources"
                    if not policy.get(capability):
                        raise ValueError(
                            f"source {identifier}: no connection profile supports selected {transport} transport"
                        )
        # Source decoders are deliberately copied unchanged. The trace review
        # above has already rejected any channel/Note/CC/range divergence.
        document["ddrum4_output_channel"] = source_channels["ddrum4"]
        if document.get("control_bus") is not None:
            document["control_bus"]["endpoint"] = control_endpoint
            document["control_bus"]["status"] = "user-confirmed"
        for native in document.get("native_control_map", {}).values():
            if native.get("source") == "ddrum4":
                native["channel"] = source_channels["ddrum4"]
        for name, native in document.get("native_control_map", {}).items():
            row = observed.get(self.native_trace_identifier(name))
            if not isinstance(row, dict) or not isinstance(row.get("channel"), int) or not isinstance(row.get("data1"), int):
                raise ValueError(f"missing observed native control {name}")
            source_name = native.get("source")
            if source_name is not None and row["channel"] != source_channels[source_name]:
                raise ValueError(f"native control {name} channel does not match observed source {source_name}")
            # Native control addresses are also prescribed and were checked
            # for exact equality; preserve the project values verbatim.
        for actions in document.get("ddrum_state_actions", {}).values():
            for action in actions:
                if action.get("type") == "program_change":
                    action["channel"] = source_channels["ddrum4"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
        # Re-load immediately so neither an unrecognised endpoint nor a source
        # channel mismatch can leak into a hand-authored live profile.
        load_rig_project(output)
        return output

    def promote_configured(
        self,
        output: Path,
        *,
        endpoints: Mapping[str, str],
        control_endpoint: str,
        transports: Mapping[str, str],
        source_contract: Path,
        ddti_receipt: Path,
        edrumin_receipt: Path,
        hihat_calibration: HihatCalibration,
        pressure_confirmation: PressureConfirmation,
    ) -> Path:
        """Create a live profile from module configuration receipts, without pads.

        The declared raw map is preserved byte-for-byte. Physical traces stay
        mandatory as post-flash functional verification, but they are not a
        prerequisite for generating the first reviewed firmware image.
        """
        output = output.resolve()
        if output.exists():
            raise FileExistsError(f"refusing to overwrite live rig project: {output}")
        required_sources = set(self.project.sources)
        if set(endpoints) != required_sources or set(transports) != required_sources:
            raise ValueError("configured promotion requires one endpoint and transport for every source")
        for source, endpoint in endpoints.items():
            if not isinstance(endpoint, str) or not endpoint.strip() or endpoint.upper().startswith("SIM_"):
                raise ValueError(f"endpoint for {source} must be a non-SIM MIDI port name")
        if not isinstance(control_endpoint, str) or not control_endpoint.strip() or control_endpoint.upper().startswith("SIM_"):
            raise ValueError("control_endpoint must be a non-SIM MIDI output name")
        if any(value not in {"din", "usb"} for value in transports.values()):
            raise ValueError("configured source transports must be din or usb")

        try:
            contract = yaml.safe_load(source_contract.read_text(encoding="utf-8"))
            ddti = json.loads(ddti_receipt.read_text(encoding="utf-8"))
            edrumin = json.loads(edrumin_receipt.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot read module configuration evidence: {error}") from error
        if not isinstance(contract, Mapping) or contract.get("format") != "rig-source-note-contract/v1":
            raise ValueError("source_contract must be a compiled rig-source-note-contract/v1 artifact")
        if contract.get("source_sha256") != self.project_sha256:
            raise ValueError("compiled source contract does not belong to this rig project")
        fingerprint = contract.get("source_contract_sha256")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise ValueError("compiled source contract has no source_contract_sha256")
        if (not isinstance(ddti, Mapping) or ddti.get("kind") != "greg-hybrid-ddti-configuration-receipt/v1"
                or ddti.get("status") != "verified" or ddti.get("source_contract_sha256") != fingerprint
                or ddti.get("candidate_sha256") != ddti.get("readback_sha256")):
            raise ValueError("DDTi evidence is not a verified readback for this source contract")
        if (not isinstance(edrumin, Mapping)
                or edrumin.get("kind") != "greg-hybrid-edrumin-configuration-receipt/v1"
                or edrumin.get("status") != "user-confirmed"
                or edrumin.get("source_contract_sha256") != fingerprint):
            raise ValueError("eDRUMin evidence is not a confirmed snapshot for this source contract")

        document = yaml.safe_load(self.project_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("source rig project is not a YAML object")
        document["deployment"] = "live"
        # This profile is deliberately flashable but not playable yet. Real
        # pad traces must promote a later hardware-verified profile.
        document["validation_stage"] = "post-flash-validation-pending"
        configured_rows: list[dict[str, object]] = []
        for decoder in self.project.source_decoders:
            row: dict[str, object] = {
                "id": self.trace_identifier(decoder), "status": "configured",
                "channel": self.project.sources[decoder.source].channel,
            }
            if decoder.message_type == "note_range":
                row.update({"data1": decoder.match["note_range"][0],
                            "note_range": list(decoder.match["note_range"])})
            elif decoder.message_type == "note":
                row["data1"] = decoder.match["note"]
            elif decoder.message_type == "cc":
                row.update({"data1": decoder.match["cc"],
                            "observed_values": [hihat_calibration.input_open, hihat_calibration.input_closed]})
            elif "note" in decoder.match:
                row["data1"] = decoder.match["note"]
            configured_rows.append(row)
        configured_review: dict[str, object] = {"rows": configured_rows}
        self._apply_hihat_calibration(document, configured_review, hihat_calibration)
        self._apply_pressure_confirmation(document, configured_review, pressure_confirmation)

        for identifier, source in document["sources"].items():
            source["endpoint"] = endpoints[identifier]
            transport = transports[identifier]
            source["primary"] = transport
            profile = "DIN_ONLY" if transport == "din" else "LIVE_USB_PRIMARY"
            if profile not in document["connection_profiles"]:
                raise ValueError(f"source {identifier}: connection profile {profile} is unavailable")
            source["connection_profile"] = profile
        document["control_bus"]["endpoint"] = control_endpoint
        document["control_bus"]["status"] = "user-confirmed"
        if self.project.ddrum4_bank_facts is not None and isinstance(document.get("ddrum4_bank"), dict):
            try:
                bank_reference = os.path.relpath(self.project.ddrum4_bank_facts.manifest, output.parent).replace("\\", "/")
            except ValueError:
                bank_reference = str(self.project.ddrum4_bank_facts.manifest)
            document["ddrum4_bank"]["manifest"] = bank_reference
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
        load_rig_project(output)
        evidence = {
            "kind": "greg-hybrid-configured-live-evidence/v1", "status": "flash-ready-validation-pending",
            "source_project_sha256": self.project_sha256,
            "source_contract_sha256": fingerprint,
            "source_contract": str(source_contract.resolve()),
            "ddti_receipt": {"path": str(ddti_receipt.resolve()), "sha256": sha256(ddti_receipt.read_bytes()).hexdigest()},
            "edrumin_receipt": {"path": str(edrumin_receipt.resolve()), "sha256": sha256(edrumin_receipt.read_bytes()).hexdigest()},
            "post_flash_required": ["pad dynamics", "CC4/CC16 calibration", "zones", "chokes", "latency"],
        }
        evidence_path = output.with_suffix(".configuration-receipts.json")
        evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return output

    def write_new(self, directory: Path) -> tuple[Path, Path]:
        """Write a new offline plan without overwriting an existing campaign."""
        directory = directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        plan = directory / "live-measurement-plan.json"
        guide = directory / "README.md"
        if plan.exists() or guide.exists():
            raise FileExistsError(f"measurement campaign already exists in {directory}")
        plan.write_text(json.dumps(self.to_document(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        guide.write_text(self.render_markdown(), encoding="utf-8", newline="\n")
        return plan, guide
