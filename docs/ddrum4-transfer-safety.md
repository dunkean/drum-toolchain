# DDrum4 B0 Transfer Safety

The B0 sound is a disposable transfer-path test, not a musical sound and not
part of the final bank. Its source is a deterministic, non-copyrighted,
short 44.1 kHz mono sine-decay WAV created locally by the bank-builder command.

```powershell
$env:PYTHONPATH = 'apps/ddrum4-bank-builder/src'
python -m ddrum4_bank.cli create-b0-fixture `
  --wav D:\Studio\ddrum4-b0\b0-click.wav `
  --manifest D:\Studio\ddrum4-b0\b0-click.json
```

The command has no MIDI implementation and cannot send anything to the module.
It refuses to overwrite either output and records the fixture hash and source
provenance in the JSON manifest.

After DDrum4UI has saved a local sound, verify it before any transmission:

```powershell
$env:PYTHONPATH = 'apps/ddrum4-bank-builder/src'
python -m ddrum4_bank.cli verify-b0-build `
  --fixture-manifest D:\Studio\ddrum4-b0\b0-click.json `
  --sound D:\Studio\ddrum4-b0\KICK_999.mid `
  --output D:\Studio\ddrum4-b0\KICK_999.build.json
```

This only invokes `ddrum4edit -p`, checks the fixture WAV hash and records the
actual encoded block count. It has no MIDI output path.

Before a human performs the one required ddrum4UI import/build/send operation,
record all of the following in the bench log:

1. DDrum4 firmware/version shown by the module.
2. Observed free-memory value and the screen/menu that reported it.
3. A user-approved, sacrificial User Sound ID. It must not contain a sound the
   user wants to retain.
4. The exact ddrum4UI/ddrum4edit version, operation and generated output file.
5. After transmission, the observed Sound ID, audible playback at several MIDI
   velocities, UMC recording path and actual encoded block count.

The module's software version is shown briefly at power-on. To observe free
memory without modifying a sound, press `SHIFT` + `MEM.LEFT`; record the
displayed block count exactly (for example, `1.28` means 1,280 blocks). Do not
use `SHIFT` + `MARK`, `DELETE`, or any `F.*` factory-initialization option.

Do not send a generated file merely because it has a `.mid`, `.midi`, or
`.syx` suffix. The current backend intentionally cannot build transfer files
until one manual, reproducible UI build identifies the correct format and
command semantics. Stop the queue on the first build, send, playback, or
recording failure.

## Timed MIDI-file replay

A DDrum4UI-authored `.mid` sound contains SysEx delta-times of about 376 ms
for B0, but these encode the serial-wire duration rather than the native
sender's actual spacing. A direct Windows-MM capture measured the DDrum4UI
sender at 400 ms between packets. Replay code therefore sends an all-SysEx
sound `.mid` at that observed 400 ms pace and does not also honour its SMF
delta-times. Applying both produced an approximately 776 ms gap and a module
`ERR` during the first characterization. Raw `.syx` files have no delta-times
and use the same explicit inter-message pause.

## Capturing a native DDrum4UI transfer on Windows

The command below records a manually initiated DDrum4UI SysEx send without
assuming that the stream is a settings backup. On Windows it uses enlarged
Windows-MM receive buffers; ordinary Python MIDI inputs can silently drop the
1,174-byte sound packets.

```powershell
$env:PYTHONPATH = 'apps/ddrum4-bank-builder/src'
python -m ddrum4_bank.cli record-sysex `
  --input 'in_dunk 14' `
  --output D:\Studio\ddrum4-b0\ddrum4ui-native.mid `
  --seconds 90 `
  --confirm-listening
```

With the recorder already listening, select `in_dunk` in the **Output port**
field of the DDrum4UI **Send to ddrum4** dialog and press **Start** once. This
never reaches the hardware module. The command refuses to overwrite a prior
capture.
