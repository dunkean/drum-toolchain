"""Portable, human-editable offline DDTi preset documents.

YAML is the preferred representation so mappings can live alongside the rest
of the drum-toolchain profiles. JSON remains accepted for existing note preset
files and automation. These helpers only read and write local files; they have
no MIDI dependency.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path


def load_document(path: Path) -> dict[str, object]:
    """Read one JSON or YAML mapping document with a useful validation error."""
    try:
        if path.suffix.casefold() in {".yaml", ".yml"}:
            import yaml

            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        else:
            document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read preset {path}: {error}") from error
    except Exception as error:
        # PyYAML's exception hierarchy is optional at module import time.
        if error.__class__.__module__.startswith("yaml"):
            raise ValueError(f"cannot read preset {path}: {error}") from error
        raise
    if not isinstance(document, Mapping):
        raise ValueError("preset root must be an object")
    return dict(document)


def write_document(path: Path, document: Mapping[str, object]) -> None:
    """Write a new preset in the explicitly requested JSON or YAML format."""
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {path}")
    if path.suffix.casefold() in {".yaml", ".yml"}:
        import yaml

        text = yaml.safe_dump(dict(document), allow_unicode=True, sort_keys=False)
    else:
        text = json.dumps(document, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
