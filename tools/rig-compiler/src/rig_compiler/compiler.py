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
    physical_decoder_counts: dict[str, int] = {}
    source_physical_decoder_counts: dict[tuple[str, str], int] = {}
    for decoder in project.source_decoders:
        physical_decoder_counts[decoder.physical] = physical_decoder_counts.get(decoder.physical, 0) + 1
        key = (decoder.source, decoder.physical)
        source_physical_decoder_counts[key] = source_physical_decoder_counts.get(key, 0) + 1
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
                # Keep historical IDs for a single decoder. A physical pad
                # may also be decoded by several modules, in which case its
                # source becomes part of the identity to prevent a collision.
                route_prefix = f"{scene}.{decoder.physical}"
                if physical_decoder_counts[decoder.physical] > 1:
                    route_prefix = f"{scene}.{decoder.source}.{decoder.physical}"
                if source_physical_decoder_counts[(decoder.source, decoder.physical)] > 1:
                    address = (decoder.match.get("cc") if decoder.message_type == "cc" else
                               decoder.match.get("note", decoder.match.get("note_range", "any")))
                    if isinstance(address, list):
                        address = "-".join(str(value) for value in address)
                    route_prefix += f".{decoder.message_type}-{address}"
                records.append({
                    "id": route_prefix if isinstance(source_route, str)
                    else f"{route_prefix}.{suffix}-{index}", "scene": scene,
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


def _firmware_lowering_reason(record: dict[str, Any]) -> str | None:
    """Return why a route cannot be represented by the current Uno generator.

    Keep this intentionally as narrow as ``project_mapping_header``: any
    change here must be accompanied by generator support and a golden test.
    An exact raw Note is the only source decoder that currently becomes a
    generated ``StateRoute``.
    """
    matcher = record["match"].get("type")
    if matcher != "note":
        return f"firmware-project mapping lowers exact Note decoders only (got {matcher!r})"
    return None


def _runtime_expression_reason(record: dict[str, Any]) -> str | None:
    """Return why a source expression cannot be loaded into the PC runtime."""
    matcher = record["match"].get("type")
    if matcher in {"cc", "poly_aftertouch"}:
        return "runtime expression routing is not yet common/correlated with the firmware"
    return None


def _expression_capability_report(document: dict[str, Any], routes: list[dict[str, Any]],
                                  provenance: dict[str, str]) -> dict[str, Any]:
    """Make unsupported expression paths explicit before any target is enabled.

    ``rig-project/v1`` already records raw CC and poly-aftertouch decoders,
    but a common PC/Arduino lowering contract has not been measured.  This
    report is intentionally fail-closed: an expression cannot be hidden by a
    renderer fallback or make a firmware plan look flashable.
    """
    expressions = [record for record in routes if record["match"].get("type") in {"cc", "poly_aftertouch"}]
    non_exact = [record for record in routes if _firmware_lowering_reason(record) is not None]
    rows: list[dict[str, Any]] = []
    for record in expressions:
        kind = record["match"]["type"]
        rows.append({
            "id": record["id"], "source": record["source"]["id"], "physical": record["physical"],
            "logical_sound": record["logical_target"], "raw_match": record["match"], "emit": record["emit"],
            "targets": {
                "arduino_ddrum4": {"status": "unsupported", "reason": _firmware_lowering_reason(record)},
                "sd3": {"status": "unsupported", "reason": _runtime_expression_reason(record)},
                "drumgizmo": {"status": "unsupported", "reason": "declared DrumGizmo renderer map is note-only"},
            },
            "status": "unsupported",
            "kind": kind,
        })
    firmware_rows = [{
        "id": record["id"], "source": record["source"]["id"], "physical": record["physical"],
        "raw_match": record["match"], "status": "unsupported",
        "reason": _firmware_lowering_reason(record),
    } for record in non_exact]
    return {**provenance, "format": "expression-capability-report/v1",
            "status": "ready" if not firmware_rows else "planned", "hardware_io": "disabled",
            "summary": {"declared_expressions": len(rows), "supported_expressions": 0,
                        "firmware_unlowerable_routes": len(firmware_rows)},
            "expressions": rows, "firmware_unlowerable_routes": firmware_rows}


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
    return Compilation(path, digest, document, _artifacts(document, digest, routes, project.ddrum4_bank_facts))


def _artifacts(document: dict[str, Any], digest: str, routes: list[dict[str, Any]],
               bank_facts: Any = None) -> dict[str, Any]:
    provenance = _provenance(digest)
    if document.get("ddti_base_dump"):
        # The input is identified, not parsed, copied, or claimed usable.
        provenance["base_dump"] = document["ddti_base_dump"]
    unresolved = _has_unresolved_values(document)
    expression_report = _expression_capability_report(document, routes, provenance)
    firmware_unlowerable = bool(expression_report["firmware_unlowerable_routes"])
    runtime_expressions_unlowered = bool(expression_report["expressions"])
    deployment = document.get("deployment", "simulation")
    live_ready = deployment == "live" and not unresolved and not firmware_unlowerable
    control_bus = document.get("control_bus")
    logical_control_live = bool(live_ready and isinstance(control_bus, dict)
                                and control_bus.get("status") == "user-confirmed")
    report_status = {
        "runtime-profile": "planned" if unresolved or runtime_expressions_unlowered else "ready", "ddrum4-routing-plan": "planned",
        "ddrum4-routing-contract": "planned", "firmware-project-mapping": "ready" if live_ready else ("planned" if unresolved or firmware_unlowerable else ("simulation-only" if deployment == "simulation" else "planned")),
        "sd3-midimap": "user-confirmed" if not runtime_expressions_unlowered else "planned",
        "drumgizmo-midimap": "planned" if unresolved or runtime_expressions_unlowered else "ready",
        "sd3-megakit-map": "user-confirmed" if not runtime_expressions_unlowered else "planned",
        "ddrum4-bank-plan": "planned", "virtual-kit-map": "planned" if unresolved or firmware_unlowerable or runtime_expressions_unlowered else "ready",
        "expression-capability-report": expression_report["status"],
        "ddti-preset": "planned" if document.get("ddti_base_dump") else "unresolved",
    }
    report = {**provenance, "format": "rig-project-report/v1", "project": document.get("project", "unnamed-rig"),
              "artifacts": [{"name": key, "status": value} for key, value in report_status.items()],
              "route_count": len(routes), "deployment": deployment,
              "unresolved_measurements": unresolved, "hardware_io": "disabled"}
    # Keep the complete validated declarative model in the runtime artifact.
    # ``records`` remains a compatibility/index view, never the sole source of
    # truth: it cannot express state variants, connection-profile policy, or
    # source decoder metadata without loss.
    runtime = {**provenance, "format": "rig-runtime-profile/v1", "status": report_status["runtime-profile"],
               "project": document.get("project", "unnamed-rig"), "deployment": deployment,
               "state": document["state"], "logical_control_protocol": document["logical_control_protocol"],
               "policies": document["policies"], "connection_profiles": document["connection_profiles"],
               "sources": document["sources"], "source_decoders": document["source_decoders"],
               "physical_events": document["physical_events"], "logical_routes": document["logical_routes"],
               "renderers": document["renderers"], "native_control_map": document["native_control_map"],
               "ddrum_state_actions": document.get("ddrum_state_actions", {}),
               "records": routes, "routes": routes,
               "hardware_io": "logical-control-only" if logical_control_live else "disabled"}
    if control_bus is not None:
        runtime["control_bus"] = control_bus
    routing = {**provenance, "format": "ddrum4-routing-plan/v1", "status": "planned", "records": routes, "hardware_write": "disabled"}
    contract = {**provenance, "format": "ddrum4-routing-contract/v1", "status": "planned", "routing_plan": "ddrum4-routing-plan.json", "records": routes}
    firmware = {
        **provenance,
        "format": "ddrum4-firmware-project-mapping-plan/v1",
        "status": report_status["firmware-project-mapping"], "deployment": deployment,
        "state": document["state"],
        "logical_control_protocol": document["logical_control_protocol"],
        "native_control_map": document["native_control_map"],
        "ddrum_state_actions": document.get("ddrum_state_actions", {}),
        "records": routes,
        "hardware_flash": "ready" if live_ready else "disabled",
    }
    def note_map(target: str, renderer: str) -> dict[str, Any]:
        mappings = []
        unsupported_source_expressions = []
        for route in routes:
            runtime_reason = _runtime_expression_reason(route)
            if runtime_reason is not None:
                unsupported_source_expressions.append({
                    "id": route["id"], "raw_match": route["match"], "physical": route["physical"],
                    "reason": runtime_reason,
                })
                continue
            render = route["renderers"][renderer]
            mapping = {"id": route["id"], "note": render["note"], "logical_target": route["logical_target"]}
            if renderer == "drumgizmo":
                mapping.update({"instrument": render["instrument"], "articulation": render["articulation"]})
            mappings.append(mapping)
        return {**provenance, "format": "drum-note-map/v1", "target": target,
                "status": "planned" if unsupported_source_expressions else (report_status["sd3-midimap"] if target == "sd3" else report_status["drumgizmo-midimap"]),
                "source_renderer": renderer, "mappings": mappings,
                "unsupported_source_expressions": unsupported_source_expressions}
    bank = {**provenance, "format": "ddrum4-bank-plan/v1", "status": "planned", "records": routes,
            "hardware_transfer": "disabled"}
    if bank_facts is not None:
        reference = document["ddrum4_bank"]
        bank["bank_reference"] = {
            "manifest": reference["manifest"], "manifest_resolved_path": str(bank_facts.manifest),
            "bank_id": bank_facts.bank_id,
            "sha256": bank_facts.sha256, "midi_channel": bank_facts.midi_channel,
            "playable_notes": list(bank_facts.playable_notes),
            **({"reports": reference["reports"]} if "reports" in reference else {}),
        }
    markdown = _megakit_markdown(digest, routes)
    virtual_kit = _virtual_kit_map(provenance, document, routes, report_status["virtual-kit-map"], bank_facts)
    return {
        "project-report.json": report, "runtime-profile.yaml": runtime, "ddrum4-routing-plan.json": routing,
        "ddrum4-routing-contract.json": contract, "firmware-project-mapping.json": firmware,
        "sd3-midimap.json": note_map("sd3", "sd3"),
        "drumgizmo-midimap.json": note_map("drumgizmo", "drumgizmo"), "sd3-megakit-map.md": markdown,
        "ddrum4-bank-plan.yaml": bank, "virtual-kit-map.json": virtual_kit,
        "expression-capability-report.json": expression_report,
        # This is intentionally a declarative request, never a sysex/dump artifact.
        "ddti-preset.yaml": {**provenance, "format": "ddti-preset/v1", "status": report_status["ddti-preset"],
                                   "reason": "base dump hash recorded; manual staging remains planned" if document.get("ddti_base_dump") else "--base-dump is required; no transferable dump was generated",
                                   "transferable_dump": False},
    }


def _virtual_kit_map(provenance: dict[str, str], document: dict[str, Any], routes: list[dict[str, Any]],
                     status: str, bank_facts: Any = None) -> dict[str, Any]:
    """Emit a renderer-parity artifact from the exact compiled route records.

    It intentionally records one state-qualified source route per row.  This
    avoids hiding a Scene/VP variation behind a prettified single-pad table and
    gives the desktop UI a stable, compiler-owned contract to display.
    """
    bank_sounds: list[dict[str, Any]] = []
    if bank_facts is not None:
        try:
            bank_document = yaml.safe_load(bank_facts.manifest.read_text(encoding="utf-8"))
            sounds = bank_document.get("sounds", []) if isinstance(bank_document, dict) else []
            if isinstance(sounds, list):
                bank_sounds = [item for item in sounds if isinstance(item, dict)]
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            # The domain has already validated the linked bank. The parity
            # artifact remains useful even if optional display metadata cannot
            # be read again during artifact rendering.
            bank_sounds = []
    rows = []
    for route in routes:
        ddrum, sd3, gizmo = (route["renderers"][name] for name in ("ddrum4", "sd3", "drumgizmo"))
        ddrum_target = {"channel": document["ddrum4_output_channel"], "note": ddrum["note"]}
        for slot, sound in enumerate(bank_sounds, start=1):
            base, width = sound.get("note_base"), sound.get("note_p")
            if isinstance(base, int) and isinstance(width, int) and base <= ddrum["note"] < base + width:
                ddrum_target.update({"slot": slot, "sound_id": sound.get("sound_id", sound.get("id")),
                                     "note_p": ddrum["note"] - base + 1})
                break
        matcher = route["match"].get("type")
        firmware_reason = _firmware_lowering_reason(route)
        runtime_reason = _runtime_expression_reason(route)
        if firmware_reason is not None:
            coverage = "unsupported" if matcher in {"cc", "poly_aftertouch"} else "planned"
        elif runtime_reason is not None:
            coverage = "unsupported"
        else:
            coverage = "complete"
        row = {
            "id": route["id"], "scene": route["scene"], "state_predicates": route["state_predicates"],
            "source": route["source"]["id"], "raw_match": route["match"], "physical": route["physical"],
            "logical_sound": route["logical_target"],
            "ddrum4": ddrum_target,
            "sd3": {"channel": sd3.get("channel", 10), "note": sd3["note"]},
            "drumgizmo": {"channel": gizmo.get("channel", 10), "note": gizmo["note"],
                           "instrument": gizmo["instrument"], "articulation": gizmo["articulation"]},
            "coverage": coverage,
        }
        if firmware_reason is not None:
            row["ddrum4_capability"] = {"status": "unsupported", "reason": firmware_reason}
        if runtime_reason is not None:
            row["sd3_capability"] = {"status": "unsupported", "reason": runtime_reason}
            row["drumgizmo_capability"] = {"status": "unsupported", "reason": "declared DrumGizmo renderer map is note-only"}
        rows.append(row)
    return {**provenance, "format": "virtual-kit-map/v1", "status": status,
            "project": document.get("project", "unnamed-rig"), "deployment": document.get("deployment"),
            "state": document["state"], "rows": rows, "hardware_io": "disabled"}


def _megakit_markdown(digest: str, routes: list[dict[str, Any]]) -> str:
    lines = ["# SD3 MegaKit map", "", f"Compiler version: `{COMPILER_VERSION}`", f"Source SHA-256: `{digest}`", "", "| Route | Note | Articulation |", "| --- | ---: | --- |"]
    supported = [route for route in routes if _runtime_expression_reason(route) is None]
    unsupported = [route for route in routes if _runtime_expression_reason(route) is not None]
    lines.extend(f"| {r['id']} | {r['renderers']['sd3']['note']} | {r['logical_target']} |" for r in supported)
    if unsupported:
        lines.extend(["", "## Unsupported source expressions", "",
                      "The following raw expressions are deliberately excluded from the active SD3 note map until a measured common expression-routing contract exists.",
                      "", "| Route | Raw matcher | Reason |", "| --- | --- | --- |"])
        lines.extend(f"| {route['id']} | {route['match'].get('type')} | {_runtime_expression_reason(route)} |"
                     for route in unsupported)
    return "\n".join(lines) + "\n"


def compile_project(path: Path, output: Path, *, replace: bool = False, base_dump: Path | None = None) -> Compilation:
    """Validate then write all offline artifacts to an explicitly named directory."""
    compilation = validate_project(path)
    if base_dump is not None:
        if not base_dump.is_file():
            raise RigCompilerError(f"base dump does not exist: {base_dump}")
        # It is intentionally not parsed or copied: this compiler cannot create a transferable dump.
        from drum_domain.rig_project import load_rig_project
        project = load_rig_project(compilation.source)
        document = {**compilation.document, "ddti_base_dump": {"path": str(base_dump), "sha256": hashlib.sha256(base_dump.read_bytes()).hexdigest()}}
        compilation = Compilation(compilation.source, compilation.source_sha256, document,
                                  _artifacts(document, compilation.source_sha256,
                                             _domain_route_records(project), project.ddrum4_bank_facts))
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
