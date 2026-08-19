# DDTi Python API

The DDTi API is intentionally read-first. The local REST API and desktop GUI
operate on an explicit, already-captured dump; they never open a MIDI output or
write to the module. They call the central library rather than duplicate its
protocol decoding.

```python
from ddti import DDTi, discover_devices

devices = discover_devices()  # Windows/Python MIDI discovery only
device = DDTi.connect()
info = device.get_info()
```

`DDTi.read_configuration()` and `DDTi.write_configuration(...)` raise
`ProtocolNotValidatedError`.  This is an intentional safety boundary: neither
method opens an output port or sends any bytes.

Offline interfaces:

```python
from pathlib import Path
from ddti.diff import diff_files
from ddti.sysex import parse_stream

frames = parse_stream(Path("captures/factory_dump_001.syx").read_bytes())
differences = diff_files(Path("dump_a.syx"), Path("dump_b.syx"))
```

For the captured legacy DDTi framing, use the lossless structural decoder:

```python
from ddti import decode_dump

dump = decode_dump(Path("captures/factory_dump_001.syx").read_bytes())
assert b"".join(packet.raw for packet in dump.packets) == dump.raw
print(dump.family_indexes())  # {1: (0, ..., 20), 2: (0, ..., 10)}
```

The validated note model is available offline. `with_note` and
`encode_configuration` are useful for previews and tests only; their result is
not accepted by `DDTi.write_configuration`.

```python
from ddti import decode_configuration, encode_configuration

config = decode_configuration(dump)
assert config.kits[0].inputs[0].tip.note == 35
preview = config.with_note(0, 1, "tip", 36)
assert encode_configuration(preview) != encode_configuration(config)
```

The `ddti` command provides the corresponding `devices`, `info`, `monitor`,
`dump`, `decode`, and `diff` commands.  There is deliberately no `set`,
`restore`, or `write` command yet.

## Local REST API

Install `ddti[api]`, then run:

```powershell
ddti serve captures/factory_dump_001.syx
```

The service binds to `127.0.0.1:8765` by default and exposes:

| Method | Path | Behaviour |
| --- | --- | --- |
| GET | `/device`, `/device/status` | OS/MIDI discovery only |
| GET | `/configuration`, `/kits`, `/kits/{kit}` | decoded captured configuration |
| GET | `/kits/{kit}/inputs/{input}` | one decoded input |
| PATCH | `/kits/{kit}/inputs/{input}` | stage `tip_note` / `ring_note` in memory only |

The PATCH response explicitly states `hardware_write: disabled`. Restarting
the service discards staged changes unless they have been exported through the
offline GUI.

## Desktop GUI

Install `ddti[gui]`, then run `ddti gui captures/factory_dump_001.syx`.
The PySide6 editor provides a compact 10-input Tip/Ring table for Kit 0, staged
note editing, and a non-overwriting local file export. Its **Write to DDTi**
control is disabled by design.
