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
| SysEx framing | `F0 ... F7` | standard SysEx | packet | CONFIRMED | 42 complete frames in independent full capture |
| Manufacturer bytes | `00 00 0E` | 3-byte ID | packet | CONFIRMED | identical in all 32 frames; vendor attribution unverified |
| Device byte | `2C` | uint7 | packet | CONFIRMED | identical in all 32 frames; meaning unverified |
| Command byte | `0D` | uint7 | packet | CONFIRMED | identical in all 32 frames; meaning unverified |
| Packet family `01` | offset `0x0000` onwards | 21 × 78-byte packets, indexes `00`–`14` | dump | CONFIRMED | first factory dump, exact structural decode |
| Packet family `02` | offset `0x0666` onwards | 21 × 18-byte packets, indexes `00`–`14` | dump | CONFIRMED | independent full capture; original native capture was truncated after index `0A` |
| Kit record index | family `01` / index `00` | uint7 | per kit | CONFIRMED | Kit 0 panel edits changed this record only |
| Kit/Input zone ordering | family `01` body bytes `00`–`59` | 20 × 3-byte records, Tip/Ring interleaved | per kit | CONFIRMED | factory map plus Input 1/Input 2 controlled diffs |
| Input 1 Tip MIDI Note | `0x00000C` | uint7 | Kit 0 | CONFIRMED | tested `35/36/37`, restored `35` |
| Input 2 Tip MIDI Note | `0x00000012` | uint7 | Kit 0 | CONFIRMED | tested `38/39`; distinct field from Input 1 |
| Input 1 Tip Gain | family `02`, index `00`, body `+0x00` | uint7 | global trigger | CONFIRMED | saved panel value `15→16`, independent full capture `0F→10` |
| Input 1 Threshold candidate | family `02`, index `00`, body `+0x02` | uint7 | global trigger | HYPOTHESIS | saved panel value `5→6` produced `05→06`; record `06/+0x02` mirrored the same change and needs isolation |
| Zone raw channel byte | preceding note byte in each 3-byte record | uint7 | per kit | PROBABLE | two Tip zones: `09→0A` when panel channel `10→11`; inverse (`raw + 1`) pending more kits |
| Zone raw companion byte | following note byte in each 3-byte record | uint7 | per kit | UNKNOWN | observed `03` in factory Kit 0 |
| Family `02` byte +`0x05` | `0x000676` (index 0) | uint7 | unknown | UNKNOWN | changed `00→22→04` across saved edits |
| Family `02` body bytes | 21 records, indexes `00`–`14` | raw | global trigger | HYPOTHESIS | indexes follow the 20 Tip/Ring zones plus hi-hat control; one Input 1 Gain field confirmed |
| Kit Program Change disabled flag | family `01`, body `+0x40` | `1` = panel `---`; `0` = active | per kit | CONFIRMED | Kit 1 controlled `---→0→1`; factory Kit 20 independently contains active value `20` |
| Kit Program Change value | family `01`, body `+0x41` | direct uint7 `0..127`; ignored while disabled | per kit | CONFIRMED | Kit 1 controlled `---→0→1`; exact changes `7F→00→01` |
| PC write acceptance | complete 42-frame replay | DDTi canonicalises disabled Program Change from `01 7F` to `01 00` | protocol | PROBABLE | golden replay preserved the disabled flag and all functional fields; controlled Note write still required |

## Experiments

| Date | Experiment | Result | Consequence |
| --- | --- | --- | --- |
| 2026-08-19 | Windows USB/MIDI enumeration | `TriggerIO`, VID/PID `13B2:0021` visible | receive-only capture tooling created |
| 2026-08-19 | Factory-reset panel dump | 32 packets / 1,836 bytes / SHA-256 `504ebd7e…c42c33ce` | later found to be a native-reader prefix, retained for audit only |
| 2026-08-19 | Kit 0/Input 1 Tip note 35→36→37→35 | only `0x00000C` follows note exactly; some Family `02` state also changed on save | note field confirmed; Family `02` remains unknown |
| 2026-08-19 | Kit 0/Input 2 Tip note 38→39 | `0x000012: 26→27`; Family `02` byte +`0x05`: `22→04` | second input confirms Tip/Ring record layout |
| 2026-08-19 | Combined Input 1/2 channel, Gain and Threshold edits | two Tip channel bytes `09→0A`; Family `02` records `00`/`02` changed | channel encoding probable; global record semantics not yet assigned |
| 2026-08-19 | Independent receiver cross-check | 42 packets / 2,016 bytes; saved Input 1 Tip Gain `15→16` changes `family 02/index 00/+0x00: 0F→10` | Windows reader truncation found; full factory baseline must be recaptured after restoration |
| 2026-08-19 | Factory reset / full baseline recapture | `factory_dump_002_full`: 42 packets / 2,016 bytes / SHA-256 `43c64c48…1f84c70f`; its 1,836-byte prefix equals the original factory prefix | full factory golden established; Input 1 Tip note `35` and Gain `15` restored |
| 2026-08-19 | Input 1 Threshold `5→6` | complete dump: `family 02/index 00/+0x02: 05→06`, mirrored at `index 06/+0x02` | threshold byte candidate identified; duplicate scope remains unexplained |
| 2026-08-19 | Final reset verification after Threshold test | `factory_reset_verification_002_full` is byte-identical to `factory_dump_002_full.golden` (2,016 bytes / SHA-256 `43c64c48…1f84c70f`) | hardware restored exactly to the complete factory baseline |
| 2026-08-19 | Authorised full-golden PC round trip | replayed the exact 42-frame, 2,016-byte factory golden; the following dump differed at Family `01` body `+0x41` in indexes `00`–`13`, each `7F→00`; known note, channel, Gain and Threshold bytes were unchanged | PC sending is disabled; the user factory-reset the module afterwards and requested no repeated verification dumps |
| 2026-08-19 | Kit 1 Program Change `---→0→1` | two complete 42-frame dumps: `+0x40/+0x41` encoded `01 7F` for `---`, `00 00` for `0`, and `00 01` for `1`; no other bytes changed | former round-trip anomaly identified as canonicalisation of an ignored disabled value; controlled Note write can proceed |
| 2026-08-19 | Controlled PC write: Kit 0/Input 1 Tip Note `35→36` | sent 42 frames / 2,016 bytes at 50 ms intervals after canonicalising disabled Program Changes; sent and returned dumps are byte-identical, SHA-256 `c14e5136…1cdb` | strict hardware write PASS for confirmed notes and canonical disabled Program Change storage; user factory-reset afterwards |

Do not record a semantic field interpretation here without linking it to the
two raw captures, their hashes, the exact single panel change, and restoration
evidence.
