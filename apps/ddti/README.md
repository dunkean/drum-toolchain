# DDTi safe reverse-engineering toolchain

`ddti` is the DDTi-specific, read-first application in the Drum Toolchain
monorepo.  It supports USB/MIDI discovery, traffic monitoring, raw SysEx
capture, integrity metadata, and offline binary diffs.  It deliberately has
no implemented configuration writer until the legacy DDTi protocol has been
confirmed from controlled dumps.

Install it for the `ddti` command:

```powershell
python -m pip install -e apps/ddti
ddti devices
ddti info
```

Or run directly from a checkout:

```powershell
$env:PYTHONPATH = 'apps/ddti/src'
python -m ddti devices
python -m ddti monitor --input TriggerIO --output captures/monitor.jsonl
```

## First safe capture

No command sends MIDI or SysEx.  Start the listener first, then trigger the
DDTi's *documented panel dump/export operation*.  Do not guess a request
message and do not use an update utility.

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
