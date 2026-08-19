"""Read-only capture and integrity artifacts for user-initiated DDTi dumps."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import platform
import time
from typing import Callable, Literal

from .protocol import decode_dump
from .sysex import SysExMessage, parse_stream, render_hex


_WINDOWS_SYSEX_BUFFER_COUNT = 64


class CaptureCancelled(RuntimeError):
    """Raised when a caller explicitly cancels a receive-only capture."""


@dataclass(frozen=True)
class CaptureResult:
    source_port: str
    captured_at_utc: str
    message_count: int
    sysex_count: int
    byte_count: int
    sha256: str
    syx_path: Path
    hex_path: Path
    metadata_path: Path


def _resolve_input(query: str) -> str:
    import mido

    names = list(mido.get_input_names())
    exact = [name for name in names if name.casefold() == query.casefold()]
    if len(exact) == 1:
        return exact[0]
    matches = [name for name in names if query.casefold() in name.casefold()]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one MIDI input matching {query!r}; found {matches}")
    return matches[0]


def capture_dump(
    port_query: str,
    stem: Path,
    *,
    seconds: float,
    idle_seconds: float,
    receiver: Literal["auto", "mido"] = "auto",
    cancelled: Callable[[], bool] | None = None,
) -> CaptureResult:
    """Listen only; write received complete SysEx frames to three new files."""
    if seconds <= 0 or idle_seconds <= 0:
        raise ValueError("seconds and idle_seconds must be positive")
    if receiver not in {"auto", "mido"}:
        raise ValueError("receiver must be 'auto' or 'mido'")
    paths = tuple(stem.with_suffix(suffix) for suffix in (".syx", ".hex", ".json"))
    existing = [path for path in paths if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite capture artifact(s): {', '.join(map(str, existing))}")
    if cancelled is not None and cancelled():
        raise CaptureCancelled("DDTi capture cancelled")
    name = _resolve_input(port_query)
    use_windows_receiver = receiver == "auto" and platform.system() == "Windows"
    messages = (
        _receive_windows_sysex(name, seconds=seconds, idle_seconds=idle_seconds, cancelled=cancelled)
        if use_windows_receiver
        else _receive_mido_sysex(name, seconds=seconds, idle_seconds=idle_seconds, cancelled=cancelled)
    )
    if cancelled is not None and cancelled():
        raise CaptureCancelled("DDTi capture cancelled")
    if not messages:
        raise ValueError("no SysEx received; start the DDTi panel dump while this listener is running")
    raw = b"".join(message.raw for message in messages)
    # Parse again so a complete on-disk stream is checked before any artifact is published.
    parsed = parse_stream(raw)
    if parsed != tuple(messages):
        raise RuntimeError("captured SysEx framing changed during round-trip validation")
    _require_complete_ddti_dump(raw)
    stem.parent.mkdir(parents=True, exist_ok=True)
    syx_path, hex_path, metadata_path = paths
    syx_path.write_bytes(raw)
    hex_path.write_text(render_hex(parsed), encoding="utf-8", newline="\n")
    result = CaptureResult(
        source_port=name,
        captured_at_utc=datetime.now(UTC).isoformat(),
        message_count=len(messages),
        sysex_count=len(messages),
        byte_count=len(raw),
        sha256=sha256(raw).hexdigest(),
        syx_path=syx_path,
        hex_path=hex_path,
        metadata_path=metadata_path,
    )
    document = {
        "schema_version": 1,
        "kind": "ddti-read-only-sysex-capture",
        "protocol_semantics": "unknown",
        "files": {"syx": syx_path.name, "hex": hex_path.name},
        **{name: str(value) if isinstance(value, Path) else value for name, value in asdict(result).items() if name not in {"syx_path", "hex_path", "metadata_path"}},
    }
    metadata_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return result


def _require_complete_ddti_dump(raw: bytes) -> None:
    """Reject a recognised DDTi panel dump when any required frame is absent."""
    if not raw.startswith(bytes((0xF0, 0x00, 0x00, 0x0E, 0x2C, 0x0D))):
        return
    dump = decode_dump(raw)
    expected = tuple(range(21))
    if dump.family_indexes() != {1: expected, 2: expected}:
        families = dump.family_indexes()
        details = "; ".join(
            f"family {family}: received {len(families.get(family, ()))}/21, "
            f"missing {sorted(set(expected) - set(families.get(family, ())))}"
            for family in (1, 2)
        )
        raise ValueError(
            "incomplete DDTi panel dump: expected 21 kit and 21 global-trigger packets; "
            f"{details}; no capture artifact was written"
        )


def capture_series(
    port_query: str,
    directory: Path,
    *,
    label: str,
    snapshots: int,
    seconds_per_snapshot: float,
    idle_seconds: float,
    on_listening: Callable[[int, Path], None] | None = None,
) -> tuple[CaptureResult, ...]:
    """Capture several user-initiated dumps without restarting the CLI process.

    Each snapshot still opens a fresh receive-only endpoint and waits for one
    complete dump.  This preserves the proven native Windows long-message path
    while letting the operator perform a compact sequence of panel edits.
    """
    if snapshots <= 0:
        raise ValueError("snapshots must be positive")
    if not label or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in label):
        raise ValueError("label may contain only letters, numbers, _ and -")
    results = []
    for number in range(1, snapshots + 1):
        stem = directory / f"{label}_{number:03d}"
        if on_listening:
            on_listening(number, stem)
        results.append(capture_dump(port_query, stem, seconds=seconds_per_snapshot, idle_seconds=idle_seconds))
    return tuple(results)


def _receive_mido_sysex(
    name: str,
    *,
    seconds: float,
    idle_seconds: float,
    cancelled: Callable[[], bool] | None = None,
) -> list[SysExMessage]:
    """Portable fallback used for development and small standard SysEx frames."""
    import mido

    started = time.monotonic()
    last_message = started
    messages: list[SysExMessage] = []
    with mido.open_input(name) as input_port:
        while time.monotonic() - started < seconds:
            if cancelled is not None and cancelled():
                break
            pending = list(input_port.iter_pending())
            if pending:
                last_message = time.monotonic()
            for message in pending:
                if message.type == "sysex":
                    messages.append(SysExMessage(bytes(message.bytes())))
            if messages and time.monotonic() - last_message >= idle_seconds:
                break
            time.sleep(0.001)
    return messages


def _receive_windows_sysex(
    name: str,
    *,
    seconds: float,
    idle_seconds: float,
    cancelled: Callable[[], bool] | None = None,
) -> list[SysExMessage]:
    """Receive Windows-MM long messages with 64 KiB buffers.

    `python-rtmidi` can use comparatively small input buffers.  Direct WinMM
    long-message buffers prevent a legacy configuration dump from being
    truncated merely because its packet size was not predicted in advance.
    This receiver opens an input endpoint only and has no `midiOut*` calls.
    """
    import ctypes as c
    from ctypes import wintypes as w
    import mido

    device_index = list(mido.get_input_names()).index(name)
    winmm = c.WinDLL("winmm")
    mim_longdata = 0x3C4
    callback_function = 0x30000
    dword_ptr = c.c_size_t

    class MidiHeader(c.Structure):
        _fields_ = [
            ("lpData", c.c_void_p), ("dwBufferLength", w.DWORD), ("dwBytesRecorded", w.DWORD),
            ("dwUser", dword_ptr), ("dwFlags", w.DWORD), ("lpNext", c.c_void_p),
            ("reserved", dword_ptr), ("dwOffset", w.DWORD), ("dwReserved", dword_ptr * 8),
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
    # A full legacy DDTi dump has 42 SysEx packets. Queue more than that before
    # starting: the former 32-buffer limit silently truncated the final eleven
    # global-trigger packets on Windows.
    buffers: list[tuple[object, MidiHeader]] = []
    try:
        for _ in range(_WINDOWS_SYSEX_BUFFER_COUNT):
            buffer = c.create_string_buffer(65_536)
            header = MidiHeader(c.cast(buffer, c.c_void_p), 65_536, 0, 0, 0, None, 0, 0, (dword_ptr * 8)())
            if result := winmm.midiInPrepareHeader(handle, c.byref(header), header_size):
                raise RuntimeError(f"Windows MM could not prepare SysEx buffer: error {result}")
            if result := winmm.midiInAddBuffer(handle, c.byref(header), header_size):
                raise RuntimeError(f"Windows MM could not queue SysEx buffer: error {result}")
            buffers.append((buffer, header))
        if result := winmm.midiInStart(handle):
            raise RuntimeError(f"Windows MM could not start MIDI input: error {result}")
        started = time.monotonic()
        last_count = 0
        last_message = started
        while time.monotonic() - started < seconds:
            if cancelled is not None and cancelled():
                break
            if len(raw_messages) != last_count:
                last_count = len(raw_messages)
                last_message = time.monotonic()
            elif raw_messages and time.monotonic() - last_message >= idle_seconds:
                break
            time.sleep(0.001)
    finally:
        winmm.midiInStop(handle)
        winmm.midiInReset(handle)
        for _, header in buffers:
            winmm.midiInUnprepareHeader(handle, c.byref(header), header_size)
        winmm.midiInClose(handle)
    return [SysExMessage(raw) for raw in raw_messages]
