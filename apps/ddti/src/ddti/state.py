"""Persistent last-known DDTi state for workflows without repeated panel dumps."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .models import DDTiConfiguration, decode_configuration
from .protocol import decode_dump
from .transfer import build_transfer_plan


def default_state_directory() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return base / "DDTi Editor"


@dataclass(frozen=True)
class DDTiStateStore:
    directory: Path

    @classmethod
    def default(cls) -> "DDTiStateStore":
        return cls(default_state_directory())

    @property
    def syx_path(self) -> Path:
        return self.directory / "last-known-state.syx"

    @property
    def metadata_path(self) -> Path:
        return self.directory / "last-known-state.json"

    def exists(self) -> bool:
        return self.syx_path.exists()

    def load(self) -> DDTiConfiguration:
        raw = self.syx_path.read_bytes()
        build_transfer_plan(raw)
        return decode_configuration(decode_dump(raw))

    def save(self, raw: bytes, *, source: str, reason: str) -> Path:
        plan = build_transfer_plan(raw)
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary_syx = self.syx_path.with_suffix(".syx.tmp")
        temporary_json = self.metadata_path.with_suffix(".json.tmp")
        temporary_syx.write_bytes(plan.raw)
        temporary_json.write_text(
            json.dumps(
                {
                    "format": "ddti-last-known-state/v1",
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                    "source": source,
                    "reason": reason,
                    "sha256": plan.sha256,
                    "byte_count": len(plan.raw),
                    "packet_count": len(plan.dump.packets),
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        temporary_syx.replace(self.syx_path)
        temporary_json.replace(self.metadata_path)
        return self.syx_path
