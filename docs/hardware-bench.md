# DDrum4 Hardware Bench

The observed connection is `MIDI4x4` output to DDrum4 MIDI IN, `MIDI4x4` input
from DDrum4 MIDI OUT, and DDrum4 audio outputs 1/2 to UMC404HD inputs 1/2.
Scripts must resolve a unique name, never use a numeric device index.

## First action: settings backup

No test sound, SysEx request, sound upload, or bulk transfer may be sent until
a DDrum4 settings dump was captured and validated on 2026-08-10. The
repository does not guess a request SysEx command. Start the dump manually
from the module or ddrum4UI, then run the receiver in a separate terminal:

```powershell
$env:PYTHONPATH = 'apps/ddrum4-bank-builder/src'
python -m ddrum4_bank.cli receive-settings-backup `
  --input MIDI4x4 --output D:\Studio\ddrum4-backups\settings-YYYYMMDD.mid `
  --confirm-listening
```

The command only opens the named MIDI input. It writes the received MIDI file,
rejects an empty/corrupt file, calculates a SHA-256 hash and writes adjacent
metadata. Backups stay outside Git. A settings dump is not evidence that the
module's audio sound files are backed up; those are a separate concern.

On this PC, use `--input 'MIDI4x4 30'` if the generic name is ambiguous.
The receiver now prefers an exact port-name match before performing a partial
match. The validated local backup is outside Git at
`D:\Studio\ddrum4-backups\settings-20260810.mid`, with SHA-256
`4c05512746282701aefe2ee3af24d30aa7909ccda2c5cbdecf4e83f733fea037`.
It contains 56 SysEx messages. Its structural inspection reports payload
lengths 112, 121, and 578 bytes; these are framing facts only, not a decoded
DDrum4 protocol specification. The 56 messages form two byte-identical
28-message sequences; the inspector records this fact without assuming why
the module emits it.

### Observed module state — 2026-08-10

- Firmware shown at boot: `1.50`.
- `SHIFT` + `MEM.LEFT`: `1.27`, meaning 1,270 currently free blocks.
- The user explicitly authorized replacement of all existing sounds if needed.
  B0 still starts with the available free memory and deletes nothing merely to
  create room.

After validation, record the module firmware/version, safe sound-ID range, and
a user-confirmed inventory/free-memory observation. Only then may a separate
explicitly confirmed transfer command be introduced or used.

For this DDrum4 SE, the firmware version appears at power-on. `SHIFT` +
`MEM.LEFT` shows unused sound memory in blocks (for example `1.28` means 1,280
blocks); it is read-only. Do not use the adjacent mark/delete controls while
performing this observation.
