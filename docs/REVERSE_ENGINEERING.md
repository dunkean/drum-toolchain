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
| SysEx manufacturer ID | — | — | protocol | UNKNOWN | no dump captured |
| Kit/Input/zone data | — | — | configuration | UNKNOWN | no dump captured |
| Write command | — | — | protocol | UNKNOWN | deliberately not attempted |

## Experiments

| Date | Experiment | Result | Consequence |
| --- | --- | --- | --- |
| 2026-08-19 | Windows USB/MIDI enumeration | `TriggerIO`, VID/PID `13B2:0021` visible | receive-only capture tooling created |

Do not record a semantic field interpretation here without linking it to the
two raw captures, their hashes, the exact single panel change, and restoration
evidence.
