"""File-backed hand-off from an offline rig project to live measurements.

The campaign deliberately records what needs to be observed, rather than
turning a ``SIM_*`` address into a plausible live address.  It performs no
MIDI, audio, serial, or firmware operation.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Callable, Mapping, Sequence

import yaml

from drum_domain.rig_project import RigProject, load_rig_project
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
                    "record one isolated MIDI trace for every physical event and zone",
                    "record CC/aftertouch/choke separately where the module exposes it",
                ],
                "status": "needs-live-measurement",
            })
        trace_requests = []
        for decoder in self.project.source_decoders:
            if decoder.message_type not in {"note", "cc", "poly_aftertouch"}:
                continue
            expression = decoder.message_type in {"cc", "poly_aftertouch"}
            trace_requests.append({
                "id": self.trace_identifier(decoder.source, decoder.physical, decoder.message_type),
                "source": decoder.source,
                "physical": decoder.physical,
                "message_type": decoder.message_type,
                "trace": self.trace_relative_path(decoder.source, decoder.physical, decoder.message_type),
                "acceptance": ("one isolated Note On address (channel + note)" if not expression else
                               "one isolated controller/aftertouch address (channel + data1); retain every observed value"),
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
            "do_not_copy_simulation_addresses": True,
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
                "replace SIM_* endpoint and note addresses with captured values",
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
            "## Rule", "", "Do not copy any `SIM_*` endpoint or simulation note into the live project.", "",
            "## Inputs", "",
        ]
        for item in document["inputs"]:  # type: ignore[index]
            lines.append(f"- **{item['id']}** — declared {item['declared_endpoint']} / C{item['declared_channel']}; "
                         f"measure: {', '.join(item['physical_events']) or 'no input declared'}.")
        lines.extend(["", "## Isolated traces", ""])
        for request in document["trace_requests"]:  # type: ignore[index]
            lines.append(f"- `{request['trace']}` — **{request['id']}**: {request['acceptance']}.")
        lines.extend(["", "## Flash gate", ""])
        lines.extend(f"1. {step}" for step in document["flash_gate"])  # type: ignore[index]
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def trace_relative_path(source: str, physical: str, message_type: str = "note") -> str:
        """Stable relative location for one intentionally isolated hit trace."""
        safe_physical = physical.replace(".", "-")
        suffix = "" if message_type == "note" else f"__{message_type.replace('_', '-')}"
        return f"traces/{source}__{safe_physical}{suffix}.jsonl"

    @staticmethod
    def trace_identifier(source: str, physical: str, message_type: str = "note") -> str:
        """Keep legacy Note IDs compact while making expression rows unique."""
        return f"{source}.{physical}" if message_type == "note" else f"{source}.{physical}.{message_type}"

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
            if decoder.message_type not in {"note", "cc", "poly_aftertouch"}:
                continue
            identifier = self.trace_identifier(decoder.source, decoder.physical, decoder.message_type)
            relative = self.trace_relative_path(decoder.source, decoder.physical, decoder.message_type)
            trace_path = directory / relative
            if not trace_path.is_file():
                rows.append({"id": identifier, "trace": relative, "message_type": decoder.message_type,
                             "status": "missing", "reason": "capture one isolated MIDI event"})
                continue
            try:
                trace = MidiTrace.read(trace_path)
                expected_type = {"note": "note_on", "cc": "control_change",
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
            if len(addresses) != 1:
                rows.append({"id": identifier, "trace": relative, "message_type": decoder.message_type,
                             "status": "ambiguous" if addresses else "empty",
                             "addresses": [{"channel": channel, "note": note} for channel, note in sorted(addresses)],
                             "reason": "one isolated MIDI address is required"})
                continue
            channel, note = next(iter(addresses))
            row = {"id": identifier, "trace": relative, "message_type": decoder.message_type,
                   "status": "observed", "channel": channel, "data1": note}
            if decoder.message_type == "note":
                row["note"] = note
            else:
                row["observed_values"] = values
            rows.append(row)
        passed = bool(rows) and all(row["status"] == "observed" for row in rows)
        return {"kind": "drum-live-measurement-review/v1", "hardware_io": "disabled",
                "source_project": str(self.project_path), "source_sha256": self.project_sha256,
                "status": "capture-complete-not-live" if passed else "incomplete",
                "rows": rows,
                "next": ("review every observed address, then manually create a deployment: live project"
                         if passed else "capture or re-capture every non-observed trace")}

    def promote_live(
        self,
        directory: Path,
        output: Path,
        *,
        endpoints: Mapping[str, str],
        control_endpoint: str,
    ) -> Path:
        """Create one new measured live profile from complete isolated traces.

        This is intentionally a narrow, one-way hand-off.  It never edits the
        source simulation project, opens a MIDI port, stages a DDTi dump, or
        changes firmware.  A later compiler pass remains the hardware-flash
        gate, especially for unmeasured expression and native state actions.
        """
        review = self.review_traces(directory)
        if review["status"] != "capture-complete-not-live":
            raise ValueError("cannot promote live profile until every isolated note trace is observed")
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

        observed = {row["id"]: row for row in review["rows"] if isinstance(row, dict)}
        source_channels: dict[str, int] = {}
        notes: dict[tuple[str, str], int] = {}
        for decoder in self.project.source_decoders:
            if decoder.message_type not in {"note", "cc", "poly_aftertouch"}:
                continue
            row = observed.get(self.trace_identifier(decoder.source, decoder.physical, decoder.message_type))
            if not isinstance(row, dict) or not isinstance(row.get("channel"), int) or not isinstance(row.get("data1"), int):
                raise ValueError(f"missing observed address for {decoder.source}.{decoder.physical}")
            prior_channel = source_channels.setdefault(decoder.source, row["channel"])
            if prior_channel != row["channel"]:
                raise ValueError(f"source {decoder.source} has inconsistent observed MIDI channels")
            if decoder.message_type == "note":
                notes[(decoder.source, decoder.physical)] = row["data1"]

        document = yaml.safe_load(self.project_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):  # defensive; the project was validated at campaign creation.
            raise ValueError("source rig project is not a YAML object")
        document["deployment"] = "live"
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
        for decoder in document["source_decoders"]:
            match, emit = decoder["match"], decoder["emit"]
            if match["type"] == "note":
                match["note"] = notes[(match["source"], emit["physical"])]
            elif match["type"] == "cc":
                row = observed[self.trace_identifier(match["source"], emit["physical"], "cc")]
                match["cc"] = row["data1"]
            elif match["type"] == "poly_aftertouch" and "note" in match:
                row = observed[self.trace_identifier(match["source"], emit["physical"], "poly_aftertouch")]
                match["note"] = row["data1"]
        document["ddrum4_output_channel"] = source_channels["ddrum4"]
        if document.get("control_bus") is not None:
            document["control_bus"]["endpoint"] = control_endpoint
            document["control_bus"]["status"] = "user-confirmed"
        for native in document.get("native_control_map", {}).values():
            if native.get("source") == "ddrum4":
                native["channel"] = source_channels["ddrum4"]
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
