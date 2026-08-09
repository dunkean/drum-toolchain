"""Composable setup references and deterministic local-path resolution."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


_REQUIRED = ("physical_kit", "wiring", "target", "bank")


@dataclass(frozen=True)
class SetupProfile:
    path: Path
    physical_kit: Path
    wiring: Path
    target: Path
    bank: Path
    capture: Path | None = None

    def inputs(self) -> tuple[Path, ...]:
        return tuple(item for item in (self.physical_kit, self.wiring, self.target, self.bank, self.capture) if item is not None)


def _resolve(base: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"setup.{label} must be a non-empty relative path")
    path = (base / value).resolve()
    if not path.is_file():
        raise ValueError(f"setup.{label} does not exist: {path}")
    return path


def load_setup(path: Path) -> SetupProfile:
    document: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("setup"), dict):
        raise ValueError("setup profile requires a setup mapping")
    setup = document["setup"]
    for field in _REQUIRED:
        if field not in setup:
            raise ValueError(f"setup.{field} is required")
    base = path.parent
    capture = _resolve(base, setup["capture"], "capture") if "capture" in setup else None
    return SetupProfile(
        path=path.resolve(),
        physical_kit=_resolve(base, setup["physical_kit"], "physical_kit"),
        wiring=_resolve(base, setup["wiring"], "wiring"),
        target=_resolve(base, setup["target"], "target"),
        bank=_resolve(base, setup["bank"], "bank"),
        capture=capture,
    )
