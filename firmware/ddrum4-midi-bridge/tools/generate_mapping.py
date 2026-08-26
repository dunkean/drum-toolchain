#!/usr/bin/env python3
"""Generate include/generated_mapping.h from a ddrum4 hybrid-kit manifest."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

import yaml


POSITION_INDEX = {
    1: {1: 0},
    2: {1: 0, 5: 1},
    4: {1: 0, 3: 1, 5: 2, 7: 3},
    8: {position: position - 1 for position in range(1, 9)},
}


def integer(value, label, minimum, maximum):
    if not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def project_mapping_header(document, output_channel):
    """Lower a ready rig-compiler firmware plan to fixed Arduino tables."""
    if document.get("format") != "ddrum4-firmware-project-mapping-plan/v1":
        raise ValueError("expected ddrum4-firmware-project-mapping-plan/v1")
    if document.get("status") != "ready" or document.get("deployment") != "live" or document.get("hardware_flash") != "ready":
        raise ValueError("firmware project mapping is not a verified live flash plan")
    output_channel = integer(output_channel, "output channel", 1, 16)
    state = document.get("state")
    controls = document.get("logical_control_protocol")
    records = document.get("records")
    native_control_map = document.get("native_control_map", {})
    state_actions_document = document.get("ddrum_state_actions", {})
    if (not isinstance(state, dict) or not isinstance(controls, dict) or not isinstance(records, list)
            or not isinstance(native_control_map, dict) or not isinstance(state_actions_document, dict)):
        raise ValueError("firmware project mapping needs state, logical_control_protocol, native_control_map, and records")
    scenes = state.get("scenes")
    variables = state.get("variables")
    defaults = state.get("defaults")
    if (not isinstance(scenes, list) or not scenes or not all(isinstance(item, str) for item in scenes) or
            not isinstance(variables, list) or len(variables) > 4 or not all(isinstance(item, str) for item in variables) or
            not isinstance(defaults, dict) or defaults.get("scene") not in scenes):
        raise ValueError("firmware project state must declare scenes, at most four VP variables, and a default scene")
    control_values = []
    for variable in variables:
        control = controls.get(variable)
        if not isinstance(control, dict) or control.get("type") != "cc":
            raise ValueError(f"firmware state variable {variable!r} needs a CC logical control")
        control_values.append(integer(control.get("cc"), f"logical control {variable}", 0, 127))
    if len(control_values) != len(set(control_values)):
        raise ValueError("firmware logical VP controls must use distinct CCs")
    control_values.extend([255] * (4 - len(control_values)))
    initial_values = [integer(defaults.get(variable), f"default {variable}", 0, 127) for variable in variables]
    initial_values.extend([0] * (4 - len(initial_values)))
    state_routes = []
    relay_channels = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"record {index} must be an object")
        source, match, renderers = record.get("source"), record.get("match"), record.get("renderers")
        if not isinstance(source, dict) or not isinstance(match, dict) or not isinstance(renderers, dict):
            raise ValueError(f"record {index} is incomplete")
        if match.get("type") != "note":
            raise ValueError(f"record {index}: firmware generation supports only exact note decoders")
        channel = integer(source.get("channel"), f"record {index} source channel", 1, 16)
        note = integer(match.get("note"), f"record {index} source note", 0, 127)
        renderer = renderers.get("ddrum4")
        if not isinstance(renderer, dict):
            raise ValueError(f"record {index}: ddrum4 renderer is required")
        output_note = integer(renderer.get("note"), f"record {index} ddrum4 note", 0, 127)
        scene = record.get("scene")
        if scene not in scenes:
            raise ValueError(f"record {index}: unknown scene")
        predicates = record.get("state_predicates", {})
        if not isinstance(predicates, dict):
            raise ValueError(f"record {index}: state_predicates must be an object")
        values = [255, 255, 255, 255]
        for name, value in predicates.items():
            if name not in variables:
                raise ValueError(f"record {index}: unknown firmware VP predicate {name!r}")
            values[variables.index(name)] = integer(value, f"record {index} predicate {name}", 0, 127)
        state_routes.append((channel, note, scenes.index(scene), *values, output_note))
        relay_channels.add(channel)
    if not state_routes:
        raise ValueError("firmware project mapping has no state routes")
    native_type = {"program_change": "ProgramChange", "cc": "ControlChange", "note": "NoteOn"}
    native_routes = []
    for name, control in sorted(native_control_map.items()):
        if not isinstance(control, dict):
            raise ValueError(f"native control {name!r} must be an object")
        kind = control.get("type")
        if kind not in native_type:
            raise ValueError(f"native control {name!r} has unsupported type")
        target_name = control.get("decode_to")
        if target_name == "scene":
            target = 0
        elif target_name in variables:
            target = variables.index(target_name) + 1
        else:
            raise ValueError(f"native control {name!r} has unknown state target")
        channel = integer(control.get("channel"), f"native control {name} channel", 1, 16)
        address = integer(control.get("program" if kind == "program_change" else "cc" if kind == "cc" else "note"),
                          f"native control {name} address", 0, 127)
        mapped_value = integer(control.get("value"), f"native control {name} value", 0, 127)
        native_routes.append((channel, native_type[kind], address, target, mapped_value))
    if len({route[:3] for route in native_routes}) != len(native_routes):
        raise ValueError("duplicate firmware native control")
    state_actions = []
    for scene, actions in sorted(state_actions_document.items()):
        if scene not in scenes or not isinstance(actions, list):
            raise ValueError("invalid DDrum state action scene")
        for action in actions:
            if not isinstance(action, dict) or action.get("status") == "planned":
                raise ValueError("firmware refuses planned DDrum state actions")
            if action.get("type") != "program_change":
                raise ValueError("firmware supports only reviewed Program Change state actions; SysEx needs streaming approval")
            predicates = action.get("when", {})
            if not isinstance(predicates, dict):
                raise ValueError("state action predicates must be an object")
            values = [255, 255, 255, 255]
            for name, value in predicates.items():
                if name not in variables:
                    raise ValueError(f"unknown state action predicate {name!r}")
                values[variables.index(name)] = integer(value, f"state action predicate {name}", 0, 127)
            state_actions.append((scenes.index(scene), *values, integer(action.get("channel"), "state action channel", 1, 16),
                                  integer(action.get("program"), "state action program", 0, 127)))
    source_hash = document.get("source_sha256")
    if not isinstance(source_hash, str) or not source_hash:
        raise ValueError("firmware project mapping needs source_sha256")
    # Conditional rows precede their scene-local fallback, matching DdrumBridge::findNoteRoute.
    state_routes.sort(key=lambda item: (item[0], item[1], item[2], sum(value != 255 for value in item[3:7]) == 0, item[3:7]))
    lines = [
        "// Generated from rig-compiler firmware-project-mapping.json; do not edit manually.",
        f"// Rig project SHA-256: {source_hash}",
        "#pragma once",
        "#include \"DdrumBridge.h\"",
        "",
        f"constexpr uint8_t DDRUM_OUTPUT_CHANNEL = {output_channel};",
        "const uint8_t RELAY_PROGRAM_CHANNELS[] = {" + ", ".join(str(item) for item in sorted(relay_channels)) + "};",
        "constexpr size_t RELAY_PROGRAM_CHANNEL_COUNT = sizeof(RELAY_PROGRAM_CHANNELS) / sizeof(RELAY_PROGRAM_CHANNELS[0]);",
        "",
        "const NoteRoute NOTE_ROUTES[] = {{0, 0, 0, 1, 127, 1, 127}}; // State routes own every generated note.",
        "constexpr size_t NOTE_ROUTE_COUNT = 0;",
        "",
        "const StateRoute STATE_ROUTES[] PROGMEM = {",
    ]
    lines.extend("  {" + ", ".join(str(value) for value in (*route, 1, 127, 1, 127)) + "}," for route in state_routes)
    lines.extend([
        "};",
        "constexpr size_t STATE_ROUTE_COUNT = sizeof(STATE_ROUTES) / sizeof(STATE_ROUTES[0]);",
        "",
        "const NativeControlRoute NATIVE_CONTROLS[] PROGMEM = {",
    ])
    if native_routes:
        lines.extend(f"  {{{channel}, NativeControlType::{kind}, {address}, {target}, {value}}},"
                     for channel, kind, address, target, value in native_routes)
    else:
        lines.append("  {1, NativeControlType::ProgramChange, 0, 0, 0}, // empty sentinel")
    lines.extend([
        "};",
        f"constexpr size_t NATIVE_CONTROL_COUNT = {len(native_routes)};",
        "",
        "const DdrumStateAction STATE_ACTIONS[] PROGMEM = {",
    ])
    if state_actions:
        lines.extend(f"  {{{scene}, {vp1}, {vp2}, {vp3}, {vp4}, {{MidiEventType::ProgramChange, {channel}, {program}, 0}}}},"
                     for scene, vp1, vp2, vp3, vp4, channel, program in state_actions)
    else:
        lines.append("  {0, 255, 255, 255, 255, {MidiEventType::ProgramChange, 1, 0, 0}}, // empty sentinel")
    lines.extend([
        "};",
        f"constexpr size_t STATE_ACTION_COUNT = {len(state_actions)};",
        "",
        "constexpr LogicalControlConfig LOGICAL_CONTROLS = {" + ", ".join(str(value) for value in control_values) + "};",
        "constexpr LogicalState INITIAL_LOGICAL_STATE = {" + ", ".join(str(value) for value in (scenes.index(defaults["scene"]), *initial_values)) + "};",
        "",
        "// No CC4 policy is emitted until a measured project explicitly models one.",
        "constexpr HihatDirectCc4Config HIHAT_CC4 = {0, 0, 0, 0, 0, 0, 0, false, false};",
        "constexpr bool HIHAT_NOTE_P_SUPPORTED = false;",
        "constexpr bool HIHAT_THREE_ZONE_SUPPORTED = false;",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path)
    parser.add_argument("--project-mapping", type=Path, help="ready firmware-project-mapping.json emitted by rig-compiler")
    parser.add_argument("--output-channel", type=int, help="measured DDrum4 MIDI input channel, 1..16; required with --project-mapping")
    parser.add_argument("--output", type=Path, default=Path("include/generated_mapping.h"))
    args = parser.parse_args()
    try:
        if bool(args.manifest) == bool(args.project_mapping):
            raise ValueError("provide exactly one manifest or --project-mapping")
        if args.project_mapping:
            if args.output_channel is None:
                raise ValueError("--output-channel is required with --project-mapping")
            document = json.loads(args.project_mapping.read_text(encoding="utf-8"))
            output = project_mapping_header(document, args.output_channel)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
            return 0
        manifest_bytes = args.manifest.read_bytes()
        document = yaml.safe_load(manifest_bytes.decode("utf-8"))
        manifest_hash = sha256(manifest_bytes).hexdigest()
        midi = document["midi"]
        sources = midi["sources"]
        out_channel = integer(midi["ddrum_output_channel"], "midi.ddrum_output_channel", 1, 16)
        if not isinstance(sources, dict) or not sources:
            raise ValueError("midi.sources must contain at least one named source")
        source_channels = {}
        for source_name, source in sources.items():
            source_channels[source_name] = integer(source["channel"], f"{source_name} channel", 1, 16)
        hihat = document["hihat"]
        if hihat["mode"] != "direct_cc4":
            raise ValueError("only hihat.mode=direct_cc4 is supported in this firmware version")
        hihat_source = hihat.get("source", "edrumin")
        if hihat_source not in source_channels:
            raise ValueError(f"hihat source {hihat_source!r} is not declared in midi.sources")
        routes = []
        # Support the original hihat-specific schema as well as the project
        # manifest's resolved targets.  A target note is authoritative: it is
        # what ddrum4 will receive after the planned sound was installed.
        if "articulations" in hihat:
            hihat_channel = document["ddrum_channels"]["hihat"]
            note_base = integer(hihat_channel["note_base"], "hihat note_base", 0, 127)
            note_p = integer(hihat_channel["note_p"], "hihat note_p", 1, 8)
            if note_p not in POSITION_INDEX:
                raise ValueError("hihat note_p must be one of 1, 2, 4, 8")
            for name, articulation in hihat["articulations"].items():
                input_note = integer(articulation["input_note"], f"hihat {name} input_note", 0, 127)
                position = integer(articulation["position"], f"hihat {name} position", 1, 8)
                if position not in POSITION_INDEX[note_p]:
                    raise ValueError(f"hihat {name}: position {position} is impossible with Note P={note_p}")
                routes.append((source_channels[hihat_source], input_note, note_base + POSITION_INDEX[note_p][position], 1, 127, 1, 127, f"hihat_{name}"))
        for route in document.get("routes", []):
            # Generic routes deliberately use a fully resolved output note until
            # all ddrum channel layouts are added to the generator.
            source = route["source"]
            if source not in source_channels:
                raise ValueError(f"route source {source!r} is not declared in midi.sources")
            channel = source_channels[source]
            target = route.get("target", route)
            velocity = target.get("velocity", {})
            if not isinstance(velocity, dict):
                raise ValueError("route target.velocity must be a mapping")
            route_name = route.get("id", route.get("identifier", "route"))
            if route.get("sound_id"):
                route_name = f"{route['sound_id']} / {route_name}"
            routes.append((channel, integer(route["input_note"], "route input_note", 0, 127),
                           integer(target["output_note"], "route output_note", 0, 127),
                           integer(velocity.get("input_min", 1), "velocity input_min", 1, 127),
                           integer(velocity.get("input_max", 127), "velocity input_max", 1, 127),
                           integer(velocity.get("output_min", 1), "velocity output_min", 1, 127),
                           integer(velocity.get("output_max", 127), "velocity output_max", 1, 127),
                           route_name))
        if len({(item[0], item[1]) for item in routes}) != len(routes):
            raise ValueError("duplicate source channel/note route")
        if any(item[2] > 127 for item in routes):
            raise ValueError("output note exceeds MIDI range")

        lines = [
            "// Generated by tools/generate_mapping.py; do not edit manually.",
            f"// Routing contract SHA-256: {manifest_hash}",
            "#pragma once",
            "#include \"DdrumBridge.h\"",
            "",
            f"constexpr uint8_t DDRUM_OUTPUT_CHANNEL = {out_channel};",
            "const uint8_t RELAY_PROGRAM_CHANNELS[] = {" + ", ".join(str(channel) for channel in sorted(set(source_channels.values()))) + "};",
            "constexpr size_t RELAY_PROGRAM_CHANNEL_COUNT = sizeof(RELAY_PROGRAM_CHANNELS) / sizeof(RELAY_PROGRAM_CHANNELS[0]);",
            "",
            "const NoteRoute NOTE_ROUTES[] = {",
        ]
        lines.extend(f"  {{{channel}, {source_note}, {target_note}, {input_min}, {input_max}, {output_min}, {output_max}}}, // {name}"
                     for channel, source_note, target_note, input_min, input_max, output_min, output_max, name in routes)
        lines.extend([
            "};",
            "constexpr size_t NOTE_ROUTE_COUNT = sizeof(NOTE_ROUTES) / sizeof(NOTE_ROUTES[0]);",
            "// No measured Scene/VP state routes in this contract. Future generated",
            "// entries must be declared `const StateRoute ... PROGMEM`.",
            "constexpr const StateRoute* STATE_ROUTES = nullptr;",
            "constexpr size_t STATE_ROUTE_COUNT = 0;",
            "constexpr const NativeControlRoute* NATIVE_CONTROLS = nullptr;",
            "constexpr size_t NATIVE_CONTROL_COUNT = 0;",
            "constexpr const DdrumStateAction* STATE_ACTIONS = nullptr;",
            "constexpr size_t STATE_ACTION_COUNT = 0;",
            "",
            "constexpr LogicalControlConfig LOGICAL_CONTROLS = {0, 1, 2, 3};",
            "constexpr LogicalState INITIAL_LOGICAL_STATE = {0, 0, 0, 0, 0};",
            "",
            "constexpr HihatDirectCc4Config HIHAT_CC4 = {",
            f"  {source_channels[hihat_source]}, {integer(hihat['input_cc'], 'input_cc', 0, 127)}, {integer(hihat['output_cc'], 'output_cc', 0, 127)},",
            f"  {integer(hihat['input_closed'], 'input_closed', 0, 127)}, {integer(hihat['input_open'], 'input_open', 0, 127)},",
            f"  {integer(hihat['output_closed'], 'output_closed', 0, 127)}, {integer(hihat['output_open'], 'output_open', 0, 127)},",
            f"  {'true' if hihat.get('invert', False) else 'false'}",
            "};",
            "// Deliberately unsupported until hardware captures validate them.",
            "constexpr bool HIHAT_NOTE_P_SUPPORTED = false;",
            "constexpr bool HIHAT_THREE_ZONE_SUPPORTED = false;",
            "",
        ])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(lines), encoding="utf-8")
    except (KeyError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"mapping generation failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
