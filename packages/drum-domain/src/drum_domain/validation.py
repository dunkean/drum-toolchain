"""JSON Schema validation of versioned toolchain contracts and profiles."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml


def validate_document(document: object, schema_path: Path) -> None:
    """Raise a concise ValueError on the first schema violation."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.Draft202012Validator(schema).validate(document)
    except jsonschema.ValidationError as error:
        location = ".".join(str(item) for item in error.absolute_path) or "root"
        raise ValueError(f"{schema_path.name}: {location}: {error.message}") from error


def validate_yaml(path: Path, schema_path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    validate_document(document, schema_path)
    if not isinstance(document, dict):  # schema currently prevents this; keeps static type precise.
        raise ValueError("validated profile is not an object")
    return document
