from __future__ import annotations

from pathlib import Path
import time

import mido


def ports() -> tuple[list[str], list[str]]:
    return list(mido.get_input_names()), list(mido.get_output_names())


def resolve_port(names: list[str], query: str) -> str:
    exact_matches = [name for name in names if name.casefold() == query.casefold()]
    if len(exact_matches) == 1:
        return exact_matches[0]
    matches = [name for name in names if query.lower() in name.lower()]
    if len(matches) != 1:
        raise ValueError(f"expected one port containing {query!r}, found {matches}")
    return matches[0]


def send_midi_file(path: Path, port_query: str, sysex_pause: float = 0.4) -> int:
    suffix = path.suffix.lower()
    if suffix not in {".mid", ".midi", ".syx"}:
        raise ValueError("accepted transfer files are .mid, .midi and raw .syx")
    if not path.is_file():
        raise ValueError(f"transfer file does not exist: {path}")
    name = resolve_port(list(mido.get_output_names()), port_query)
    sent = 0
    with mido.open_output(name) as output:
        if suffix == ".syx":
            # mido parses only framed MIDI messages; this deliberately refuses
            # malformed binary data rather than placing arbitrary bytes on DIN.
            messages = mido.parse_all(path.read_bytes())
            if not messages or any(message.type != "sysex" for message in messages):
                raise ValueError(".syx must contain one or more complete SysEx messages only")
            for message in messages:
                output.send(message)
                sent += 1
                time.sleep(sysex_pause)
        else:
            file = mido.MidiFile(path)
            for message in file.play(meta_messages=False):
                output.send(message)
                sent += 1
                if message.type == "sysex":
                    time.sleep(sysex_pause)
    return sent


def send_all(directory: Path, port_query: str, sysex_pause: float = 0.4) -> list[tuple[Path, int]]:
    results = []
    for path in sorted([*directory.glob("*.mid"), *directory.glob("*.midi"), *directory.glob("*.syx")]):
        results.append((path, send_midi_file(path, port_query, sysex_pause)))
    return results


def receive_midi_dump(port_query: str, output: Path, seconds: float = 15.0, idle_seconds: float = 2.0) -> int:
    """Record a user-initiated ddrum4 SysEx/settings dump into a MIDI file.

    The ddrum4 request command is intentionally not guessed. Start a dump from
    ddrum4UI/module, then run this listener on the selected input.
    """
    if seconds <= 0 or idle_seconds <= 0:
        raise ValueError("seconds and idle_seconds must be positive")
    name = resolve_port(list(mido.get_input_names()), port_query)
    track = mido.MidiTrack()
    started = time.monotonic()
    last_message = started
    count = 0
    with mido.open_input(name) as input_port:
        while time.monotonic() - started < seconds:
            message = input_port.poll()
            if message is None:
                if count and time.monotonic() - last_message >= idle_seconds:
                    break
                time.sleep(0.002)
                continue
            message.time = 0
            track.append(message)
            count += 1
            last_message = time.monotonic()
    if not count:
        raise ValueError("no MIDI data received; start the module/UI dump then retry")
    output.parent.mkdir(parents=True, exist_ok=True)
    file = mido.MidiFile(type=0)
    file.tracks.append(track)
    file.save(output)
    return count
