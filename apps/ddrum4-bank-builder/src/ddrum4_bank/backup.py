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


@dataclass(frozen=True)
class BackupInspection:
    """Read-only structural facts about a received settings dump.

    This reports MIDI framing only: it neither decodes vendor payload semantics
    nor replays anything to a module.
    """

    record: BackupRecord
    message_types: dict[str, int]
    sysex_data_lengths: tuple[int, ...]
    sysex_prefixes: dict[str, int]
    repeated_message_sequence_count: int

    def to_document(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "ddrum4-settings-backup-inspection",
            "backup": asdict(self.record),
            "message_types": self.message_types,
            "sysex_data_lengths": list(self.sysex_data_lengths),
            "sysex_prefixes": self.sysex_prefixes,
            "repeated_message_sequence_count": self.repeated_message_sequence_count,
        }


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


def inspect_settings_backup(path: Path) -> BackupInspection:
    """Inspect a saved settings dump locally after validating it."""
    record = validate_settings_backup(path)
    midi = mido.MidiFile(path)
    messages = [message for track in midi.tracks for message in track if not message.is_meta]
    message_types: dict[str, int] = {}
    prefixes: dict[str, int] = {}
    lengths: set[int] = set()
    for message in messages:
        message_types[message.type] = message_types.get(message.type, 0) + 1
        if message.type == "sysex":
            lengths.add(len(message.data))
            prefix = " ".join(f"{byte:02X}" for byte in message.data[:4])
            prefixes[prefix] = prefixes.get(prefix, 0) + 1
    serialized = tuple(bytes(message.bin()) for message in messages)
    repeats = 1
    for candidate in range(2, len(serialized) + 1):
        if len(serialized) % candidate:
            continue
        segment_size = len(serialized) // candidate
        if serialized == serialized[:segment_size] * candidate:
            repeats = candidate
            break
    return BackupInspection(
        record,
        dict(sorted(message_types.items())),
        tuple(sorted(lengths)),
        dict(sorted(prefixes.items())),
        repeats,
    )
