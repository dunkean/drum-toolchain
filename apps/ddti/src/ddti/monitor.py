"""Live, read-only MIDI observation with portable JSON Lines captures."""
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import time

from .capture import _resolve_input


def message_record(message: object, port: str) -> dict[str, object]:
    values = {"timestamp_utc": datetime.now(UTC).isoformat(), "port": port, "message_type": getattr(message, "type")}
    if hasattr(message, "channel"):
        values["channel"] = getattr(message, "channel") + 1
    for field in ("note", "velocity", "control", "value", "program", "pitch"):
        if hasattr(message, field):
            values[field] = getattr(message, field)
    if getattr(message, "type") == "sysex":
        values["sysex_raw_hex"] = " ".join(f"{byte:02X}" for byte in getattr(message, "bytes")())
    return values


def monitor(port_query: str, *, seconds: float | None, output: Path | None) -> int:
    """Print each received message; this function never opens a MIDI output."""
    if seconds is not None and seconds <= 0:
        raise ValueError("seconds must be positive when supplied")
    import mido

    name = _resolve_input(port_query)
    started = time.monotonic()
    count = 0
    handle = output.open("x", encoding="utf-8", newline="\n") if output else None
    try:
        with mido.open_input(name) as input_port:
            while seconds is None or time.monotonic() - started < seconds:
                for message in input_port.iter_pending():
                    record = message_record(message, name)
                    rendered = json.dumps(record, sort_keys=True)
                    print(rendered, flush=True)
                    if handle:
                        handle.write(rendered + "\n")
                        handle.flush()
                    count += 1
                time.sleep(0.001)
    finally:
        if handle:
            handle.close()
    return count
