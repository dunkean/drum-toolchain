"""Explicit, process-owned Linux sessions for the DrumGizmo renderer."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
from typing import Any, Callable, Sequence
import xml.etree.ElementTree as ElementTree


class LiveSessionError(RuntimeError):
    """A declared live session cannot be started or safely stopped."""


@dataclass(frozen=True)
class JackConnection:
    source: str
    destination: str


@dataclass(frozen=True)
class DrumGizmoSession:
    converter: tuple[str, ...]
    converter_path: Path
    runtime_profile: Path
    midi_bridge: tuple[str, ...]
    midi_bridge_path: Path
    drumgizmo: tuple[str, ...]
    drumgizmo_path: Path
    connections: tuple[JackConnection, ...]


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LiveSessionError(f"{name} must be an object")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise LiveSessionError(f"{name} must be a non-empty string")
    return value


def _arguments(value: object, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LiveSessionError(f"{name} must be a list of strings")
    return tuple(value)


def _executable(value: object, name: str) -> Path:
    command = _string(value, name)
    candidate = Path(command)
    if candidate.parent != Path("."):
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise LiveSessionError(f"{name} is not an executable file: {candidate}")
        return candidate.resolve()
    found = shutil.which(command)
    if found is None:
        raise LiveSessionError(f"{name} is not available on PATH: {command}")
    return Path(found).resolve()


def _file(value: object, name: str) -> Path:
    path = Path(_string(value, name)).expanduser()
    if not path.is_file():
        raise LiveSessionError(f"{name} is missing: {path}")
    return path.resolve()


def load_drumgizmo_session(path: Path) -> DrumGizmoSession:
    """Parse a narrow JSON session contract without launching anything."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LiveSessionError(f"cannot read live session {path}: {error}") from error
    root = _mapping(document, "session")
    if root.get("schema_version") != 1 or root.get("renderer") != "drumgizmo":
        raise LiveSessionError("session must declare schema_version 1 and renderer drumgizmo")
    converter = _mapping(root.get("converter"), "converter")
    runtime = _mapping(root.get("runtime_profile"), "runtime_profile")
    midi_bridge = _mapping(root.get("midi_bridge"), "midi_bridge")
    drumgizmo = _mapping(root.get("drumgizmo"), "drumgizmo")
    converter_path = _executable(converter.get("path"), "converter.path")
    runtime_profile = _file(runtime.get("path"), "runtime_profile.path")
    midi_bridge_path = _executable(midi_bridge.get("path", "a2jmidid"), "midi_bridge.path")
    drumgizmo_path = _executable(drumgizmo.get("path", "drumgizmo"), "drumgizmo.path")
    kit_directory = Path(_string(drumgizmo.get("kit_directory"), "drumgizmo.kit_directory")).expanduser()
    drumkit = kit_directory / "drumkit.xml"
    midimap = kit_directory / "midimap.xml"
    for document_path in (drumkit, midimap):
        if not document_path.is_file():
            raise LiveSessionError(f"DrumGizmo kit document is missing: {document_path}")
        try:
            ElementTree.parse(document_path)
        except ElementTree.ParseError as error:
            raise LiveSessionError(f"invalid DrumGizmo XML: {document_path}") from error
    input_engine = _string(drumgizmo.get("input_engine", "jackmidi"), "drumgizmo.input_engine")
    output_engine = _string(drumgizmo.get("output_engine", "jackaudio"), "drumgizmo.output_engine")
    if input_engine != "jackmidi" or output_engine != "jackaudio":
        raise LiveSessionError("Linux live sessions require DrumGizmo jackmidi input and jackaudio output")
    connections_value = root.get("jack_connections", [])
    if not isinstance(connections_value, list):
        raise LiveSessionError("jack_connections must be a list")
    connections = tuple(JackConnection(_string(_mapping(item, "jack connection").get("source"), "jack connection.source"),
                                       _string(_mapping(item, "jack connection").get("destination"), "jack connection.destination"))
                        for item in connections_value)
    if not connections:
        raise LiveSessionError("at least one explicit jack_connections entry is required")
    if len({(item.source, item.destination) for item in connections}) != len(connections):
        raise LiveSessionError("jack_connections must be unique")
    dg_command = (str(drumgizmo_path), "-i", input_engine, "-I", f"midimap={midimap.resolve()}",
                  "-o", output_engine, *_arguments(drumgizmo.get("arguments"), "drumgizmo.arguments"),
                  str(drumkit.resolve()))
    bridge_command = (str(midi_bridge_path), *_arguments(midi_bridge.get("arguments", ["-e"]), "midi_bridge.arguments"))
    return DrumGizmoSession((str(converter_path), *_arguments(converter.get("arguments"), "converter.arguments")),
                            converter_path, runtime_profile, bridge_command, midi_bridge_path,
                            dg_command, drumgizmo_path, connections)


def _probe_drumgizmo(session: DrumGizmoSession, runner: Callable[..., subprocess.CompletedProcess[str]]) -> str:
    result = runner((str(session.drumgizmo_path), "--version"), capture_output=True, text=True,
                    check=False, timeout=10)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise LiveSessionError(f"DrumGizmo version probe failed: {detail}")
    return result.stdout.strip()


def _terminate(processes: Sequence[subprocess.Popen[str]]) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in reversed(processes):
        if process.poll() is None:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def _connect_jack(connection: JackConnection, runner: Callable[..., subprocess.CompletedProcess[str]],
                  sleep: Callable[[float], None]) -> None:
    last: subprocess.CompletedProcess[str] | None = None
    # JACK clients register asynchronously. Retry only this declared edge and
    # keep the wait short enough that an operator sees a failed port promptly.
    for _ in range(20):
        result = runner(("jack_connect", connection.source, connection.destination), capture_output=True,
                        text=True, check=False, timeout=10)
        if result.returncode == 0:
            return
        last = result
        sleep(0.1)
    assert last is not None
    detail = last.stderr.strip() or last.stdout.strip() or f"exit {last.returncode}"
    raise LiveSessionError(f"JACK connection {connection.source!r} -> {connection.destination!r} failed: {detail}")


def preview_drumgizmo_session(config_path: Path, state_path: Path) -> dict[str, Any]:
    """Validate and describe a session without starting processes or JACK routes."""
    if state_path.exists():
        raise LiveSessionError(f"live session state already exists: {state_path}")
    session = load_drumgizmo_session(config_path)
    return {
        "kind": "live-session-preview",
        "schema_version": 1,
        "renderer": "drumgizmo",
        "state_file": str(state_path.resolve()),
        "commands": {
            "a2jmidid": list(session.midi_bridge),
            "drumgizmo": list(session.drumgizmo),
            "converter": list(session.converter),
        },
        "converter_environment": {
            "DDRUM4_RUNTIME_PROFILE": str(session.runtime_profile),
            "DDRUM4_RENDERER_TARGET": "drumgizmo",
        },
        "jack_connections": [
            {"source": item.source, "destination": item.destination} for item in session.connections
        ],
        "hardware_io": "disabled",
    }


def start_drumgizmo_session(config_path: Path, state_path: Path, *, confirm_start: bool,
                            runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
                            popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
                            sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Launch an explicit DrumGizmo session and write only its owned PIDs."""
    if not confirm_start:
        raise LiveSessionError("starting a live session is explicit; pass --confirm-start after preflight")
    if state_path.exists():
        raise LiveSessionError(f"live session state already exists: {state_path}")
    session = load_drumgizmo_session(config_path)
    version = _probe_drumgizmo(session, runner)
    started: list[subprocess.Popen[str]] = []
    try:
        midi_bridge = popen(session.midi_bridge)
        started.append(midi_bridge)
        if midi_bridge.poll() is not None:
            raise LiveSessionError("a2jmidid exited before JACK connections were created")
        drumgizmo = popen(session.drumgizmo)
        started.append(drumgizmo)
        if drumgizmo.poll() is not None:
            raise LiveSessionError("DrumGizmo exited before JACK connections were created")
        converter_env = {**os.environ, "DDRUM4_RUNTIME_PROFILE": str(session.runtime_profile),
                         "DDRUM4_RENDERER_TARGET": "drumgizmo"}
        converter = popen(session.converter, env=converter_env)
        started.append(converter)
        if converter.poll() is not None:
            raise LiveSessionError("Converter exited before JACK connections were created")
        for connection in session.connections:
            _connect_jack(connection, runner, sleep)
        state = {
            "kind": "live-session-state", "schema_version": 1, "renderer": "drumgizmo",
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "config": str(config_path.resolve()), "drumgizmo_version": version,
            "processes": [
                {"name": "a2jmidid", "pid": midi_bridge.pid, "path": str(session.midi_bridge_path)},
                {"name": "drumgizmo", "pid": drumgizmo.pid, "path": str(session.drumgizmo_path)},
                {"name": "converter", "pid": converter.pid, "path": str(session.converter_path)},
            ],
            "jack_connections": [{"source": item.source, "destination": item.destination} for item in session.connections],
            "note": "Only recorded PIDs with a matching /proc executable may be stopped.",
        }
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except BaseException:
        _terminate(started)
        raise
    return state


def stop_drumgizmo_session(state_path: Path, *, dry_run: bool = False) -> tuple[int, ...]:
    """Stop only processes recorded by this launcher after checking /proc identity."""
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LiveSessionError(f"cannot read live session state {state_path}: {error}") from error
    if not isinstance(state, dict) or state.get("kind") != "live-session-state" or state.get("renderer") != "drumgizmo":
        raise LiveSessionError("refusing an unrecognised DrumGizmo session state")
    stopped: list[int] = []
    for entry in state.get("processes", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("pid"), int) or not isinstance(entry.get("path"), str):
            raise LiveSessionError("invalid process record in live session state")
        pid, expected = entry["pid"], Path(entry["path"]).resolve()
        proc_path = Path(f"/proc/{pid}/exe")
        if not proc_path.exists():
            continue
        try:
            actual = proc_path.resolve()
        except OSError as error:
            raise LiveSessionError(f"cannot verify PID {pid}: {error}") from error
        if actual != expected:
            raise LiveSessionError(f"PID {pid} no longer matches recorded executable {expected}; refusing to stop it")
        if not dry_run:
            os.kill(pid, signal.SIGTERM)
        stopped.append(pid)
    if not dry_run:
        state_path.unlink()
    return tuple(stopped)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch or stop an explicitly declared Linux DrumGizmo live session.")
    commands = parser.add_subparsers(dest="action", required=True)
    start = commands.add_parser("start")
    start.add_argument("--config", required=True, type=Path)
    start.add_argument("--state-file", required=True, type=Path)
    start.add_argument("--confirm-start", action="store_true")
    start.add_argument("--dry-run", action="store_true")
    stop = commands.add_parser("stop")
    stop.add_argument("--state-file", required=True, type=Path)
    stop.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "start":
        if args.dry_run:
            print(json.dumps(preview_drumgizmo_session(args.config, args.state_file), indent=2, sort_keys=True))
        else:
            state = start_drumgizmo_session(args.config, args.state_file, confirm_start=args.confirm_start)
            print(f"started DrumGizmo session ({state['drumgizmo_version']}); state: {args.state_file}")
    else:
        stopped = stop_drumgizmo_session(args.state_file, dry_run=args.dry_run)
        print(f"{'would stop' if args.dry_run else 'stopped'} {len(stopped)} owned process(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
