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
background, shows file-backed progress, runs the immutable-library quality
review, captures and validates simultaneous layered centers, and only then
exports or verifies DrumGizmo. The second tab can launch DDTi, ddrum4UI, Converter, and an
explicit SD3/DAW or DrumGizmo host; it displays and can request termination only
for applications it launched itself. Use **Complete chain simulator** to trace
a raw pad note through Scene/VP state, DDrum4 return MIDI, SD3, and DrumGizmo.
The virtual-kit workspace exposes positional NOTE P ranges as direct buttons;
for Snare2, `P1`…`P8` visibly drive SD3 CC16 and the DDrum4 three-zone result.
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

For the Greg Hybrid rig routed through the UMC MIDI input, the repository also
provides a receive-only guarded helper:

```powershell
.\scripts\capture-greg-hybrid-ddti-base.ps1 -ConfirmReceiveOnly
```

After initiating the complete dump from the DDTi panel, select the resulting
gitignored `local/ddti/greg-hybrid-base.syx` as **DDTi base dump** in Control
Center. Compile the rig, then choose **Stage DDTi notes from compiled role
template**. This combines the captured dump, generated stable-note roles and
`profiles/physical/greg-hybrid-ddti-layout.yaml`, writes a new review-only
`.syx`, and displays its semantic diff. It never opens a MIDI output or writes
the module.

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
file operations. `capture` and `capture-composites` are live: they send the
declared MIDI notes and record the declared audio input only when
`--confirm-capture` is supplied. Composite capture writes its own strict
quality report and is resumable by exact filename.
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

## Greg Hybrid Windows live session

After the physical measurement campaign has produced a `deployment: live`
project, generate the machine-local configuration with
`scripts/prepare-greg-hybrid-live.ps1`. `Launch-Greg-Hybrid-Live.cmd` then
runs a fail-closed preflight before starting the owned Converter and SD3
processes; a missing port, stale runtime hash, non-live profile, non-ready SD3
target or invalid power-plan GUID prevents every launch. The shortcut prefers
PowerShell 7 and remains compatible with Windows PowerShell 5.1.

`Stop-Greg-Hybrid-Live.cmd` restores the exact previous power plan and stops
only the recorded PIDs. The transient state is removed, while a persistent
JSON health report remains in `local/reports`: it records the configuration
and runtime hashes, read-only MIDI inventory, declared ASIO buffer, owned
processes and final restoration result. These reports are local and must not
be committed.

### Portable rehearsal/live laptop archive

`scripts/build-greg-hybrid-live-bundle.ps1` builds a Windows 11 x64 ZIP which
does not require Git, Python, CMake or a source checkout on the target laptop.
It embeds the official CPython 3.12 runtime, GUI/MIDI/audio dependencies pinned
to the exact Windows wheel SHA-256 and installed with `--require-hashes`,
all project tools and profiles, the Release Converter, a freshly compiled rig,
install/configure/diagnostic scripts and one-click launch/stop shortcuts. Every
file is recorded in `bundle-manifest.json`; installation verifies all SHA-256
values before copying to a versioned directory under
`%LOCALAPPDATA%\GregHybridLive`.
The builder itself requires PowerShell 7 on the development workstation; the
generated installer and launchers also support stock Windows PowerShell 5.1.
Before extraction, compare the ZIP with its adjacent `.zip.sha256` sidecar
obtained from the build workstation or another trusted channel. Internal
manifest verification protects the extracted payload, but is not a substitute
for authenticating the archive hash.

```powershell
# Shareable tool bundle; no proprietary or derived audio assets.
./scripts/build-greg-hybrid-live-bundle.ps1

# Personal migration archive for the owner's laptop only.
./scripts/build-greg-hybrid-live-bundle.ps1 -PrivateAssets
```

The private scope additionally embeds the approved user SD3 preset and the
validated DrumGizmo r5 kit. Its manifest marks both as non-redistributable; the
ZIP remains under ignored `build/releases` and must never be committed or
published. Toontrack applications/EZX libraries, hardware drivers and an
optional DrumGizmo host remain external licensed prerequisites.
The `tools-only` build also fails if its staged project payload contains an
`assets` directory, audio, SD3/eDRUMin/SysEx presets, or a recognizable kit
archive, so a future source-tree addition cannot silently leak into it.

The current pre-pad archive can install and run every editor/diagnostic, but
retains `post-flash-validation-pending`. `Configure-Live-Rig.cmd` and the live
launcher fail closed until the 75 physical proofs promote the packaged project
to `hardware-verified`. Rebuilding the same command from that promoted project
produces the final laptop archive.

## Safety summary

| Operation | Hardware effect | Confirmation |
|---|---|---|
| Control Center simulation/compile | None | Not required |
| DDTi monitor/dump | Receives MIDI only | Listener/operator action |
| Drum Sampler capture | Sends MIDI and records audio | `--confirm-capture` |
| DDrum4 backup listener | Receives MIDI/SysEx only | `--confirm-listening` |
| DDrum4 Sound transfer | Writes one Sound | `--confirm-hardware-write` |
| Arduino flashing | Writes firmware | Operator confirmation in protocol |
