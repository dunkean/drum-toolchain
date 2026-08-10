#!/usr/bin/env python3
"""List, send and observe MIDI messages through a Windows MIDI interface.

Examples:
  python tools/midi_probe.py --list
  python tools/midi_probe.py --send "MidiFace.*Out 3" --channel 10 --note 38
  python tools/midi_probe.py --listen "MidiFace.*In 3"
  python tools/midi_probe.py --send "UMC404HD.*Out 9" --audio-input 3 \
      --scan-notes --channel 12 --note-start 0 --note-end 127
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


def audio_scan(*, output_name, audio_input, pairs, slot_seconds, note_length_seconds):
    """Send a deterministic note grid and print the measured input level per hit.

    This is deliberately diagnostic-only: audio stays in memory and no module
    or project setting is written. It makes a DDrum4 MIDI input-map search
    repeatable even when its panel does not reveal the active receive note.
    """
    import numpy as np
    import sounddevice as sd

    if not pairs or slot_seconds <= 0 or not 0 < note_length_seconds < slot_seconds:
        raise ValueError("scan needs at least one pair and 0 < note length < slot length")
    input_index = int(audio_input.split(":", 1)[0]) if audio_input.split(":", 1)[0].isdigit() else audio_input
    lead_seconds = 0.25
    duration = lead_seconds + len(pairs) * slot_seconds + 0.25
    recording = sd.rec(round(duration * 44100), samplerate=44100, channels=2,
                       dtype="float32", device=input_index)
    time.sleep(lead_seconds)
    with mido.open_output(output_name) as out:
        for channel, note in pairs:
            out.send(mido.Message("note_on", channel=channel - 1, note=note, velocity=110))
            time.sleep(note_length_seconds)
            out.send(mido.Message("note_off", channel=channel - 1, note=note, velocity=0))
            time.sleep(slot_seconds - note_length_seconds)
    sd.wait()
    levels = []
    for index, (channel, note) in enumerate(pairs):
        start = round((lead_seconds + index * slot_seconds) * 44100)
        end = round((lead_seconds + (index + 1) * slot_seconds) * 44100)
        window = recording[start:end]
        rms = float(np.sqrt(np.mean(np.square(window))))
        peak = float(np.max(np.abs(window)))
        levels.append((rms, peak, channel, note))
    baseline = sorted(level[0] for level in levels)[len(levels) // 2]
    print(f"Audio baseline RMS: {baseline:.7f}")
    for rms, peak, channel, note in sorted(levels, reverse=True):
        print(f"channel={channel:02d} note={note:03d} rms={rms:.7f} peak={peak:.7f}")


def audio_monitor(*, audio_input, duration):
    """Measure a single live audio window without sending any MIDI.

    This is used to validate the physical DDrum4 -> Arduino -> DDrum4 loop
    from its resulting audio, even when the module deliberately does not echo
    incoming MIDI back to its MIDI OUT port.
    """
    import numpy as np
    import sounddevice as sd

    input_index = int(audio_input.split(":", 1)[0]) if audio_input.split(":", 1)[0].isdigit() else audio_input
    print(f"Monitoring {audio_input} for {duration:.1f}s: play one deliberate pad hit now.")
    recording = sd.rec(round(duration * 44100), samplerate=44100, channels=2,
                       dtype="float32", device=input_index)
    sd.wait()
    magnitude = np.max(np.abs(recording), axis=1)
    peak = float(np.max(magnitude))
    rms = float(np.sqrt(np.mean(np.square(recording))))
    threshold = max(0.003, peak * 0.02)
    active = np.flatnonzero(magnitude >= threshold)
    if not len(active):
        print(f"NO AUDIO: peak={peak:.7f}, rms={rms:.7f}")
        return
    first, last = int(active[0]), int(active[-1])
    print(f"AUDIO DETECTED: peak={peak:.4f}, rms={rms:.6f}, "
          f"activity={first / 44100:.3f}s..{last / 44100:.3f}s "
          f"({(last - first) / 44100:.3f}s above {threshold:.5f})")


def audio_note_measure(*, output_name, audio_input, channel, note, velocity, duration):
    """Trigger one MIDI note and report both the body and low-level tail time.

    A DDrum sound is normally one-shot, so a short Note On/Off pair models a
    pad event while still allowing the recording to expose a long cymbal tail.
    Nothing is saved and no module setting is changed.
    """
    import numpy as np
    import sounddevice as sd

    sample_rate = 44100
    lead_seconds = 0.25
    input_index = int(audio_input.split(":", 1)[0]) if audio_input.split(":", 1)[0].isdigit() else audio_input
    print(f"Measuring C{channel} note {note} on {output_name} through {audio_input} for {duration:.1f}s.")
    recording = sd.rec(round(duration * sample_rate), samplerate=sample_rate, channels=2,
                       dtype="float32", device=input_index)
    time.sleep(lead_seconds)
    with mido.open_output(output_name) as out:
        out.send(mido.Message("note_on", channel=channel - 1, note=note, velocity=velocity))
        time.sleep(0.08)
        out.send(mido.Message("note_off", channel=channel - 1, note=note, velocity=0))
    sd.wait()
    magnitude = np.max(np.abs(recording), axis=1)
    peak = float(np.max(magnitude))
    rms = float(np.sqrt(np.mean(np.square(recording))))
    noise = float(np.sqrt(np.mean(np.square(recording[: round(lead_seconds * sample_rate)]))))
    body_threshold = max(0.003, peak * 0.02)
    tail_threshold = max(0.001, noise * 4.0)
    def last_active(threshold):
        indices = np.flatnonzero(magnitude >= threshold)
        return None if not len(indices) else max(0.0, indices[-1] / sample_rate - lead_seconds)
    body = last_active(body_threshold)
    tail = last_active(tail_threshold)
    if body is None:
        print(f"NO AUDIO: peak={peak:.7f}, rms={rms:.7f}, noise={noise:.7f}")
        return
    print(f"AUDIO DETECTED: peak={peak:.4f}, rms={rms:.6f}; "
          f"body={body:.3f}s (>{body_threshold:.5f}), "
          f"tail={tail:.3f}s (>{tail_threshold:.5f})")


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
    parser.add_argument("--audio-input", help="audio input index/name used by a MIDI-to-audio scan")
    parser.add_argument("--monitor-audio", action="store_true",
                        help="measure live audio only; sends no MIDI")
    parser.add_argument("--measure-note", action="store_true",
                        help="trigger --channel/--note once and measure its audio body and tail")
    parser.add_argument("--scan-channels", action="store_true",
                        help="send the chosen note on all 16 MIDI channels and rank audio energy")
    parser.add_argument("--scan-notes", action="store_true",
                        help="send a MIDI-note range on --channel and rank audio energy")
    parser.add_argument("--note-start", type=int, default=0, choices=range(128),
                        help="first note for --scan-notes (default: 0)")
    parser.add_argument("--note-end", type=int, default=127, choices=range(128),
                        help="last note for --scan-notes (default: 127)")
    parser.add_argument("--slot-ms", type=int, default=400,
                        help="per-note scan window in milliseconds (default: 400)")
    args = parser.parse_args()
    inputs, outputs = mido.get_input_names(), mido.get_output_names()
    if args.list or not (args.send or args.listen or args.monitor_audio or args.measure_note):
        print("MIDI inputs:")
        print(*inputs, sep="\n  ") if inputs else print("  (none)")
        print("MIDI outputs:")
        print(*outputs, sep="\n  ") if outputs else print("  (none)")
    if bool(args.loopback_out) != bool(args.loopback_in):
        parser.error("--loopback-out and --loopback-in must be provided together")
    if args.scan_channels and args.scan_notes:
        parser.error("choose either --scan-channels or --scan-notes")
    if (args.scan_channels or args.scan_notes) and not args.audio_input:
        parser.error("--audio-input is required for an audio scan")
    if args.monitor_audio and not args.audio_input:
        parser.error("--audio-input is required for --monitor-audio")
    if args.measure_note and not (args.audio_input and args.send):
        parser.error("--measure-note requires both --send and --audio-input")
    if args.note_start > args.note_end:
        parser.error("--note-start must not exceed --note-end")
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
    if args.send and not (args.scan_channels or args.scan_notes or args.measure_note):
        name = resolve(outputs, args.send)
        message = mido.Message("note_on", channel=args.channel - 1, note=args.note, velocity=args.velocity)
        print(f"> {name}: {message}")
        with mido.open_output(name) as out:
            out.send(message)
            time.sleep(0.3)
            out.send(mido.Message("note_off", channel=args.channel - 1, note=args.note, velocity=0))
    if args.scan_channels or args.scan_notes:
        # A send/scan target intentionally shares --send to avoid a second
        # ambiguous MIDI-output selector. The scan never runs unless the user
        # explicitly supplies it.
        if not args.send:
            parser.error("--send selects the MIDI output for an audio scan")
        name = resolve(outputs, args.send)
        pairs = ([(channel, args.note) for channel in range(1, 17)] if args.scan_channels
                 else [(args.channel, note) for note in range(args.note_start, args.note_end + 1)])
        audio_scan(output_name=name, audio_input=args.audio_input, pairs=pairs,
                   slot_seconds=args.slot_ms / 1000, note_length_seconds=min(0.08, args.slot_ms / 2000))
    if args.monitor_audio:
        audio_monitor(audio_input=args.audio_input, duration=args.duration or 8.0)
    if args.measure_note:
        name = resolve(outputs, args.send)
        audio_note_measure(output_name=name, audio_input=args.audio_input,
                           channel=args.channel, note=args.note, velocity=args.velocity,
                           duration=args.duration or 8.0)
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
