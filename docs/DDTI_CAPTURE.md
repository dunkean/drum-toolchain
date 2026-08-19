# DDTi capture workflow

This is the only permitted first hardware workflow for the DDTi.  It opens the
identified MIDI input (`TriggerIO 30`) and never opens `TriggerIO 10`.

1. Leave firmware tools closed.  Do not connect or run any sender.
2. In a terminal at the repository root, install the local app once:

   ```powershell
   python -m pip install -e apps/ddti
   ```

3. Start the passive capture listener:

   ```powershell
   ddti dump captures/factory_dump_001 --input TriggerIO --listen --seconds 90 --idle-seconds 5
   ```

4. Only after the listener says it is active, press **FUNCTION UP** and
   **VALUE UP** simultaneously on the DDTi front panel, then release both.
   The legacy [DDTi owner's manual](https://www.ddrum.com/images/manuals/DDTi%20manual.pdf)
   documents this exact combination as a Data Dump request which transfers all
   presets to the connected SysEx application over USB or MIDI.  This is a
   documented panel action, not a PC-to-DDTi SysEx command; the actual received
   bytes remain unverified until the capture finishes.
5. Do not press **VALUE DOWN**, do not power-cycle the DDTi, and do not use the
   simultaneous **VALUE UP + VALUE DOWN** power-on operation (factory reset).
6. Let the transfer complete and wait for the capture command to finish after
   five seconds of inactivity.
7. Inspect the three new artifacts and their SHA-256 hash:

   ```powershell
   Get-Content captures/factory_dump_001.json
   Get-Content captures/factory_dump_001.hex
   ```

8. Before changing a single panel value, create two byte-identical copies
   outside version control, one explicitly named `golden`:

   ```powershell
   Copy-Item captures/factory_dump_001.syx captures/factory_dump_001.golden.syx
   Copy-Item captures/factory_dump_001.syx $env:USERPROFILE\Documents\DDTi-backups\factory_dump_001.syx
   Get-FileHash captures/factory_dump_001.syx -Algorithm SHA256
   ```

`captures/*.syx` is deliberately ignored by Git.  Keep its metadata and any
facts subsequently confirmed in the documentation, but do not publish a
personal factory dump unless it is intentionally reviewed.

## Compact differential session

Use one long-running CLI process when collecting several controlled panel
changes. It does not send MIDI: each numbered snapshot opens the same
receive-only capture path, saves its own hash, then automatically waits for
the next manual dump.

```powershell
ddti session captures/channel-test --input TriggerIO --listen --label channel --snapshots 3 --seconds-per-snapshot 300
```

For every announced snapshot, perform **exactly one** documented panel edit,
return to `Kit` to save where required, then press `FUNCTION UP + VALUE UP` to
dump. Do not make a second edit until the next `snapshot n/m: listening` line.
At the end of a short experiment series, a factory reset followed by one final
capture is the quickest way to re-establish the known baseline.

## Controlled differential experiment (after the golden copy)

For the first comparison, change only **Kit 0, Input 1 Tip MIDI Note: 35 to
36**, using the module panel.  Do not touch another setting.  Capture as
`captures/kit0_input1_tip_note_35_to_36`, restore 35 on the panel, then
compare offline:

```powershell
ddti diff captures/factory_dump_001.syx captures/kit0_input1_tip_note_35_to_36.syx
```

Record changed offsets as `HYPOTHESIS`, not confirmed fields, in
[`REVERSE_ENGINEERING.md`](REVERSE_ENGINEERING.md).  The same candidate field
must be exercised with at least three values, two inputs, and (when relevant)
two kits before it becomes `CONFIRMED`.
