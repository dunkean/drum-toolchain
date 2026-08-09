from __future__ import annotations

from pathlib import Path
import platform
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
            messages = [message for message in mido.merge_tracks(file.tracks) if not message.is_meta]
            if messages and all(message.type == "sysex" for message in messages):
                # The SMF delta-times in a DDrum4UI sound file encode roughly
                # the serial-wire duration (376 ms for B0), not the sender's
                # inter-message pacing.  A native DDrum4UI capture measured a
                # 400 ms packet interval.  Reproduce that observed transport
                # rather than treating the sound file as a sequencer clip.
                # The native sender also emits two MIDI Reset messages before
                # the first packet and one immediately after the last one.
                # The DDrum4 rejects a bare packet stream even when the bytes
                # and 400 ms pace are otherwise correct.
                output.send(mido.Message("reset"))
                output.send(mido.Message("reset"))
                for message in messages:
                    output.send(message)
                    sent += 1
                    time.sleep(sysex_pause)
                output.send(mido.Message("reset"))
            else:
                # Preserve ordinary MIDI-file replay semantics for non-SysEx
                # traces used by the MIDI lab.
                for message in file.play(meta_messages=False):
                    output.send(message)
                    sent += 1
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
    messages = (
        _receive_windows_long_messages(name, seconds=seconds, idle_seconds=idle_seconds)
        if platform.system() == "Windows"
        else _receive_mido_messages(name, seconds=seconds, idle_seconds=idle_seconds)
    )
    if not messages:
        raise ValueError("no MIDI data received; start the module/UI dump then retry")
    track = mido.MidiTrack()
    track.extend(messages)
    output.parent.mkdir(parents=True, exist_ok=True)
    file = mido.MidiFile(type=0)
    file.tracks.append(track)
    file.save(output)
    return len(messages)


def _receive_mido_messages(name: str, *, seconds: float, idle_seconds: float) -> list[mido.Message]:
    """Portable fallback for small MIDI/SysEx messages."""
    track = mido.MidiTrack()
    started = time.monotonic()
    last_message = started
    with mido.open_input(name) as input_port:
        while time.monotonic() - started < seconds:
            message = input_port.poll()
            if message is None:
                if track and time.monotonic() - last_message >= idle_seconds:
                    break
                time.sleep(0.002)
                continue
            message.time = 0
            track.append(message)
            last_message = time.monotonic()
    return list(track)


def _receive_windows_long_messages(name: str, *, seconds: float, idle_seconds: float) -> list[mido.Message]:
    """Capture long Windows-MM SysEx packets without the 1 KiB input limit.

    DDrum4UI sound packets are 1,174 bytes including F0/F7.  The normal
    Python MIDI input backend silently dropped them on this workstation.
    Windows MM lets us provide sufficiently large receive buffers directly.
    """
    import ctypes as c
    from ctypes import wintypes as w

    input_names = list(mido.get_input_names())
    device_index = input_names.index(name)
    winmm = c.WinDLL("winmm")
    mim_longdata = 0x3C4
    callback_function = 0x30000
    dword_ptr = c.c_size_t

    class MidiHeader(c.Structure):
        _fields_ = [
            ("lpData", c.c_void_p),
            ("dwBufferLength", w.DWORD),
            ("dwBytesRecorded", w.DWORD),
            ("dwUser", dword_ptr),
            ("dwFlags", w.DWORD),
            ("lpNext", c.c_void_p),
            ("reserved", dword_ptr),
            ("dwOffset", w.DWORD),
            ("dwReserved", dword_ptr * 8),
        ]

    callback_type = c.WINFUNCTYPE(None, c.c_void_p, w.UINT, dword_ptr, dword_ptr, dword_ptr)
    raw_messages: list[bytes] = []

    @callback_type
    def callback(handle: object, event: int, instance: int, parameter: int, timestamp: int) -> None:
        if event != mim_longdata:
            return
        header = c.cast(parameter, c.POINTER(MidiHeader)).contents
        if header.dwBytesRecorded:
            raw_messages.append(c.string_at(header.lpData, header.dwBytesRecorded))

    handle = c.c_void_p()
    header_size = c.sizeof(MidiHeader)
    result = winmm.midiInOpen(c.byref(handle), device_index, callback, 0, callback_function)
    if result:
        raise RuntimeError(f"Windows MM could not open MIDI input {name!r}: error {result}")

    # A full DDrum4 settings dump observed on this workstation has 56 packets.
    # Reserve 64 buffers so callback ownership never has to be recycled while
    # the module is still transmitting.
    buffers: list[tuple[object, MidiHeader]] = []
    try:
        for _ in range(64):
            buffer = c.create_string_buffer(4096)
            header = MidiHeader(c.cast(buffer, c.c_void_p), 4096, 0, 0, 0, None, 0, 0, (dword_ptr * 8)())
            result = winmm.midiInPrepareHeader(handle, c.byref(header), header_size)
            if result:
                raise RuntimeError(f"Windows MM could not prepare SysEx buffer: error {result}")
            result = winmm.midiInAddBuffer(handle, c.byref(header), header_size)
            if result:
                raise RuntimeError(f"Windows MM could not queue SysEx buffer: error {result}")
            buffers.append((buffer, header))
        result = winmm.midiInStart(handle)
        if result:
            raise RuntimeError(f"Windows MM could not start MIDI input: error {result}")
        started = time.monotonic()
        last_count = 0
        last_message = started
        while time.monotonic() - started < seconds:
            if len(raw_messages) != last_count:
                last_count = len(raw_messages)
                last_message = time.monotonic()
            elif raw_messages and time.monotonic() - last_message >= idle_seconds:
                break
            time.sleep(0.002)
    finally:
        winmm.midiInStop(handle)
        winmm.midiInReset(handle)
        for _, header in buffers:
            winmm.midiInUnprepareHeader(handle, c.byref(header), header_size)
        winmm.midiInClose(handle)

    messages: list[mido.Message] = []
    for raw in raw_messages:
        message = mido.Message.from_bytes(list(raw))
        message.time = 0
        messages.append(message)
    return messages
