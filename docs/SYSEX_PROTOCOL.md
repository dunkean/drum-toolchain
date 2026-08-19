# Legacy DDTi SysEx protocol

Status: **structural framing observed; configuration semantics unresolved; PC
writing disabled**.
The dump below was received from the connected legacy DDTi on 2026-08-19 after
a factory reset. One explicitly authorised full-dump replay was later made;
the DDTi accepted it but changed an unexplained byte in the subsequent panel
dump, so this repository exposes no active hardware writer.

## Verified framing capability of the tooling

The original 1,836-byte / 32-frame factory capture is retained as an immutable
**partial prefix** only. An independent `python-rtmidi` capture revealed that
the Windows native reader had queued only 32 buffers and omitted the final 11
frames. A complete observed DDTi dump is **2,016 bytes in 42 SysEx frames**:
21 kit frames followed by 21 global-trigger frames. After a verified factory
reset, `factory_dump_002_full` captured that complete stream (SHA-256
`43c64c486f72ec349c5ebee4020ef9e176f5d64033118f95fb25f6f81f84c70f`).
The original SHA-256 `504ebd7e…c42c33ce` must not be used as a
full-configuration golden. The tooling accepts a capture only when it is a
concatenation of complete standard MIDI SysEx frames:

```text
F0  <zero or more 7-bit data bytes>  F7
```

For this dump, every packet has this **observed** layout:

```text
F0
00 00 0E       observed manufacturer ID
2C             observed device byte
0D             observed command byte
00 00          observed address/reserved bytes
LL             declared-length byte (meaning not yet validated)
TT             record family
II             sequential record index
...            opaque body
F7
```

Two record families occur in order:

| `TT` | Index sequence | Packets | Packet size | Opaque body |
| ---: | --- | ---: | ---: | ---: |
| `01` | `00`–`14` | 21 | 78 bytes | 66 bytes |
| `02` | `00`–`14` | 21 | 18 bytes | 6 bytes |

`LL` is `46` for family `01` and `0A` for family `02`; it is not yet known
whether that byte is a length, subtype, or part of another encoding.  The
offline `ddti decode` command validates this framing and reproduces the exact
raw stream byte for byte.  It does not modify or reinterpret the payload.

## Confirmed kit MIDI-note records

Family `01` is confirmed as the 21-kit record family: its index `00` was
changed through the DDTi's Kit 0 panel controls, and the manual documents 21
available kits.  The first 60 bytes of each family-`01` body contain twenty
interleaved 3-byte records:

```text
Input 1 Tip, Input 1 Ring, Input 2 Tip, Input 2 Ring, ... Input 10 Ring
  raw channel byte, MIDI note, raw companion byte
```

The MIDI-note byte is confirmed by controlled panel captures:

| Panel action | Packet byte | Observed transition |
| --- | ---: | --- |
| Kit 0 / Input 1 Tip note | `0x00000C` | `35 → 36 → 37 → 35` |
| Kit 0 / Input 2 Tip note | `0x000012` | `38 → 39` |

The three values and two inputs prove direct `uint7` MIDI-note encoding and
the Tip/Ring interleaving. The surrounding channel and companion bytes remain
uninterpreted. Family `02` changed during saves but has no assigned semantics
or checksum rule yet.

## Confirmed per-kit Program Change

The final two Family-`01` body bytes are the per-kit Program Change fields:

```text
body +0x40   disabled flag: 1 = panel `---`, 0 = active
body +0x41   direct uint7 Program Change value 0..127
```

A controlled Kit 1 sequence produced `01 7F` (`---`), `00 00` (`0`) and
`00 01` (`1`) with no other changes. The value byte is ignored while the flag
is disabled. The former golden-replay difference `01 7F -> 01 00` therefore
canonicalised unused storage without enabling Program Change or changing any
functional configuration.

## Controlled write validation

A hash-locked 42-frame transfer was built from the complete factory golden,
canonicalised disabled Program Changes to `01 00`, and changed only Kit 0 /
Input 1 Tip Note from `35` to `36`. It was sent at 50 ms per frame. The next
panel dump was byte-identical to the sent stream (2,016 bytes, SHA-256
`c14e5136f3db716d3ad85986c9d1b5c6b72346d976132c537b0abfa323ee1cdb`).
This is a strict write PASS for confirmed MIDI-note fields. It does not by
itself validate writes to remaining raw trigger fields. A second controlled
transfer enabled Kit 0 Program Change `0` and changed Input 1 Tip Gain
`15→16`; its returned dump was also byte-identical (SHA-256
`b9d7d859589b01e107898f71593afb8d1ba427b445c006d883fe103ba20a0967`).
An isolated panel capture then mapped Family `02`, record `00`, bytes `+0..+4`
to Input 1 Tip Gain, Velocity Curve, Threshold, X-Talk and Retrigger. The exact
transitions were `15→16`, `Lin→LG1` (`6→7`), `5→7`, `1→4`, and `10→14`, with
no other byte changes. After a reset, the grouped PC transfer produced the
expected panel values and its following dump was byte-identical to the sent
stream (SHA-256 `3c391467216459e8ff64b025e313c83e1ed3b67bd06e9148f6e53024566175cb`).
Unknown trigger fields and unobserved values remain blocked by offset and value
allowlisting.

## Unknown protocol fields

| Field | Status |
| --- | --- |
| Manufacturer ID | `00 00 0E` observed in one factory dump; vendor attribution unverified |
| Model/device ID | `2C` observed; semantic meaning UNKNOWN |
| Command byte(s) | `0D` observed; semantic meaning UNKNOWN |
| Addressing | `00 00` observed; semantic meaning UNKNOWN |
| Payload encoding | note and Program Change fields described above; remaining bytes UNKNOWN |
| Checksum | UNKNOWN; family `02` changes on save require dedicated experiments |
| 7-bit packing beyond MIDI transport | UNKNOWN |
| Segmentation/order | UNKNOWN |
| Inter-message timing | UNKNOWN |
| Read/configuration-write commands | UNKNOWN |

No currently available command or public API sends a DDTi SysEx message.  The
one authorised 2026-08-19 test replayed the exact 42-frame factory golden and
then showed `0x7F -> 0x00` at Family `01` body offset `+0x41` in records
`00`–`13`. That byte's meaning and whether it is derived state are UNKNOWN;
therefore any writer, including a verbatim restore, is unsafe. In particular,
this project does not guess a dump-request frame from other ddrum products or
newer DDTi models.

## Next evidence required

Perform controlled panel edits and capture a dump after each one.  The legacy
[owner's manual](https://www.ddrum.com/images/manuals/DDTi%20manual.pdf)
documents **FUNCTION UP + VALUE UP** as the action that requests a Data Dump.
Only differential captures can establish field semantics and any checksum rule.
