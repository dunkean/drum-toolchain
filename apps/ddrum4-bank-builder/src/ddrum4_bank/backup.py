"""Validation and metadata for user-initiated DDrum4 settings backups."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path

import mido


@dataclass(frozen=True)
class BackupRecord:
    path: str
    sha256: str
    message_count: int
    sysex_count: int

    def write_metadata(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {"schema_version": 1, "kind": "ddrum4-settings-backup", **asdict(self)}
        path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_settings_backup(path: Path) -> BackupRecord:
    """Reject empty/corrupt MIDI files; do not assert what a dump contains."""
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("settings backup file is missing or empty")
    midi = mido.MidiFile(path)
    messages = [message for track in midi.tracks for message in track if not message.is_meta]
    if not messages:
        raise ValueError("settings backup contains no MIDI messages")
    return BackupRecord(
        path=str(path),
        sha256=sha256(path.read_bytes()).hexdigest(),
        message_count=len(messages),
        sysex_count=sum(message.type == "sysex" for message in messages),
    )
