#!/usr/bin/env python3
"""Reject hardware upload unless the repository flash gate issued a short permit."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path

Import("env")  # type: ignore[name-defined]  # PlatformIO/SCons injects this.


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _guard(*_args, **_kwargs) -> None:
    permit_name = os.environ.get("DDRUM_REVIEWED_UPLOAD_PERMIT")
    if not permit_name:
        raise RuntimeError(
            "Hardware upload is gated; use scripts/flash-ddrum4-bridge.ps1 with a ready live mapping and module receipts"
        )
    permit_path = Path(permit_name).resolve()
    document = json.loads(permit_path.read_text(encoding="utf-8"))
    if document.get("kind") != "ddrum-reviewed-upload-permit/v1" or document.get("status") != "authorized":
        raise RuntimeError("invalid reviewed upload permit")
    expires = datetime.fromisoformat(document["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) >= expires:
        raise RuntimeError("reviewed upload permit has expired")
    mapping = Path(document["mapping_path"]).resolve()
    header = Path(document["header_path"]).resolve()
    if _digest(mapping) != document.get("mapping_sha256"):
        raise RuntimeError("live firmware mapping changed after the flash permit was issued")
    if _digest(header) != document.get("header_sha256"):
        raise RuntimeError("generated firmware header changed after the flash permit was issued")


env.AddPreAction("upload", _guard)  # type: ignore[name-defined]
