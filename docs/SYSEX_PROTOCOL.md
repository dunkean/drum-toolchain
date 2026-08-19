# Legacy DDTi SysEx protocol

Status: **unresolved**.  No legacy DDTi SysEx dump has been captured or sent
by this repository as of 2026-08-19.

## Verified framing capability of the tooling

The tooling accepts a capture only when it is a concatenation of complete
standard MIDI SysEx frames:

```text
F0  <zero or more 7-bit data bytes>  F7
```

For each received dump it preserves each byte exactly in `.syx`, produces a
readable hexadecimal view, and records a SHA-256 digest.  This is a statement
about MIDI framing, not about the DDTi's vendor payload.

## Unknown protocol fields

| Field | Status |
| --- | --- |
| Manufacturer ID | UNKNOWN |
| Model/device ID | UNKNOWN |
| Command byte(s) | UNKNOWN |
| Addressing | UNKNOWN |
| Payload encoding | UNKNOWN |
| Checksum | UNKNOWN |
| 7-bit packing beyond MIDI transport | UNKNOWN |
| Segmentation/order | UNKNOWN |
| Inter-message timing | UNKNOWN |
| Read/configuration-write commands | UNKNOWN |

No code sends a DDTi SysEx message.  In particular, this project does not
guess a dump-request frame from other ddrum products or newer DDTi models.

## Next evidence required

Capture a panel-initiated dump using the documented procedure in
[`DDTI_CAPTURE.md`](DDTI_CAPTURE.md).  Only then can this document name the
observed manufacturer ID, packet sequence, and candidate checksum rules.
