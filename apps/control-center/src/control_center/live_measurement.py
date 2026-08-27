"""File-backed hand-off from an offline rig project to live measurements.

The campaign deliberately records what needs to be observed, rather than
turning a ``SIM_*`` address into a plausible live address.  It performs no
MIDI, audio, serial, or firmware operation.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Callable, Sequence

from drum_domain.rig_project import RigProject, load_rig_project


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
        lines.extend(["", "## Flash gate", ""])
        lines.extend(f"1. {step}" for step in document["flash_gate"])  # type: ignore[index]
        lines.append("")
        return "\n".join(lines)

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
