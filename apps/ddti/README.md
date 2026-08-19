# DDTi safe reverse-engineering toolchain

`ddti` is the DDTi-specific, read-first application in the Drum Toolchain
monorepo.  It supports USB/MIDI discovery, traffic monitoring, raw SysEx
capture, integrity metadata, offline binary diffs, and a confirmed-fields-only
configuration writer. Controlled transfers were returned byte-identically for
MIDI Note, Program Change, and Input 1 Tip Gain. Unrestricted raw writes remain
disabled.

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
python -m ddti export-config captures/factory_dump_002_full.golden.syx presets/my-sd3.yaml --name "My SD3 mapping"
python -m ddti apply-config captures/factory_dump_002_full.golden.syx presets/my-sd3.yaml captures/my-sd3-staged.syx
Copy-Item presets/ddti-input-layout.example.yaml presets/my-ddti-layout.yaml
python -m ddti apply-role-preset captures/factory_dump_002_full.golden.syx presets/sd3.yaml presets/my-ddti-layout.yaml captures/sd3-staged.syx
python -m ddti transfer-plan captures/factory_dump_002_full.golden.syx
```

## First safe capture

The `dump` command never sends MIDI or SysEx. Start the listener first, then press
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
They cover the 21 observed kits, expose confirmed MIDI notes, per-kit Program
Change (`---` or `0..127`), the confirmed Input 1 Tip Gain byte, and observed raw channel bytes. They can export/import
portable `ddti-note-preset/v1` JSON and complete
`ddti-configuration-preset/v1` YAML/JSON presets. Channel, Trigger Type,
Threshold, and companion bytes remain read-only because their meaning or scope
is not proven. The writer accepts only the confirmed editable subset.

The repository’s named `presets/gm.yaml` and `presets/sd3.yaml` are musical
role templates, not assumptions about cable wiring. Copy and fill
`presets/ddti-input-layout.example.yaml` with the exact physical Input/Tip/Ring
assignments for your kit and the exact target kit numbers. `apply-role-preset`
then creates a new staged dump. The GUI offers the same two-file flow through
**Apply GM/SD3 role preset**. Neither flow opens a MIDI output.

Before exporting a staged file, the GUI’s **Review staged diff** button shows
the exact byte changes from the source dump. The local API exposes the same
review at `GET /staged-diff` and permits an integration to download the staged
file at `GET /staged-sysex`; those endpoints are output-free and explicitly
report `hardware_write: disabled`.

`ddti write-plan SOURCE CANDIDATE` validates that every changed byte belongs to
a confirmed field and prints the canonical candidate SHA-256 and semantic
diff. `ddti write-config` requires that exact hash, the token
`I_AUTHORIZE_DDTI_CONFIRMED_FIELDS`, and a minimum 50 ms frame interval. Any
unknown field mutation is rejected before a MIDI output is opened.
