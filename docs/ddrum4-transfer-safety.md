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

The initial manual DDrum4UI operation has now been replaced by a verified
`ddrum4edit` command-line round-trip. Before any new hardware build/send
operation, record all of the following in the bench log:

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
`.syx` suffix. `Ddrum4EditBackend.build()` accepts only an auditable `.cfg`
whose declared output path exactly matches the requested target, refuses an
existing output, and re-inspects the encoded block count after building. Stop
the queue on the first build, send, playback, or recording failure.

## Timed MIDI-file replay

A DDrum4UI-authored `.mid` sound contains SysEx delta-times of about 376 ms
for B0, but these encode the serial-wire duration rather than the native
sender's actual spacing. A direct Windows-MM capture measured the DDrum4UI
sender at about 400 ms between packets. Replay therefore sends an all-SysEx
sound `.mid` at that explicit pace and does not also honour its SMF
delta-times. Raw `.syx` files have no delta-times and use the same explicit
inter-message pause.

The three `FF` short events observed beside a DDrum4UI send to a *virtual*
loopback port are Windows/port-reset artefacts, not members of the 11-packet
sound file. They must not be injected around a physical DDrum4 transfer: a
MIDI System Reset can abort the module receiver before its Flash commit.

### MIDI interface compatibility and fragmentation

The connected MIDIPLUS/Miditech MIDI4x4 reports firmware `1.02` and is known
to mishandle Windows SysEx messages above roughly 255 bytes. A DDrum4UI sound
packet is 1,174 bytes. The transfer transport therefore has an explicit
Windows diagnostic mode that fragments an existing SysEx stream into 255-byte
pieces, keeps the single initial `F0` and final `F7`, waits for each fragment
to clear at MIDI wire speed, and retains the 400 ms packet cadence. This is a
transport adaptation only; it never alters the encoded sound bytes.

For the B0 bench, the DDrum4 was reconnected through `UMC404HD MIDI Out 9` /
`UMC404HD MIDI In 29`. The module displayed the expected B0 block countdown
when sent with 255-byte fragments and no injected System Reset. `KICK_999`
was then heard through `SHIFT + LISTEN`. A real SD3-derived snare was built
and loaded as `SNRE_999` (one source layer, 137 blocks), proving the complete
capture-to-module path. A seven-layer velocity-crossfade candidate was then
built as `SNRE_998` (94 blocks); its runtime velocity sweep remains the B1
listening test.

On Windows, DDrum4UI uses the WinMM `midiOutLongMsg` API. All-SysEx sound
transfers use the same native API rather than the general Python MIDI backend.
The latter can carry the bytes through a virtual port but was rejected by the
physical DDrum4 even with identical framing and timing.

## Single-sound hardware write receipt

`transfer-sound` is the only bank-builder CLI command that writes a sound to
hardware. It deliberately accepts exactly one file, requires
`--confirm-hardware-write`, and creates its JSON receipt only after the native
sender has reported a non-zero message count. It is not a batch uploader: read
`SHIFT + MEM.LEFT`, confirm the intended Sound ID, and run it separately for
each candidate. For the UMC route, do not request fragmentation; reserve
`--sysex-chunk-bytes 255` for diagnosing the Midiface limitation.

```powershell
$env:PYTHONPATH = 'apps/ddrum4-bank-builder/src'
python -m ddrum4_bank.cli transfer-sound D:\Studio\ddrum4-b3\rim-999\RIM_999.mid `
  --output 'UMC404HD 192k MIDI Out 9' `
  --receipt D:\Studio\ddrum4-b3\rim-999\transfer-receipt.json `
  --confirm-hardware-write
```

## B1 source-versus-module comparison

After recording a module velocity or positional-sweep WAV through the UMC,
compare it with the corresponding original SD3 capture without rewriting
either file. The report measures onset offset, peak-level delta, decay/tail,
spectral-centroid delta and pre-onset module noise. It records facts, not a
musical pass/fail verdict; audition remains mandatory for layer gaps and
musical timbre.

```powershell
$env:PYTHONPATH = 'apps/ddrum4-bank-builder/src'
python -m ddrum4_bank.cli compare-render `
  --source D:\Studio\sample-library\source.wav `
  --module D:\Studio\ddrum4-b1\module-render.wav `
  --output D:\Studio\ddrum4-b1\render-comparison.json
```

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
