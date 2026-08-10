"""Explicit, auditable DDrum4 hardware-write operations.

The bank builder deliberately keeps transfer separate from sound construction.
This module accepts one already-built sound at a time so a failed transfer can
never silently continue into a subsequent sound.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from .transport import send_midi_file


@dataclass(frozen=True)
class SoundTransferReceipt:
    """Facts recorded only after a successful, explicitly confirmed transfer."""

    sound_path: str
    sound_sha256: str
    midi_output: str
    messages_sent: int
    sysex_pause_seconds: float
    sysex_chunk_bytes: int | None
    completed_utc: str

    def to_document(self) -> dict[str, object]:
        return {"schema_version": 1, "kind": "ddrum4-sound-transfer-receipt", **asdict(self)}

    def write(self, path: Path) -> None:
        if path.exists():
            raise FileExistsError(f"refusing to overwrite transfer receipt: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def transfer_one_sound(
    sound: Path,
    midi_output: str,
    *,
    confirmed: bool,
    sysex_pause_seconds: float = 0.4,
    sysex_chunk_bytes: int | None = None,
) -> SoundTransferReceipt:
    """Send exactly one sound after an explicit caller confirmation.

    The receipt is returned only when the native MIDI sender reports success.
    The caller is responsible for storing it non-destructively.  There is no
    batch API intentionally: each sound needs its own module-memory check.
    """
    if not confirmed:
        raise ValueError("hardware write refused: pass explicit confirmation after verifying backup, Sound ID and MEM.LEFT")
    if sound.suffix.lower() not in {".mid", ".midi", ".syx"} or not sound.is_file() or sound.stat().st_size == 0:
        raise ValueError("sound must be a non-empty .mid, .midi or .syx file")
    if sysex_pause_seconds < 0:
        raise ValueError("sysex_pause_seconds must not be negative")
    if sysex_chunk_bytes is not None and sysex_chunk_bytes < 3:
        raise ValueError("sysex_chunk_bytes must be at least 3")
    message_count = send_midi_file(
        sound, midi_output, sysex_pause_seconds,
        sysex_chunk_bytes=sysex_chunk_bytes,
    )
    if message_count < 1:
        raise RuntimeError("MIDI sender reported no transferred messages")
    return SoundTransferReceipt(
        str(sound), sha256(sound.read_bytes()).hexdigest(), midi_output,
        message_count, sysex_pause_seconds, sysex_chunk_bytes,
        datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
