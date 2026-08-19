# DDTi Python API

The DDTi API remains read-first and operates on an explicit captured source
dump. The REST API and desktop GUI stage changes before output, then call the
central confirmed-fields validator rather than duplicating protocol logic.

```python
from ddti import DDTi, discover_devices

devices = discover_devices()  # Windows/Python MIDI discovery only
device = DDTi.connect()
info = device.get_info()
```

`DDTi.read_configuration()` still raises `ProtocolNotValidatedError` because
the dump is initiated from the panel. `DDTi.write_configuration(...)` accepts
an explicit source dump, reviewed candidate hash and confirmation token; it
rejects every mutation outside the confirmed-field allowlist before opening
MIDI.

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

The validated offline model exposes Kit/Input/Tip-or-Ring notes, per-kit
Program Change, plus the controlled-evidence Input 1 Tip Gain field. `with_note`,
`with_program_change`, `with_input_1_tip_gain`, and `encode_configuration` are
used for staging. Hardware output additionally requires source-relative field
validation, candidate-hash review and explicit confirmation.

```python
from ddti import decode_configuration, encode_configuration

config = decode_configuration(dump)
assert config.kits[0].inputs[0].tip.note == 35
preview = config.with_note(0, 1, "tip", 36)
assert encode_configuration(preview) != encode_configuration(config)

# The one gain byte whose location was verified by a panel 15 -> 16 change.
preview = config.with_input_1_tip_gain(16)
preview = config.with_program_change(0, None)  # panel `---`, canonical 01 00
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
and never opens a MIDI output. Hardware writing uses the separate `write-plan`
and `write-config` review flow described below.

`export-config` creates a human-editable `ddti-configuration-preset/v1` YAML
(or JSON) file containing every proven editable field: all kit notes, Program
Change, and the five isolated Input 1 Tip settings. `apply-config` applies only these named fields to a new staged
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

`ddti transfer-plan complete-dump.syx` validates raw structural completeness
only and remains output-free. It is not sufficient to authorise hardware
output; `write-plan` performs the required source-relative field validation.

The safe CLI writer is a two-step review flow:

```powershell
ddti write-plan source.syx candidate.syx
ddti write-config source.syx candidate.syx --output TriggerIO --expected-sha256 <hash-from-plan> --confirm I_AUTHORIZE_DDTI_CONFIRMED_FIELDS
```

Only confirmed kit notes, Program Change, and observed Input 1 Tip values may
differ. The accepted trigger pairs are Gain `15/16`, Curve `6/7` (`Lin/LG1`),
Threshold `5/7`, X-Talk `1/4`, and Retrigger `10/14`. The transfer uses at least 50 ms between frames. Unrestricted raw
SysEx replay remains unavailable.

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
| PATCH | `/kits/{kit}` | stage `program_change` (`null` for panel `---`, otherwise `0..127`) |
| PATCH | `/global-trigger/input-1/tip` | stage any subset of `gain`, `velocity_curve`, `threshold`, `xtalk`, `retrigger` in memory only |
| GET | `/preset` | export the current `ddti-note-preset/v1` document |
| PUT | `/preset` | stage a full or partial note-preset document in memory only |
| GET/PUT | `/configuration-preset` | export/stage all proven editable values in `ddti-configuration-preset/v1` form |
| POST | `/role-template` | stage a `ddti-note-role-template/v1` plus explicit `ddti-input-layout/v1` binding document |
| GET | `/write-plan` | validate changed offsets and return candidate hash plus diff |
| POST | `/write` | send only the validated candidate with exact hash and confirmation token |
| GET | `/transfer/plan` | validate and review the complete staged transfer; sends nothing |

The PATCH response explicitly states `hardware_write: disabled`. Restarting
the service discards staged changes unless they have been exported through the
offline GUI. `GET /staged-sysex` is intentionally a download only: it returns
the currently staged bytes with `X-DDTi-Hardware-Write: disabled`, and never
opens a MIDI output.

## Desktop GUI

Install `ddti[gui]`, then run `ddti gui captures/factory_dump_001.syx`.
The PySide6 editor provides a Kit selector for every decoded kit, a compact
10-input Tip/Ring note table, five Input 1 Tip controls, and
non-overwriting export of either the staged SysEx, a note preset, or a YAML
configuration preset. It can import either preset form into memory. Its
**Review staged diff** shows the exact byte-level changes. **Write confirmed
fields to DDTi** re-runs the allowlist validation, presents the hash and diff,
and requires an explicit confirmation before sending 42 frames.
