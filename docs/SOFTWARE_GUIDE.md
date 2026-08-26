# Software Guide

This page is a short English operator guide for the applications in this
workspace. Run commands from the repository root. The complete recording and
hardware qualification procedure is in [COMPLETE_TEST_PROTOCOL.md](COMPLETE_TEST_PROTOCOL.md).

## Common setup

```powershell
.\scripts\bootstrap.ps1
python -m pip install -e .
```

Use one application per MIDI input. Close DAWs, monitors, and editors that
already own a port before opening another live-MIDI application.

## Drum Control Center

**Purpose:** offline rig-project validation, compilation, reports, the complete
chain simulator, guided SD3 capture campaigns, and explicit launch/monitoring
of other applications. It does not open MIDI ports or send MIDI itself.

```powershell
python -m pip install -e 'apps/control-center[gui]'
drum-control-center validate profiles/projects/complete-chain-simulator.yaml
drum-control-center simulate profiles/projects/complete-chain-simulator.yaml --source ddrum4 --note 85 --velocity 106 --scene dnb
drum-control-center-gui
```

On Windows, double-click `Launch-Control-Center.cmd` in the repository root.
It starts the same GUI from the project virtual environment without opening a
terminal window.

For a new kit, start in **SD3 capture campaign**: select a campaign root, name
the SD3 preset and routing, review the complete articulation grid, and create
the versioned campaign. The same tab then starts confirmed capture in the
background, shows file-backed progress, runs quality review, and exports or
verifies DrumGizmo. The second tab can launch DDTi, ddrum4UI, Converter, and an
explicit SD3/DAW or DrumGizmo host; it displays and can request termination only
for applications it launched itself. Use **Complete chain simulator** to trace
a raw pad note through Scene/VP state, DDrum4 return MIDI, SD3, and DrumGizmo.
The supplied simulator project is synthetic and must never be copied to a
module. See [the Control Center README](../apps/control-center/README.md) for
the full workflow.

## DDTi Editor

**Purpose:** inspect, stage, compare, and—only after explicit confirmation—send
validated DDTi configuration fields. The GUI also has a receive-only live MIDI
pad test.

```powershell
python -m pip install -e 'apps/ddti[api,gui]'
ddti devices
ddti gui
```

For a first hardware read, start a listener and initiate the dump from the
DDTi panel; the tool must not guess or send a request SysEx message:

```powershell
ddti dump captures/initial --input TriggerIO --listen --seconds 90 --idle-seconds 5
```

Use **Synchronize** to receive a panel-initiated dump, **View changes** before
exporting staged data, and use a write only after reviewing its exact hash and
confirmation token. Details: [DDTi README](../apps/ddti/README.md) and
[DDTi capture workflow](DDTI_CAPTURE.md).

## ddrum4 Converter

**Purpose:** real-time MIDI conversion from DDrum4/declared sources to SD3 or
DrumGizmo. It supports a compiled runtime profile, local Scene/VP controls,
monitoring, and Panic. It does not make local state global without a proven
Master Merger route.

Build the Windows desktop version with Visual Studio tools:

```powershell
cmake --build build/modernizer-desktop-msvc --config Release --target ddrum4_converter
& 'build/modernizer-desktop-msvc/ddrum4_converter_artefacts/Release/ddrum4 Converter.exe'
```

In the application, select the raw MIDI input and the output port visible to
the renderer. Use **Start**, inspect **Monitor**, and use **Panic** when needed.
The application works from a compiled `runtime-profile.yaml`; the Control
Center can launch it with the profile explicitly selected. See the
[Converter README](../apps/ddrum4-modernizer/README.md).

## Drum Sampler

**Purpose:** create deterministic sample plans, capture confirmed SD3 MIDI and
audio sessions, quality-check immutable raw WAVs, and export/verify DrumGizmo
kits.

```powershell
python -m pip install -e apps/drum-sampler
drum-sampler --help
drum-sampler fixture --output build/sample-fixture.json
```

`plan`, `audit-quality`, `prepare-offline`, and `export-drumgizmo` are offline
file operations. `capture` is live: it sends the declared MIDI notes and
records the declared audio input only when `--confirm-capture` is supplied.
Retain the inventory, generated session, raw WAVs, report, and checksums as
described in the complete test protocol.

## DDrum4 Bank Builder

**Purpose:** inspect/build DDrum4 Sound assets offline, create reports, receive
manual backups, compare renders, and transfer exactly one Sound after an
explicit safety confirmation.

```powershell
python -m pip install -e apps/ddrum4-bank-builder
ddrum4-bank-builder discover
ddrum4-bank-builder --help
```

Most commands are offline. `receive-settings-backup` only opens an input after
`--confirm-listening`; start the dump manually on the module or UI.
`transfer-sound` opens a MIDI output only with `--confirm-hardware-write` and
writes a non-overwriting receipt after success. Back up settings and verify the
exact target, Sound ID, free memory, and output port before transfer.

## Supporting command-line tools

- `drum-toolchain` validates, compiles, and reports rig-project files. It is
  installed by `python -m pip install -e .`.
- `midi_lab` lists and observes MIDI devices. Use it for read-only discovery;
  do not run it beside another process reading the same input.
- PlatformIO builds/tests the Arduino bridge:

  ```powershell
  pio test -d firmware/ddrum4-midi-bridge -e native
  pio run -d firmware/ddrum4-midi-bridge
  ```

For a full Windows health check, run `./scripts/test-all.ps1`.

## Safety summary

| Operation | Hardware effect | Confirmation |
|---|---|---|
| Control Center simulation/compile | None | Not required |
| DDTi monitor/dump | Receives MIDI only | Listener/operator action |
| Drum Sampler capture | Sends MIDI and records audio | `--confirm-capture` |
| DDrum4 backup listener | Receives MIDI/SysEx only | `--confirm-listening` |
| DDrum4 Sound transfer | Writes one Sound | `--confirm-hardware-write` |
| Arduino flashing | Writes firmware | Operator confirmation in protocol |
