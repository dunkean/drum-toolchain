#!/usr/bin/env python3
"""List, send and observe MIDI messages through a Windows MIDI interface.

Examples:
  python tools/midi_probe.py --list
  python tools/midi_probe.py --send "MidiFace.*Out 3" --channel 10 --note 38
  python tools/midi_probe.py --listen "MidiFace.*In 3"
"""
import argparse
import re
import sys
import time

import mido


def resolve(names, pattern):
    matches = [name for name in names if re.search(pattern, name, re.I)]
    if len(matches) != 1:
        print(f"Expected exactly one MIDI port matching {pattern!r}; found: {matches}", file=sys.stderr)
        raise SystemExit(2)
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="show Windows MIDI input/output port names")
    parser.add_argument("--send", metavar="REGEX", help="send a 300 ms test note to the matching MIDI output")
    parser.add_argument("--listen", metavar="REGEX", help="print incoming messages from the matching MIDI input")
    parser.add_argument("--duration", type=float, help="stop listening after this many seconds")
    parser.add_argument("--loopback-out", metavar="REGEX", help="MIDI output used for an automatic loopback test")
    parser.add_argument("--loopback-in", metavar="REGEX", help="MIDI input expected to receive that test")
    parser.add_argument("--channel", type=int, default=10, choices=range(1, 17))
    parser.add_argument("--note", type=int, default=38, choices=range(128))
    parser.add_argument("--velocity", type=int, default=100, choices=range(128))
    parser.add_argument("--expected-channel", type=int, choices=range(1, 17),
                        help="expected returned channel for --loopback (default: --channel)")
    parser.add_argument("--expected-note", type=int, choices=range(128),
                        help="expected returned note for --loopback (default: --note)")
    parser.add_argument("--controller", type=int, choices=range(128),
                        help="send this CC instead of a note in --loopback")
    parser.add_argument("--value", type=int, default=127, choices=range(128),
                        help="CC value used with --controller (default: 127)")
    args = parser.parse_args()
    inputs, outputs = mido.get_input_names(), mido.get_output_names()
    if args.list or not (args.send or args.listen):
        print("MIDI inputs:")
        print(*inputs, sep="\n  ") if inputs else print("  (none)")
        print("MIDI outputs:")
        print(*outputs, sep="\n  ") if outputs else print("  (none)")
    if bool(args.loopback_out) != bool(args.loopback_in):
        parser.error("--loopback-out and --loopback-in must be provided together")
    if args.loopback_out:
        output_name = resolve(outputs, args.loopback_out)
        input_name = resolve(inputs, args.loopback_in)
        if args.controller is None:
            wanted_on = mido.Message("note_on", channel=args.channel - 1, note=args.note, velocity=args.velocity)
            wanted_off = mido.Message("note_off", channel=args.channel - 1, note=args.note, velocity=0)
        else:
            wanted_on = mido.Message("control_change", channel=args.channel - 1,
                                    control=args.controller, value=args.value)
            wanted_off = None
        expected_channel = (args.expected_channel or args.channel) - 1
        expected_note = args.expected_note if args.expected_note is not None else args.note
        received = []
        print(f"Loopback: {output_name} -> Arduino -> {input_name}")
        with mido.open_input(input_name) as inp, mido.open_output(output_name) as out:
            out.send(wanted_on)
            if wanted_off is not None:
                time.sleep(0.3)
                out.send(wanted_off)
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                received.extend(inp.iter_pending())
                time.sleep(0.01)
        print(*[f"< {message}" for message in received], sep="\n")
        if args.controller is None:
            got_on = any(message.type == "note_on" and message.channel == expected_channel
                         and message.note == expected_note and message.velocity == wanted_on.velocity
                         for message in received)
            got_off = any(message.type == "note_off" and message.channel == expected_channel
                          and message.note == expected_note for message in received)
            passed = got_on and got_off
        else:
            passed = any(message.type == "control_change" and message.channel == expected_channel
                         and message.control == args.controller and message.value == args.value
                         for message in received)
        if passed:
            print("PASS: expected MIDI event returned after routing.")
        else:
            print("FAIL: expected routed MIDI event did not return.", file=sys.stderr)
            raise SystemExit(1)
    if args.send:
        name = resolve(outputs, args.send)
        message = mido.Message("note_on", channel=args.channel - 1, note=args.note, velocity=args.velocity)
        print(f"> {name}: {message}")
        with mido.open_output(name) as out:
            out.send(message)
            time.sleep(0.3)
            out.send(mido.Message("note_off", channel=args.channel - 1, note=args.note, velocity=0))
    if args.listen:
        name = resolve(inputs, args.listen)
        print(f"Listening on {name}; press Ctrl+C to stop.")
        with mido.open_input(name) as port:
            if args.duration is None:
                for message in port:
                    print(f"< {message}")
            else:
                deadline = time.monotonic() + args.duration
                while time.monotonic() < deadline:
                    for message in port.iter_pending():
                        print(f"< {message}")
                    time.sleep(0.01)


if __name__ == "__main__":
    main()
