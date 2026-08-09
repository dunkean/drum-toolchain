"""MIDI discovery and trace inspection. No command sends MIDI events."""
from __future__ import annotations

import argparse
from pathlib import Path
import time

from .ports import resolve_unique_port
from .traces import MidiTrace


def _port_names(direction: str) -> list[str]:
    try:
        import mido
    except ImportError as error:  # pragma: no cover - depends on optional runtime package
        raise RuntimeError("mido is required to list live MIDI ports") from error
    return mido.get_input_names() if direction == "input" else mido.get_output_names()


def _mido():
    try:
        import mido
    except ImportError as error:  # pragma: no cover - depends on optional runtime package
        raise RuntimeError("mido is required for live MIDI operations") from error
    return mido


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="midi-lab", description="Safely discover MIDI ports and inspect saved traces.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list", help="list currently visible MIDI ports")
    list_parser.add_argument("--direction", choices=("input", "output"), default="input")
    match = subparsers.add_parser("match", help="resolve a unique port name from supplied candidates")
    match.add_argument("query")
    match.add_argument("names", nargs="+")
    info = subparsers.add_parser("trace-info", help="inspect a JSON Lines trace")
    info.add_argument("trace", type=Path)
    record = subparsers.add_parser("record", help="record a bounded MIDI trace from one explicit input")
    record.add_argument("--input", required=True, help="unique MIDI input name")
    record.add_argument("--seconds", required=True, type=float)
    record.add_argument("--output", required=True, type=Path)
    replay = subparsers.add_parser("replay", help="replay a trace only with an explicit send confirmation")
    replay.add_argument("trace", type=Path)
    replay.add_argument("--output", required=True, help="unique MIDI output name")
    replay.add_argument("--send", action="store_true", help="required: actually send messages to the output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "list":
        print("\n".join(_port_names(args.direction)))
    elif args.command == "match":
        print(resolve_unique_port(args.names, args.query))
    elif args.command == "trace-info":
        trace = MidiTrace.read(args.trace)
        print(f"source={trace.source} events={len(trace.events)}")
    elif args.command == "record":
        if args.seconds <= 0:
            raise ValueError("--seconds must be positive")
        mido = _mido()
        name = resolve_unique_port(mido.get_input_names(), args.input)
        started = time.monotonic()
        events = []
        with mido.open_input(name) as input_port:
            while time.monotonic() - started < args.seconds:
                for message in input_port.iter_pending():
                    timestamp = int((time.monotonic() - started) * 1000)
                    events.append(TraceEvent(timestamp, message.type, getattr(message, "channel", None) + 1 if hasattr(message, "channel") else None, getattr(message, "note", getattr(message, "control", None)), getattr(message, "velocity", getattr(message, "value", None))))
                time.sleep(0.001)
        MidiTrace(name, tuple(events)).write(args.output)
        print(f"recorded {len(events)} events to {args.output}")
    else:
        if not args.send:
            raise ValueError("replay is a MIDI write; pass --send after checking the output name")
        mido = _mido()
        name = resolve_unique_port(mido.get_output_names(), args.output)
        trace = MidiTrace.read(args.trace)
        previous = 0
        with mido.open_output(name) as output_port:
            for event in trace.events:
                time.sleep(max(0, event.timestamp_ms - previous) / 1000)
                previous = event.timestamp_ms
                values = {"channel": event.channel - 1} if event.channel is not None else {}
                if event.data1 is not None:
                    if event.message_type in ("note_on", "note_off", "polytouch"):
                        values["note"] = event.data1
                    elif event.message_type == "control_change":
                        values["control"] = event.data1
                if event.data2 is not None:
                    if event.message_type in ("note_on", "note_off"):
                        values["velocity"] = event.data2
                    elif event.message_type == "control_change":
                        values["value"] = event.data2
                output_port.send(mido.Message(event.message_type, **values))
        print(f"replayed {len(trace.events)} events to {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
