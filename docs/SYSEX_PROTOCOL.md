# Legacy DDTi SysEx protocol

Status: **structural framing observed; configuration semantics unresolved**.
The dump below was received from the connected legacy DDTi on 2026-08-19 after
a factory reset.  This repository has still sent no DDTi SysEx message.

## Verified framing capability of the tooling

The first factory dump is 1,836 bytes in 32 complete standard MIDI SysEx
frames, SHA-256
`504ebd7e1a82b98c9b515febb8f3713a7a801ac5e1bbe188fad50370c42c33ce`.
Three local byte-identical copies exist, including the immutable
`factory_dump_001.golden.syx`.  The tooling accepts a capture only when it is
a concatenation of complete standard MIDI SysEx frames:

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
| `02` | `00`–`0A` | 11 | 18 bytes | 6 bytes |

`LL` is `46` for family `01` and `0A` for family `02`; it is not yet known
whether that byte is a length, subtype, or part of another encoding.  The
offline `ddti decode` command validates this framing and reproduces the exact
raw stream byte for byte.  It does not modify or reinterpret the payload.

## Unknown protocol fields

| Field | Status |
| --- | --- |
| Manufacturer ID | `00 00 0E` observed in one factory dump; vendor attribution unverified |
| Model/device ID | `2C` observed; semantic meaning UNKNOWN |
| Command byte(s) | `0D` observed; semantic meaning UNKNOWN |
| Addressing | `00 00` observed; semantic meaning UNKNOWN |
| Payload encoding | UNKNOWN |
| Checksum | UNKNOWN |
| 7-bit packing beyond MIDI transport | UNKNOWN |
| Segmentation/order | UNKNOWN |
| Inter-message timing | UNKNOWN |
| Read/configuration-write commands | UNKNOWN |

No code sends a DDTi SysEx message.  In particular, this project does not
guess a dump-request frame from other ddrum products or newer DDTi models.

## Next evidence required

Perform controlled panel edits and capture a dump after each one.  The legacy
[owner's manual](https://www.ddrum.com/images/manuals/DDTi%20manual.pdf)
documents **FUNCTION UP + VALUE UP** as the action that requests a Data Dump.
Only differential captures can establish field semantics and any checksum rule.
