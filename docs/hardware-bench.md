# DDrum4 Hardware Bench

The historical transfer bench used `MIDI4x4` for DDrum4 MIDI I/O. The current+permanent loop is documented in `ddrum4-midi-loop-modes.md`: DDrum4 OUT goes+to Arduino IN, Arduino THRU goes to UMC MIDI IN, and Arduino OUT goes to+DDrum4 IN. DDrum4 audio outputs 1/2 remain connected to UMC404HD inputs 1/2.+MIDI scripts resolve a unique port name; audio scan input `3` is the current+Windows UMC IN 1-2 device index and must be rechecked if interfaces change.

## Repeatable MIDI-input scan

`firmware/ddrum4-midi-bridge/tools/midi_probe.py` can correlate a MIDI note
grid with DDrum4 audio on UMC input 1–2 without saving a WAV or modifying the
module. It is for identifying the *currently active* MIDI input note/channel
after a palette or cabling change.

```powershell
# Scan every receiver note on MIDI channel 12; audio input 3 is UMC IN 1-2 on
# this Windows machine. The output port must be physically connected to the
# DDrum4 MIDI IN for this to be a hardware test.
python firmware/ddrum4-midi-bridge/tools/midi_probe.py `
  --send '^UMC404HD 192k MIDI Out 9$' --audio-input 3 `
  --scan-notes --channel 12 --note-start 0 --note-end 127 --slot-ms 400
```

The tool prints the RMS/peak score for each probe and does not infer a
successful module transfer merely because Windows accepted MIDI bytes. In the
current permanent Arduino loop, UMC MIDI OUT is **not** connected to DDrum4
MIDI IN, so this scan and a SysEx upload require either a temporary direct
connection or a future MIDI merger/proxy path.

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
