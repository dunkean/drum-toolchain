"""Structural decoder for the *observed* legacy DDTi 2016 dump framing.

This module names byte positions for inspection only.  It preserves every raw
packet exactly and deliberately does not infer trigger-setting semantics or a
write checksum from one factory-reset dump.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .sysex import SysExMessage, parse_stream


OBSERVED_MANUFACTURER_ID = bytes((0x00, 0x00, 0x0E))
OBSERVED_DEVICE_BYTE = 0x2C
OBSERVED_COMMAND_BYTE = 0x0D
OBSERVED_ADDRESS = bytes((0x00, 0x00))


@dataclass(frozen=True)
class DDTiPacket:
    """One received packet with only experimentally observed structural fields."""

    message: SysExMessage

    def __post_init__(self) -> None:
        raw = self.message.raw
        if len(raw) < 12:
            raise ValueError("DDTi packet is too short for observed header fields")
        if raw[1:4] != OBSERVED_MANUFACTURER_ID:
            raise ValueError(f"unexpected manufacturer bytes {raw[1:4].hex(' ').upper()}")
        if raw[4] != OBSERVED_DEVICE_BYTE or raw[5] != OBSERVED_COMMAND_BYTE:
            raise ValueError("packet does not match the observed DDTi 2016 device/command prefix")
        if raw[6:8] != OBSERVED_ADDRESS:
            raise ValueError(f"unexpected observed-address bytes {raw[6:8].hex(' ').upper()}")

    @property
    def raw(self) -> bytes:
        return self.message.raw

    @property
    def declared_length(self) -> int:
        """Byte 8.  Its unit/meaning remains unverified."""
        return self.raw[8]

    @property
    def record_type(self) -> int:
        """Byte 9; labels a packet family in the captured stream."""
        return self.raw[9]

    @property
    def record_index(self) -> int:
        """Byte 10; sequential inside each observed packet family."""
        return self.raw[10]

    @property
    def body(self) -> bytes:
        """Opaque bytes after family/index and before F7."""
        return self.raw[11:-1]

    def to_document(self, offset: int) -> dict[str, object]:
        return {
            "offset": offset,
            "length": len(self.raw),
            "manufacturer_id_hex": self.raw[1:4].hex(" ").upper(),
            "device_byte": self.raw[4],
            "command_byte": self.raw[5],
            "address_bytes_hex": self.raw[6:8].hex(" ").upper(),
            "declared_length_byte": self.declared_length,
            "record_type": self.record_type,
            "record_index": self.record_index,
            "opaque_body_length": len(self.body),
        }


@dataclass(frozen=True)
class DDTiDump:
    """Lossless structural view of a concatenated DDTi SysEx dump."""

    packets: tuple[DDTiPacket, ...]
    raw: bytes

    def __post_init__(self) -> None:
        if not self.packets:
            raise ValueError("a DDTi dump must contain at least one packet")
        if b"".join(packet.raw for packet in self.packets) != self.raw:
            raise ValueError("packets do not reproduce the original raw dump exactly")

    @property
    def sha256(self) -> str:
        return sha256(self.raw).hexdigest()

    def family_indexes(self) -> dict[int, tuple[int, ...]]:
        families: dict[int, list[int]] = {}
        for packet in self.packets:
            families.setdefault(packet.record_type, []).append(packet.record_index)
        return {family: tuple(indexes) for family, indexes in sorted(families.items())}

    def to_document(self) -> dict[str, object]:
        offset = 0
        packets = []
        for packet in self.packets:
            packets.append(packet.to_document(offset))
            offset += len(packet.raw)
        return {
            "schema_version": 1,
            "kind": "ddti-observed-2016-dump-structure",
            "semantic_decoding": "not yet validated",
            "byte_count": len(self.raw),
            "sha256": self.sha256,
            "packet_count": len(self.packets),
            "packet_lengths": dict(sorted(Counter(len(packet.raw) for packet in self.packets).items())),
            "families": {f"0x{family:02X}": list(indexes) for family, indexes in self.family_indexes().items()},
            "packets": packets,
        }


def decode_dump(raw: bytes) -> DDTiDump:
    """Decode a raw received `.syx` stream and verify byte-for-byte round-trip."""
    messages = parse_stream(raw)
    dump = DDTiDump(tuple(DDTiPacket(message) for message in messages), raw)
    if b"".join(packet.raw for packet in dump.packets) != raw:  # defensive, protects future refactors
        raise RuntimeError("DDTi structural decode failed raw round-trip")
    return dump


def decode_file(path: Path) -> DDTiDump:
    return decode_dump(path.read_bytes())

