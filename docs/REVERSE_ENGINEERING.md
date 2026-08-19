# DDTi reverse-engineering journal

Confidence levels:

- `UNKNOWN`: no controlled observation;
- `HYPOTHESIS`: a single controlled difference suggests an interpretation;
- `PROBABLE`: repeated, consistent controlled evidence;
- `CONFIRMED`: at least three values and two inputs/kits where applicable,
  with restoration validated.

## Field register

| Field | Offset/address | Encoding | Scope | Confidence | Validation |
| --- | ---: | --- | --- | --- | --- |
| USB VID | `13B2` | uint16 hex | device | CONFIRMED | Windows PnP 2026-08-19 |
| USB PID | `0021` | uint16 hex | device | CONFIRMED | Windows PnP 2026-08-19 |
| MIDI input endpoint | `TriggerIO 30` | OS name | device | CONFIRMED | mido enumeration 2026-08-19 |
| MIDI output endpoint | `TriggerIO 10` | OS name | device | CONFIRMED | mido enumeration 2026-08-19 |
| SysEx framing | `F0 ... F7` | standard SysEx | packet | CONFIRMED | 32 complete frames in `factory_dump_001` |
| Manufacturer bytes | `00 00 0E` | 3-byte ID | packet | CONFIRMED | identical in all 32 frames; vendor attribution unverified |
| Device byte | `2C` | uint7 | packet | CONFIRMED | identical in all 32 frames; meaning unverified |
| Command byte | `0D` | uint7 | packet | CONFIRMED | identical in all 32 frames; meaning unverified |
| Packet family `01` | offset `0x0000` onwards | 21 × 78-byte packets, indexes `00`–`14` | dump | CONFIRMED | first factory dump, exact structural decode |
| Packet family `02` | offset `0x0666` onwards | 11 × 18-byte packets, indexes `00`–`0A` | dump | CONFIRMED | first factory dump, exact structural decode |
| Kit/Input/zone data | — | — | configuration | UNKNOWN | controlled differential captures required |
| Write command | — | — | protocol | UNKNOWN | deliberately not attempted |

## Experiments

| Date | Experiment | Result | Consequence |
| --- | --- | --- | --- |
| 2026-08-19 | Windows USB/MIDI enumeration | `TriggerIO`, VID/PID `13B2:0021` visible | receive-only capture tooling created |
| 2026-08-19 | Factory-reset panel dump | 32 packets / 1,836 bytes / SHA-256 `504ebd7e…c42c33ce` | raw framing decoder added; golden copy retained |

Do not record a semantic field interpretation here without linking it to the
two raw captures, their hashes, the exact single panel change, and restoration
evidence.
