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

4. Only after the listener says it is active, perform the DDTi's documented
   **panel SysEx transmit/export** operation.  Do not use a guessed inbound
   request.  If the panel procedure is not known, stop here and consult the
   DDTi manual; this project has not yet verified a button sequence.
5. Let the transfer complete and wait for the capture command to finish after
   five seconds of inactivity.
6. Inspect the three new artifacts and their SHA-256 hash:

   ```powershell
   Get-Content captures/factory_dump_001.json
   Get-Content captures/factory_dump_001.hex
   ```

7. Before changing a single panel value, create two byte-identical copies
   outside version control, one explicitly named `golden`:

   ```powershell
   Copy-Item captures/factory_dump_001.syx captures/factory_dump_001.golden.syx
   Copy-Item captures/factory_dump_001.syx $env:USERPROFILE\Documents\DDTi-backups\factory_dump_001.syx
   Get-FileHash captures/factory_dump_001.syx -Algorithm SHA256
   ```

`captures/*.syx` is deliberately ignored by Git.  Keep its metadata and any
facts subsequently confirmed in the documentation, but do not publish a
personal factory dump unless it is intentionally reviewed.

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
