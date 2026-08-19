"""Optional local FastAPI surface over the staged DDTi configuration model.

This service stages configuration in memory. Hardware output is available only
through the confirmed-fields validator, exact candidate hash review, and an
explicit confirmation token.
"""
from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import BaseModel

from .discovery import discover_devices
from .diff import diff_ddti_bytes, render_diff
from .models import DDTiConfiguration, decode_configuration
from .mappings import apply_role_template
from .protocol import decode_file
from .transfer import build_safe_write_plan, build_transfer_plan, send_safe_configuration


def _configuration(path: Path) -> DDTiConfiguration:
    configuration = decode_configuration(decode_file(path))
    build_transfer_plan(configuration.raw)
    return configuration


class NotePatch(BaseModel):
    """Per-kit MIDI routing for one Tip/Ring input."""

    tip_channel: int | None = None
    tip_note: int | None = None
    ring_channel: int | None = None
    ring_note: int | None = None


class Input1TipPatch(BaseModel):
    """Input 1 Tip fields isolated by the controlled five-setting capture."""

    gain: int | None = None
    velocity_curve: int | None = None
    threshold: int | None = None
    xtalk: int | None = None
    retrigger: int | None = None


class GlobalTriggerPatch(Input1TipPatch):
    """Global response settings plus the validated PP/SS trigger type."""

    trigger_type: str | None = None

class HiHatKitPatch(BaseModel):
    pedal_channel: int | None = None
    pedal_note: int | None = None
    closed_note: int | None = None


class ProgramChangePatch(BaseModel):
    """Per-kit Program Change; JSON null represents the panel's `---`."""

    program_change: int | None


class RoleTemplateApply(BaseModel):
    """A named note-role template plus the user's explicit physical layout."""

    template: dict[str, object]
    layout: dict[str, object]


class ConfirmedWriteRequest(BaseModel):
    output: str = "TriggerIO"
    expected_sha256: str
    confirmation: str


def create_app(dump_path: Path):
    """Create a local API backed by one explicit, already-captured dump."""
    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as error:  # pragma: no cover - optional dependency
        raise RuntimeError("install the 'ddti[api]' extra to run the local API") from error

    initial = _configuration(dump_path)
    state = {"configuration": initial, "source_raw": initial.raw}
    lock = RLock()
    app = FastAPI(title="DDTi local API", version="0.1.0")

    def current() -> DDTiConfiguration:
        with lock:
            return state["configuration"]

    @app.get("/device")
    def device() -> list[dict[str, object]]:
        return [candidate.to_document() for candidate in discover_devices()]

    @app.get("/device/status")
    def status() -> dict[str, object]:
        return {"connected_candidates": len(discover_devices()), "hardware_write": "confirmed_fields_only"}

    @app.get("/configuration")
    def configuration() -> dict[str, object]:
        return current().to_document()

    @app.get("/staged-diff")
    def staged_diff() -> dict[str, object]:
        """Return the byte-level diff from the explicit source dump to staging."""
        differences = diff_ddti_bytes(state["source_raw"], current().raw)
        return {
            "staged_only": True,
            "hardware_write": "disabled",
            "changed_bytes": len(differences),
            "rendered": render_diff(differences),
        }

    @app.get("/staged-sysex")
    def staged_sysex():
        """Download the staged raw SysEx for offline backup or integration."""
        from fastapi import Response

        return Response(
            content=current().raw,
            media_type="application/octet-stream",
            headers={"Content-Disposition": "attachment; filename=ddti-staged.syx", "X-DDTi-Hardware-Write": "disabled"},
        )

    @app.get("/preset")
    def preset() -> dict[str, object]:
        """Return all confirmed notes as a portable offline preset."""
        return current().to_note_preset()

    @app.get("/configuration-preset")
    def configuration_preset() -> dict[str, object]:
        """Return the complete modeled configuration as a portable preset."""
        try:
            return current().to_configuration_preset()
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/transfer/plan")
    def transfer_plan() -> dict[str, object]:
        """Review raw structural completeness; this endpoint sends nothing."""
        return build_transfer_plan(current().raw).to_document()

    @app.get("/write-plan")
    def write_plan() -> dict[str, object]:
        try:
            plan = build_safe_write_plan(state["source_raw"], current().raw)
        except (ValueError, RuntimeError) as error:
            raise HTTPException(422, str(error)) from error
        document = plan.to_document()
        document["rendered_diff"] = render_diff(plan.differences)
        return document

    @app.post("/write")
    def write(request: ConfirmedWriteRequest) -> dict[str, object]:
        """Write only confirmed fields after exact hash and token validation."""
        with lock:
            try:
                plan = build_safe_write_plan(state["source_raw"], state["configuration"].raw)
                result = send_safe_configuration(
                    state["source_raw"],
                    state["configuration"].raw,
                    request.output,
                    expected_sha256=request.expected_sha256,
                    confirmation=request.confirmation,
                    inter_message_ms=50,
                )
            except (ValueError, RuntimeError) as error:
                raise HTTPException(422, str(error)) from error
            state["source_raw"] = plan.raw
            state["configuration"] = decode_configuration(plan.transfer.dump)
        return {
            "hardware_write": "completed",
            "output_port": result.output_port,
            "packet_count": result.packet_count,
            "byte_count": result.byte_count,
            "sha256": result.sha256,
        }

    @app.get("/kits")
    def kits() -> list[dict[str, object]]:
        return [kit.to_document() for kit in current().kits]

    @app.get("/kits/{kit}")
    def kit(kit: int) -> dict[str, object]:
        config = current()
        if not 0 <= kit < len(config.kits):
            raise HTTPException(404, "unknown kit")
        return config.kits[kit].to_document()

    @app.patch("/kits/{kit}")
    def patch_kit(kit: int, patch: ProgramChangePatch) -> dict[str, object]:
        with lock:
            try:
                updated = state["configuration"].with_program_change(kit, patch.program_change)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            state["configuration"] = updated
        return {
            "staged_only": True,
            "hardware_write": "disabled",
            "kit": updated.kits[kit].to_document(),
        }

    @app.get("/kits/{kit}/inputs/{input_number}")
    def input_(kit: int, input_number: int) -> dict[str, object]:
        config = current()
        if not 0 <= kit < len(config.kits) or not 1 <= input_number <= 10:
            raise HTTPException(404, "unknown kit/input")
        return config.kits[kit].inputs[input_number - 1].to_document()

    @app.patch("/kits/{kit}/inputs/{input_number}")
    def patch_input(kit: int, input_number: int, patch: NotePatch) -> dict[str, Any]:
        if all(value is None for value in patch.model_dump().values()):
            raise HTTPException(422, "supply at least one channel or note")
        with lock:
            config = state["configuration"]
            try:
                updated = config
                if patch.tip_channel is not None or patch.tip_note is not None:
                    updated = updated.with_zone(
                        kit, input_number, "tip", channel=patch.tip_channel, note=patch.tip_note
                    )
                if patch.ring_channel is not None or patch.ring_note is not None:
                    updated = updated.with_zone(
                        kit, input_number, "ring", channel=patch.ring_channel, note=patch.ring_note
                    )
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            state["configuration"] = updated
        return {
            "staged_only": True,
            "hardware_write": "disabled",
            "input": updated.kits[kit].inputs[input_number - 1].to_document(),
        }

    @app.patch("/kits/{kit}/hi-hat")
    def patch_hi_hat(kit: int, patch: HiHatKitPatch) -> dict[str, object]:
        values = {name: value for name, value in patch.model_dump().items() if value is not None}
        if not values:
            raise HTTPException(422, "supply at least one hi-hat setting")
        with lock:
            try:
                updated = state["configuration"].with_hi_hat_kit_settings(kit, **values)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            state["configuration"] = updated
        return {"staged_only": True, "hardware_write": "disabled", "hi_hat": updated.kits[kit].hi_hat.to_document()}

    @app.patch("/global-triggers/{record}")
    def patch_global_trigger(record: int, patch: GlobalTriggerPatch) -> dict[str, object]:
        values = {name: value for name, value in patch.model_dump().items() if value is not None}
        if not values:
            raise HTTPException(422, "supply at least one global trigger setting")
        trigger_type = values.pop("trigger_type", None)
        if trigger_type is not None:
            type_codes = {"PP": 0, "SS": 33}
            try:
                values["trigger_type_raw"] = type_codes[str(trigger_type).upper()]
            except KeyError as error:
                raise HTTPException(422, "trigger_type must be PP or SS") from error
        with lock:
            try:
                updated = state["configuration"].with_global_trigger_settings(record, values)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            state["configuration"] = updated
        item = next(item for item in updated.global_trigger_records if item.index == record)
        return {"staged_only": True, "hardware_write": "disabled", "global_trigger": item.to_document()}

    @app.patch("/global-trigger/input-1/tip")
    def patch_input_1_tip_gain(patch: Input1TipPatch) -> dict[str, object]:
        """Stage controlled-evidence Input 1 Tip fields; never sends MIDI."""
        settings = {name: value for name, value in patch.model_dump().items() if value is not None}
        if not settings:
            raise HTTPException(422, "supply at least one Input 1 Tip setting")
        with lock:
            try:
                updated = state["configuration"].with_input_1_tip_settings(settings)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            state["configuration"] = updated
        return {
            "staged_only": True,
            "hardware_write": "disabled",
            "confirmed_global_trigger": {"input_1_tip": updated.input_1_tip_settings},
        }

    @app.put("/preset")
    def replace_preset(preset: dict[str, object]) -> dict[str, object]:
        """Stage a portable note preset; no MIDI output is opened or used."""
        with lock:
            try:
                state["configuration"] = state["configuration"].with_note_preset(preset)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
        return {"staged_only": True, "hardware_write": "disabled", "preset": current().to_note_preset()}

    @app.put("/configuration-preset")
    def replace_configuration_preset(preset: dict[str, object]) -> dict[str, object]:
        """Stage a proven-field YAML/JSON preset provided as JSON over HTTP."""
        with lock:
            try:
                state["configuration"] = state["configuration"].with_configuration_preset(preset)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
        return {"staged_only": True, "hardware_write": "disabled", "preset": current().to_configuration_preset()}

    @app.post("/role-template")
    def stage_role_template(request: RoleTemplateApply) -> dict[str, object]:
        """Stage GM/SD3 roles through user-supplied input bindings only."""
        with lock:
            try:
                state["configuration"] = apply_role_template(state["configuration"], request.template, request.layout)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
        return {
            "staged_only": True,
            "hardware_write": "disabled",
            "mapping": "role-template + explicit-layout",
            "configuration": current().to_document(),
        }

    return app
