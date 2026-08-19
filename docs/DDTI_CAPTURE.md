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

### Independent receiver cross-check

On Windows, `ddti dump` normally uses large native long-message buffers. To
verify a capture with an independent receive path, repeat a panel-initiated
dump to a **new** filename with the portable `python-rtmidi` receiver:

```powershell
ddti dump captures/receiver_crosscheck --input TriggerIO --listen --receiver mido --seconds 90 --idle-seconds 5
```

This remains receive-only. `--receiver mido` exists solely to compare the raw
stream with the native Windows receiver; it never opens an output MIDI port.

## Compact differential session

Use one long-running CLI process when collecting several controlled panel
changes. It does not send MIDI: each numbered snapshot opens the same
receive-only capture path, saves its own hash, then automatically waits for
the next manual dump.

```powershell
ddti session captures/channel-test --input TriggerIO --listen --label channel --snapshots 3 --seconds-per-snapshot 300 --compare-to captures/factory_dump_002_full.golden.syx
```

For every announced snapshot, perform **exactly one** documented panel edit,
return to `Kit` to save where required, then press `FUNCTION UP + VALUE UP` to
dump. Do not make a second edit until the next `snapshot n/m: listening` line.
At the end of a short experiment series, a factory reset followed by one final
capture is the quickest way to re-establish the known baseline.

`--compare-to` is offline-only: after the final snapshot it prints the
structural byte diff of every capture against the supplied golden dump. It
never opens an output MIDI port or sends a request to the DDTi.

### Minimum Gain / Threshold campaign

With the verified factory dump as baseline, three panel dumps are enough for
an initial attribution while retaining a final recovery proof. Start this
single listener and wait for each numbered prompt:

```powershell
ddti session captures/gain-threshold-test --input TriggerIO --listen --label gain_threshold --snapshots 3 --seconds-per-snapshot 300 --compare-to captures/factory_dump_002_full.golden.syx
```

1. At snapshot 1, change only Kit 0 / Input 1 Gain from `15` to `16`, save as
   required by the panel, then press **FUNCTION UP + VALUE UP**.
2. At snapshot 2, restore Gain to `15`, change only Threshold from `5` to `6`,
   save, then dump. Its comparison with the golden dump proves whether the
   gain restoration was exact before interpreting the Threshold change.
3. At snapshot 3, factory reset using the documented power-on panel action,
   then dump. It must have no byte differences from the golden dump.

The 2026-08-19 final-reset verification was byte-identical to
`factory_dump_001.golden.syx` (1,836 bytes, SHA-256
`504ebd7e1a82b98c9b515febb8f3713a7a801ac5e1bbe188fad50370c42c33ce`).

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
