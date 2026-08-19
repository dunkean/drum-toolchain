# DDTi safe reverse-engineering toolchain

`ddti` is the DDTi-specific, read-first application in the Drum Toolchain
monorepo.  It supports USB/MIDI discovery, traffic monitoring, raw SysEx
capture, integrity metadata, and offline binary diffs.  It deliberately has
no implemented configuration writer until the legacy DDTi protocol has been
confirmed from controlled dumps. An exact full-dump round-trip was tested once
and changed an unexplained field, so hardware writing is explicitly disabled.

Install it for the `ddti` command:

```powershell
python -m pip install -e apps/ddti
ddti devices
ddti info
```

Optional local interfaces are deliberately separate from the core library:

```powershell
python -m pip install -e 'apps/ddti[api,gui]'
ddti serve captures/factory_dump_001.syx
ddti gui captures/factory_dump_001.syx
```

Or run directly from a checkout:

```powershell
$env:PYTHONPATH = 'apps/ddti/src'
python -m ddti devices
python -m ddti monitor --input TriggerIO --output captures/monitor.jsonl
python -m ddti decode captures/factory_dump_001.syx
python -m ddti export-preset captures/factory_dump_001.syx presets/factory-notes.json
python -m ddti apply-preset captures/factory_dump_001.syx presets/factory-notes.json captures/factory-notes-staged.syx
python -m ddti transfer-plan captures/factory_dump_002_full.golden.syx
```

## First safe capture

No command sends MIDI or SysEx.  Start the listener first, then press
**FUNCTION UP** and **VALUE UP** simultaneously on the DDTi.  The legacy DDTi
owner's manual documents this as a transfer of all presets to the connected
SysEx application over USB or MIDI.  Do not use a firmware updater or send a
guessed request message.

```powershell
ddti dump captures/factory_dump_001 --input TriggerIO --listen --seconds 90 --idle-seconds 5
```

This produces `factory_dump_001.syx`, `.hex`, and `.json`.  Files are never
overwritten, and the metadata records SHA-256 hashes.  Once the first capture
exists, make two independent copies before any panel edit:

```powershell
Copy-Item captures/factory_dump_001.syx captures/factory_dump_001.golden.syx
Copy-Item captures/factory_dump_001.json captures/factory_dump_001.golden.json
```

See [`docs/DDTI_CAPTURE.md`](../../docs/DDTI_CAPTURE.md) for the exact safe
workflow and the hardware evidence currently known.

The FastAPI service and PySide6 editor both edit only an offline, staged dump.
They cover the 21 observed kits, expose confirmed MIDI notes and observed
channel bytes, and can export/import portable `ddti-note-preset/v1` JSON
presets. Channel and companion bytes remain read-only because their meaning is
not proven. No hardware-write path exists until the remaining protocol fields
are experimentally validated.

`ddti transfer-plan` is an offline review gate for a possible future transfer
path. It accepts only a complete 42-packet dump and displays its SHA-256; it
does not open a MIDI output or send any bytes. There is deliberately no
`ddti transfer` command while the observed round-trip mutation remains
unexplained.
