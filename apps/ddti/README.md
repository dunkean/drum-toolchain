# DDTi Editor

`ddti` is the desktop configuration application for the legacy 2016 ddrum
DDTi. It edits the 21 kits, their Tip/Ring MIDI routing, Program Change,
per-kit hi-hat routing, and the five decoded response settings for all 20
zones plus the hi-hat pedal. It also captures panel dumps, keeps a persistent
last-known state, imports/exports reusable YAML or JSON configurations, shows
exact binary diffs, and sends only hardware-validated fields.

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
ddti gui captures/factory_dump_002_full.golden.syx
ddti gui  # subsequent launches reopen the verified last-known state
ddti-editor  # equivalent desktop shortcut
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

The FastAPI service and PySide6 editor stage changes before any output. The
complete `ddti-configuration-preset/v1` document carries all 21 kits, all 20
Tip/Ring channel and note pairs per kit, Program Change, hi-hat pedal routing
and closed note, plus Gain, Velocity Curve, Threshold, X-Talk/Calibration and
Retrigger for all 21 global targets. The unresolved final byte of each global
record is exported for inspection as `trigger_type_raw`, remains read-only in
the GUI, and is deliberately ignored when a configuration is imported.
Velocity Curve offers the documented `Cst`, `OFF`, `E1`–`E4`, `Lin`,
`LG1`–`LG4` and `SPL1`–`SPL4` choices; ordinary X-Talk is constrained to
`0..7`, while the hi-hat record keeps its separate raw Calibration range.

Click **Synchroniser** and perform the documented panel dump to replace the
working state. A complete 42-frame capture is saved under `%LOCALAPPDATA%\DDTi
Editor`; later launches can use `ddti gui` without another dump. The DDTi has
no validated PC command that starts a dump, so the panel key combination is
still required when a fresh hardware read is actually needed. During the
three-minute listening window, the same button becomes **Annuler l’écoute**;
closing the application also cancels and joins the listener cleanly.

Offline editing and preset import cover more fields than the current hardware
write allowlist. **Envoyer au DDTi** refuses any unvalidated changed offset
before opening the MIDI output. Confirmed Note, Program Change and Input 1 Tip
values can already be sent; the remaining decoded fields will enter the same
writer only after their controlled round-trip validation on this DDTi.

The repository’s named `presets/gm.yaml` and `presets/sd3.yaml` are musical
role templates, not assumptions about cable wiring. Copy and fill
`presets/ddti-input-layout.example.yaml` with the exact physical Input/Tip/Ring
assignments for your kit and the exact target kit numbers. `apply-role-preset`
then creates a new staged dump. The GUI offers the same two-file flow through
**Mapping GM/SD3**. Neither flow opens a MIDI output.

Before exporting a staged file, the GUI’s **Voir les changements** button shows
the exact byte changes from the source dump. The local API exposes the same
review at `GET /staged-diff` and permits an integration to download the staged
file at `GET /staged-sysex`; those endpoints are output-free and explicitly
report `hardware_write: disabled`.

`ddti write-plan SOURCE CANDIDATE` validates that every changed byte belongs to
a confirmed field and prints the canonical candidate SHA-256 and semantic
diff. `ddti write-config` requires that exact hash, the token
`I_AUTHORIZE_DDTI_CONFIRMED_FIELDS`, and a minimum 50 ms frame interval. Any
unknown field mutation is rejected before a MIDI output is opened.
