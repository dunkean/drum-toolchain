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

The validated offline model exposes Kit/Input/Tip-or-Ring notes plus the
controlled-evidence Input 1 Tip Gain field. `with_note`,
`with_input_1_tip_gain`, and `encode_configuration` are useful for previews
and tests only; their result is not accepted by `DDTi.write_configuration`.

```python
from ddti import decode_configuration, encode_configuration

config = decode_configuration(dump)
assert config.kits[0].inputs[0].tip.note == 35
preview = config.with_note(0, 1, "tip", 36)
assert encode_configuration(preview) != encode_configuration(config)

# The one gain byte whose location was verified by a panel 15 -> 16 change.
preview = config.with_input_1_tip_gain(16)
```

The `ddti` command provides the corresponding `devices`, `info`, `monitor`,
`dump`, `session`, `decode`, and `diff` commands.  It also supports an
offline-only note-preset exchange:

```powershell
ddti export-preset captures/factory_dump_001.syx presets/factory-notes.json
ddti apply-preset captures/factory_dump_001.syx presets/factory-notes.json captures/factory-notes-staged.syx
ddti export-config captures/factory_dump_002_full.golden.syx presets/my-sd3.yaml --name "My SD3 mapping"
ddti apply-config captures/factory_dump_002_full.golden.syx presets/my-sd3.yaml captures/my-sd3-staged.syx
```

`export-preset` writes all confirmed Tip/Ring MIDI notes in the portable
`ddti-note-preset/v1` JSON format. `apply-preset` accepts a full or partial
preset and creates a *new* staged `.syx` file; it refuses to overwrite files
and never opens a MIDI output. There is deliberately no `set`, `restore`, or
hardware `write` command yet.

`export-config` creates a human-editable `ddti-configuration-preset/v1` YAML
(or JSON) file containing every proven editable field: all kit notes and Input
1 Tip Gain. `apply-config` applies only these named fields to a new staged
dump, preserving every unknown byte from its supplied source dump. It also
never opens MIDI.

## Named GM / SD3 mappings

`presets/gm.yaml` and `presets/sd3.yaml` use
`ddti-note-role-template/v1`: they name musical roles and notes but deliberately
do **not** claim which DDTi socket is kick, snare, or hi-hat. Create a copy of
`presets/ddti-input-layout.example.yaml`, add only your observed physical
bindings, then stage it offline:

```powershell
ddti apply-role-preset captures/factory_dump_002_full.golden.syx presets/sd3.yaml presets/my-ddti-layout.yaml captures/sd3-staged.syx
```

The layout selects exact kit numbers and uses bindings such as
`{input: 2, zone: ring, role: snare.ring}`. Duplicate Input/zone bindings,
unknown roles, and unknown kits are rejected. This protects against silently
using a generic SD3 template with a guessed physical layout.

`ddti transfer-plan complete-dump.syx` validates that a file contains the full
21-kit plus 21-global-record transfer and prints its hash, packet count and
review state. It is deliberately output-free; it is the gate that a future
explicitly confirmed hardware transfer will use.

There is deliberately no CLI hardware transfer. The one authorised exact
golden-dump round trip changed an unknown Family-01 field; the review plan and
the public device facade are therefore hard-disabled for output until that
normalisation is understood.

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
| GET | `/staged-diff` | byte-level comparison between source dump and staging; sends nothing |
| GET | `/staged-sysex` | download the staged `.syx` file for offline backup/integration only |
| GET | `/kits/{kit}/inputs/{input}` | one decoded input |
| PATCH | `/kits/{kit}/inputs/{input}` | stage `tip_note` / `ring_note` in memory only |
| PATCH | `/global-trigger/input-1/tip` | stage the confirmed `gain` field in memory only |
| GET | `/preset` | export the current `ddti-note-preset/v1` document |
| PUT | `/preset` | stage a full or partial note-preset document in memory only |
| GET/PUT | `/configuration-preset` | export/stage all proven editable values in `ddti-configuration-preset/v1` form |
| POST | `/role-template` | stage a `ddti-note-role-template/v1` plus explicit `ddti-input-layout/v1` binding document |
| GET | `/transfer/plan` | validate and review the complete staged transfer; sends nothing |

The PATCH response explicitly states `hardware_write: disabled`. Restarting
the service discards staged changes unless they have been exported through the
offline GUI. `GET /staged-sysex` is intentionally a download only: it returns
the currently staged bytes with `X-DDTi-Hardware-Write: disabled`, and never
opens a MIDI output.

## Desktop GUI

Install `ddti[gui]`, then run `ddti gui captures/factory_dump_001.syx`.
The PySide6 editor provides a Kit selector for every decoded kit, a compact
10-input Tip/Ring note table, the confirmed Input 1 Tip Gain control, and
non-overwriting export of either the staged SysEx, a note preset, or a YAML
configuration preset. It can import either preset form into memory. Its
**Review staged diff** control shows the exact byte-level changes before an
export; **Write to DDTi** remains disabled by design.
