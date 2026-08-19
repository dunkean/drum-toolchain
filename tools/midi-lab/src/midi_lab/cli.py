"""MIDI discovery, trace inspection, and explicitly confirmed test relays."""
from __future__ import annotations

import argparse
from pathlib import Path
import time

from .ports import resolve_unique_port
from .traces import MidiTrace, TraceEvent
from .ddrum4_programs import decode_ddrum4_program


def _trace_event(message, timestamp_ms: int) -> TraceEvent:
    data1 = None
    data2 = None
    if message.type in ("note_on", "note_off", "polytouch"):
        data1 = message.note
    elif message.type == "control_change":
        data1 = message.control
    elif message.type == "program_change":
        data1 = message.program
    if message.type in ("note_on", "note_off"):
        data2 = message.velocity
    elif message.type in ("control_change", "polytouch"):
        data2 = message.value
    return TraceEvent(
        timestamp_ms,
        message.type,
        message.channel + 1 if hasattr(message, "channel") else None,
        data1,
        data2,
    )


def _message_from_trace(mido, event: TraceEvent):
    values = {"channel": event.channel - 1} if event.channel is not None else {}
    if event.data1 is not None:
        if event.message_type in ("note_on", "note_off", "polytouch"):
            values["note"] = event.data1
        elif event.message_type == "control_change":
            values["control"] = event.data1
        elif event.message_type == "program_change":
            values["program"] = event.data1
    if event.data2 is not None:
        if event.message_type in ("note_on", "note_off"):
            values["velocity"] = event.data2
        elif event.message_type in ("control_change", "polytouch"):
            values["value"] = event.data2
    return mido.Message(event.message_type, **values)


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
    parser = argparse.ArgumentParser(prog="midi-lab", description="Safely discover MIDI ports, inspect traces, and run bounded confirmed relays.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list", help="list currently visible MIDI ports")
    list_parser.add_argument("--direction", choices=("input", "output"), default="input")
    match = subparsers.add_parser("match", help="resolve a unique port name from supplied candidates")
    match.add_argument("query")
    match.add_argument("names", nargs="+")
    info = subparsers.add_parser("trace-info", help="inspect a JSON Lines trace")
    info.add_argument("trace", type=Path)
    describe = subparsers.add_parser("describe-ddrum4-program", help="decode one DDrum4 kit/palette Program Change")
    describe.add_argument("program", type=int)
    send_program = subparsers.add_parser("send-ddrum4-program", help="send exactly one confirmed DDrum4 Program Change")
    send_program.add_argument("--output", required=True, help="unique MIDI output connected to DDrum4 MIDI IN")
    send_program.add_argument("--channel", required=True, type=int, help="DDrum4 MIDI channel, 1..16")
    send_program.add_argument("--program", required=True, type=int, help="DDrum4 Program Change, 0..123")
    send_program.add_argument("--send", action="store_true", help="required: actually send the Program Change")
    record = subparsers.add_parser("record", help="record a bounded MIDI trace from one explicit input")
    record.add_argument("--input", required=True, help="unique MIDI input name")
    record.add_argument("--seconds", required=True, type=float)
    record.add_argument("--output", required=True, type=Path)
    replay = subparsers.add_parser("replay", help="replay a trace only with an explicit send confirmation")
    replay.add_argument("trace", type=Path)
    replay.add_argument("--output", required=True, help="unique MIDI output name")
    replay.add_argument("--send", action="store_true", help="required: actually send messages to the output")
    bridge = subparsers.add_parser("bridge", help="run a bounded two-leg live MIDI relay")
    bridge.add_argument("--input-a", required=True, help="first explicit MIDI input")
    bridge.add_argument("--output-a", required=True, help="destination for input A")
    bridge.add_argument("--input-b", required=True, help="second explicit MIDI input")
    bridge.add_argument("--output-b", required=True, help="destination for input B")
    bridge.add_argument("--seconds", required=True, type=float, help="positive bounded relay duration")
    bridge.add_argument("--send", action="store_true", help="required: actually send MIDI to both outputs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "list":
        print("\n".join(_port_names(args.direction)))
    elif args.command == "match":
        print(resolve_unique_port(args.names, args.query))
    elif args.command == "trace-info":
        trace = MidiTrace.read(args.trace)
        programs = [decode_ddrum4_program(event.data1).label for event in trace.events
                    if event.message_type == "program_change" and event.data1 is not None]
        suffix = f" programs={programs}" if programs else ""
        print(f"source={trace.source} events={len(trace.events)}{suffix}")
    elif args.command == "describe-ddrum4-program":
        decoded = decode_ddrum4_program(args.program)
        print(f"PC {decoded.program}: {decoded.label}")
    elif args.command == "send-ddrum4-program":
        if not args.send:
            raise ValueError("sending a Program Change is a MIDI write; pass --send after checking the output")
        if not 1 <= args.channel <= 16 or not 0 <= args.program <= 123:
            raise ValueError("DDrum4 channel must be 1..16 and program must be 0..123")
        mido = _mido()
        name = resolve_unique_port(mido.get_output_names(), args.output)
        with mido.open_output(name) as output_port:
            output_port.send(mido.Message("program_change", channel=args.channel - 1, program=args.program))
        print(f"sent PC {args.program} ({decode_ddrum4_program(args.program).label}) to {name} on channel {args.channel}")
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
                    events.append(_trace_event(message, timestamp))
                time.sleep(0.001)
        MidiTrace(name, tuple(events)).write(args.output)
        print(f"recorded {len(events)} events to {args.output}")
    elif args.command == "replay":
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
                output_port.send(_message_from_trace(mido, event))
        print(f"replayed {len(trace.events)} events to {name}")
    else:
        if not args.send:
            raise ValueError("bridge is a MIDI write; pass --send after checking all four port names")
        if args.seconds <= 0:
            raise ValueError("--seconds must be positive")
        mido = _mido()
        input_a = resolve_unique_port(mido.get_input_names(), args.input_a)
        output_a = resolve_unique_port(mido.get_output_names(), args.output_a)
        input_b = resolve_unique_port(mido.get_input_names(), args.input_b)
        output_b = resolve_unique_port(mido.get_output_names(), args.output_b)
        started = time.monotonic()
        a_to_b = 0
        b_to_a = 0
        with mido.open_input(input_a) as port_a, mido.open_output(output_a) as destination_a, \
             mido.open_input(input_b) as port_b, mido.open_output(output_b) as destination_b:
            while time.monotonic() - started < args.seconds:
                for message in port_a.iter_pending():
                    destination_a.send(message)
                    a_to_b += 1
                for message in port_b.iter_pending():
                    destination_b.send(message)
                    b_to_a += 1
                time.sleep(0.001)
        print(f"bridged {a_to_b} messages {input_a} -> {output_a}; {b_to_a} messages {input_b} -> {output_b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
