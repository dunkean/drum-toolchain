# DDTi Python API

The DDTi API is intentionally read-first.  It does not yet expose REST or GUI
layers because the required dump format and safe write framing are unknown.
Those layers will call this package rather than duplicate protocol logic once
the round-trip decoder is validated.

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

The `ddti` command provides the corresponding `devices`, `info`, `monitor`,
`dump`, `decode`, and `diff` commands.  There is deliberately no `set`,
`restore`, or `write` command yet.
