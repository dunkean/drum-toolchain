"""Safe offline artifact generation for a drum rig project.

The compiler deliberately produces plans and mappings only.  It has no MIDI,
serial, or device dependencies and never emits a transferable DDTi dump.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

COMPILER_VERSION = "rig-compiler/v1"
PROJECT_FORMAT = "rig-project/v1"


class RigCompilerError(ValueError):
    """A rig project is invalid or an unsafe output operation was requested."""


@dataclass(frozen=True)
class Compilation:
    source: Path
    source_sha256: str
    document: dict[str, Any]
    artifacts: dict[str, Any]


def _read(path: Path) -> tuple[dict[str, Any], str]:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise RigCompilerError(f"cannot read rig project {path}: {error}") from error
    try:
        value = yaml.safe_load(content.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise RigCompilerError(f"invalid YAML in {path}: {error}") from error
    if not isinstance(value, dict):
        raise RigCompilerError("rig project root must be a mapping")
    return value, hashlib.sha256(content).hexdigest()


def _items(document: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("routes", "mappings", "events", "articulations"):
        value = document.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    routing = document.get("routing")
    if isinstance(routing, dict) and isinstance(routing.get("routes"), list):
        return [item for item in routing["routes"] if isinstance(item, dict)]
    return []


def _integer(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 127:
        raise RigCompilerError(f"{label} must be a MIDI integer in 0..127")
    return value


def _field(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in item:
            return item[name]
    for nested in ("source", "input", "target", "output", "ddrum4", "midi"):
        value = item.get(nested)
        if isinstance(value, dict):
            for name in names:
                if name in value:
                    return value[name]
    return None


def _route_records(document: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(_items(document), 1):
        identifier = _field(item, "id", "identifier", "name") or f"route-{index}"
        source_channel = _integer(_field(item, "source_channel", "input_channel", "channel"), f"{identifier}.source_channel")
        source_note = _integer(_field(item, "source_note", "input_note", "note"), f"{identifier}.source_note")
        output_channel = _integer(_field(item, "output_channel", "ddrum_channel", "target_channel"), f"{identifier}.output_channel")
        output_note = _integer(_field(item, "output_note", "ddrum_note", "target_note"), f"{identifier}.output_note")
        result.append({
            "id": str(identifier), "instrument": str(_field(item, "instrument", "pad", "role") or ""),
            "articulation": str(_field(item, "articulation", "zone") or identifier),
            "source_channel": source_channel, "source_note": source_note,
            "output_channel": output_channel, "output_note": output_note,
        })
    return result


def _domain_route_records(project: Any) -> list[dict[str, Any]]:
    """Lower every decoder into a declarative runtime record for each scene."""
    from drum_domain.rig_project import logical_route_variants

    records: list[dict[str, Any]] = []
    for scene, mappings in project.logical_routes.items():
        for decoder in project.source_decoders:
            source_route = mappings[decoder.physical]
            variants = logical_route_variants(source_route)
            # RigRuntime selects the first matching route. Conditional routes
            # must precede the mandatory fallback, independently of YAML order.
            ordered = sorted(variants, key=lambda item: (not item.predicates, tuple(sorted(item.predicates.items()))))
            for index, variant in enumerate(ordered):
                suffix = "default" if not variant.predicates else "when-" + "-".join(
                    f"{name}-{value}" for name, value in sorted(variant.predicates.items()))
                sound = variant.logical_target
                records.append({
                    "id": f"{scene}.{decoder.physical}" if isinstance(source_route, str)
                    else f"{scene}.{decoder.physical}.{suffix}-{index}", "scene": scene,
                    "state": {"scene": scene, "defaults": dict(project.defaults)},
                    "state_predicates": dict(variant.predicates),
                    "source": {"id": decoder.source, "endpoint": project.sources[decoder.source].endpoint,
                               "channel": project.sources[decoder.source].channel,
                               "primary": project.sources[decoder.source].primary,
                               "connection_profile": project.sources[decoder.source].connection_profile},
                    "match": dict(decoder.match), "emit": dict(decoder.emit),
                    "physical": decoder.physical, "logical_target": sound,
                    "renderers": {name: dict(renderer[sound]) for name, renderer in project.renderers.items()},
                })
    return records


def _validate(document: dict[str, Any], routes: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    format_ = document.get("format", document.get("schema"))
    if format_ is not None and format_ != PROJECT_FORMAT:
        errors.append(f"unsupported rig project format {format_!r}; expected {PROJECT_FORMAT!r}")
    if not routes:
        errors.append("rig project has no routes/mappings/events")
    ids = [route["id"] for route in routes]
    if len(ids) != len(set(ids)):
        errors.append("duplicate route id")
    # Source-decoder ambiguities and renderer target semantics are validated by
    # drum_domain.  Do not infer a collision merely from equal renderer notes:
    # multiple physical events can intentionally address one target.
    return errors


def _provenance(source_sha256: str) -> dict[str, str]:
    return {"compiler_version": COMPILER_VERSION, "source_format": PROJECT_FORMAT, "source_sha256": source_sha256}


def _has_unresolved_values(value: Any) -> bool:
    """Return whether a project still contains unsafe measured-value placeholders."""
    if isinstance(value, str):
        return "MEASURE_ME" in value
    if isinstance(value, dict):
        return any(_has_unresolved_values(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_unresolved_values(item) for item in value)
    return False


def validate_project(path: Path) -> Compilation:
    """Load and validate a rig project without changing filesystem state."""
    document, digest = _read(path)
    try:
        from drum_domain.rig_project import RigProjectError, load_rig_project
    except ImportError as error:
        raise RigCompilerError("drum_domain.rig_project is required to validate rig-project/v1") from error
    try:
        project = load_rig_project(path)
    except RigProjectError as error:
        raise RigCompilerError(f"rig project domain validation failed: {error}") from error
    document = dict(project.raw)
    routes = _domain_route_records(project)
    errors = _validate(document, routes)
    if errors:
        raise RigCompilerError("rig project validation failed:\n- " + "\n- ".join(errors))
    return Compilation(path, digest, document, _artifacts(document, digest, routes))


def _artifacts(document: dict[str, Any], digest: str, routes: list[dict[str, Any]]) -> dict[str, Any]:
    provenance = _provenance(digest)
    if document.get("ddti_base_dump"):
        # The input is identified, not parsed, copied, or claimed usable.
        provenance["base_dump"] = document["ddti_base_dump"]
    unresolved = _has_unresolved_values(document)
    report_status = {
        "runtime-profile": "planned" if unresolved else "ready", "ddrum4-routing-plan": "planned",
        "ddrum4-routing-contract": "planned", "firmware-project-mapping": "planned" if unresolved else "ready",
        "sd3-midimap": "user-confirmed", "drumgizmo-midimap": "planned" if unresolved else "ready", "sd3-megakit-map": "user-confirmed",
        "ddrum4-bank-plan": "planned", "ddti-preset": "planned" if document.get("ddti_base_dump") else "unresolved",
    }
    report = {**provenance, "format": "rig-project-report/v1", "project": document.get("project", "unnamed-rig"),
              "artifacts": [{"name": key, "status": value} for key, value in report_status.items()],
              "route_count": len(routes), "unresolved_measurements": unresolved, "hardware_io": "disabled"}
    # Keep the complete validated declarative model in the runtime artifact.
    # ``records`` remains a compatibility/index view, never the sole source of
    # truth: it cannot express state variants, connection-profile policy, or
    # source decoder metadata without loss.
    runtime = {**provenance, "format": "rig-runtime-profile/v1", "status": report_status["runtime-profile"],
               "project": document.get("project", "unnamed-rig"),
               "state": document["state"], "logical_control_protocol": document["logical_control_protocol"],
               "policies": document["policies"], "connection_profiles": document["connection_profiles"],
               "sources": document["sources"], "source_decoders": document["source_decoders"],
               "physical_events": document["physical_events"], "logical_routes": document["logical_routes"],
               "renderers": document["renderers"], "native_control_map": document["native_control_map"],
               "records": routes, "routes": routes, "hardware_io": "disabled"}
    routing = {**provenance, "format": "ddrum4-routing-plan/v1", "status": "planned", "records": routes, "hardware_write": "disabled"}
    contract = {**provenance, "format": "ddrum4-routing-contract/v1", "status": "planned", "routing_plan": "ddrum4-routing-plan.json", "records": routes}
    firmware = {
        **provenance,
        "format": "ddrum4-firmware-project-mapping-plan/v1",
        "status": report_status["firmware-project-mapping"],
        "state": document["state"],
        "logical_control_protocol": document["logical_control_protocol"],
        "native_control_map": document["native_control_map"],
        "records": routes,
        "hardware_flash": "disabled",
    }
    def note_map(target: str, renderer: str) -> dict[str, Any]:
        mappings = []
        for route in routes:
            render = route["renderers"][renderer]
            mapping = {"id": route["id"], "note": render["note"], "logical_target": route["logical_target"]}
            if renderer == "drumgizmo":
                mapping.update({"instrument": render["instrument"], "articulation": render["articulation"]})
            mappings.append(mapping)
        return {**provenance, "format": "drum-note-map/v1", "target": target,
                "status": report_status["sd3-midimap"] if target == "sd3" else report_status["drumgizmo-midimap"],
                "source_renderer": renderer, "mappings": mappings}
    bank = {**provenance, "format": "ddrum4-bank-plan/v1", "status": "planned", "records": routes, "hardware_transfer": "disabled"}
    markdown = _megakit_markdown(digest, routes)
    return {
        "project-report.json": report, "runtime-profile.yaml": runtime, "ddrum4-routing-plan.json": routing,
        "ddrum4-routing-contract.json": contract, "firmware-project-mapping.json": firmware,
        "sd3-midimap.json": note_map("sd3", "sd3"),
        "drumgizmo-midimap.json": note_map("drumgizmo", "drumgizmo"), "sd3-megakit-map.md": markdown,
        "ddrum4-bank-plan.yaml": bank,
        # This is intentionally a declarative request, never a sysex/dump artifact.
        "ddti-preset.yaml": {**provenance, "format": "ddti-preset/v1", "status": report_status["ddti-preset"],
                                   "reason": "base dump hash recorded; manual staging remains planned" if document.get("ddti_base_dump") else "--base-dump is required; no transferable dump was generated",
                                   "transferable_dump": False},
    }


def _megakit_markdown(digest: str, routes: list[dict[str, Any]]) -> str:
    lines = ["# SD3 MegaKit map", "", f"Compiler version: `{COMPILER_VERSION}`", f"Source SHA-256: `{digest}`", "", "| Route | Note | Articulation |", "| --- | ---: | --- |"]
    lines.extend(f"| {r['id']} | {r['renderers']['sd3']['note']} | {r['logical_target']} |" for r in routes)
    return "\n".join(lines) + "\n"


def compile_project(path: Path, output: Path, *, replace: bool = False, base_dump: Path | None = None) -> Compilation:
    """Validate then write all offline artifacts to an explicitly named directory."""
    compilation = validate_project(path)
    if base_dump is not None:
        if not base_dump.is_file():
            raise RigCompilerError(f"base dump does not exist: {base_dump}")
        # It is intentionally not parsed or copied: this compiler cannot create a transferable dump.
        from drum_domain.rig_project import load_rig_project
        document = {**compilation.document, "ddti_base_dump": {"path": str(base_dump), "sha256": hashlib.sha256(base_dump.read_bytes()).hexdigest()}}
        compilation = Compilation(compilation.source, compilation.source_sha256, document,
                                  _artifacts(document, compilation.source_sha256,
                                             _domain_route_records(load_rig_project(compilation.source))))
    if output.exists() and not output.is_dir():
        raise RigCompilerError(f"output must be a directory: {output}")
    existing = [output / name for name in compilation.artifacts if (output / name).exists()]
    if existing and not replace:
        raise FileExistsError("refusing to replace generated artifacts without --replace: " + ", ".join(str(p) for p in existing))
    output.mkdir(parents=True, exist_ok=True)
    for name, artifact in compilation.artifacts.items():
        target = output / name
        if isinstance(artifact, str):
            target.write_text(artifact, encoding="utf-8", newline="\n")
        elif name.endswith(".yaml"):
            target.write_text(yaml.safe_dump(artifact, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
        else:
            target.write_text(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return compilation
