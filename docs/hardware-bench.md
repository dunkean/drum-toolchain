# DDrum4 Hardware Bench

The observed connection is `MIDI4x4` output to DDrum4 MIDI IN, `MIDI4x4` input
from DDrum4 MIDI OUT, and DDrum4 audio outputs 1/2 to UMC404HD inputs 1/2.
Scripts must resolve a unique name, never use a numeric device index.

## First action: settings backup

No test sound, SysEx request, sound upload, or bulk transfer may be sent until
a DDrum4 settings dump has been captured and validated. The repository does
not guess a request SysEx command. Start the dump manually from the module or
ddrum4UI, then run the receiver in a separate terminal:

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

After validation, record the module firmware/version, safe sound-ID range, and
a user-confirmed inventory/free-memory observation. Only then may a separate
explicitly confirmed transfer command be introduced or used.
