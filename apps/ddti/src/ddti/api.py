"""Optional local FastAPI surface over the read-only DDTi library.

This service only edits an in-memory/offline staging configuration.  It has no
MIDI-output dependency and no endpoint capable of writing to a DDTi.
"""
from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import BaseModel

from .discovery import discover_devices
from .models import DDTiConfiguration, decode_configuration
from .protocol import decode_file
from .transfer import build_transfer_plan


def _configuration(path: Path) -> DDTiConfiguration:
    return decode_configuration(decode_file(path))


class NotePatch(BaseModel):
    """The only editable fields currently validated for offline staging."""

    tip_note: int | None = None
    ring_note: int | None = None


def create_app(dump_path: Path):
    """Create a local API backed by one explicit, already-captured dump."""
    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as error:  # pragma: no cover - optional dependency
        raise RuntimeError("install the 'ddti[api]' extra to run the local API") from error

    state = {"configuration": _configuration(dump_path)}
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
        return {"connected_candidates": len(discover_devices()), "hardware_write": "disabled"}

    @app.get("/configuration")
    def configuration() -> dict[str, object]:
        return current().to_document()

    @app.get("/preset")
    def preset() -> dict[str, object]:
        """Return all confirmed notes as a portable offline preset."""
        return current().to_note_preset()

    @app.get("/transfer/plan")
    def transfer_plan() -> dict[str, object]:
        """Review the staged complete dump; no endpoint sends to hardware."""
        return build_transfer_plan(current().raw).to_document()

    @app.get("/kits")
    def kits() -> list[dict[str, object]]:
        return [kit.to_document() for kit in current().kits]

    @app.get("/kits/{kit}")
    def kit(kit: int) -> dict[str, object]:
        config = current()
        if not 0 <= kit < len(config.kits):
            raise HTTPException(404, "unknown kit")
        return config.kits[kit].to_document()

    @app.get("/kits/{kit}/inputs/{input_number}")
    def input_(kit: int, input_number: int) -> dict[str, object]:
        config = current()
        if not 0 <= kit < len(config.kits) or not 1 <= input_number <= 10:
            raise HTTPException(404, "unknown kit/input")
        return config.kits[kit].inputs[input_number - 1].to_document()

    @app.patch("/kits/{kit}/inputs/{input_number}")
    def patch_input(kit: int, input_number: int, patch: NotePatch) -> dict[str, Any]:
        if patch.tip_note is None and patch.ring_note is None:
            raise HTTPException(422, "supply tip_note and/or ring_note")
        with lock:
            config = state["configuration"]
            try:
                updated = config
                if patch.tip_note is not None:
                    updated = updated.with_note(kit, input_number, "tip", patch.tip_note)
                if patch.ring_note is not None:
                    updated = updated.with_note(kit, input_number, "ring", patch.ring_note)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            state["configuration"] = updated
        return {
            "staged_only": True,
            "hardware_write": "disabled",
            "input": updated.kits[kit].inputs[input_number - 1].to_document(),
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

    return app
