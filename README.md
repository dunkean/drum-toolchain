# Drum Toolchain

This monorepo contains the drum sampling, ddrum4 soundbank, MIDI conversion,
and Arduino bridge projects for the hybrid drum setup.

The implementation order is mandatory:

1. merge and validate the legacy projects;
2. establish a safe ddrum4 hardware backup/test bench;
3. build the sampler and ddrum4 bank builder;
4. create the soundbank;
5. validate ddrum4-to-modern MIDI conversion;
6. generate and validate the Arduino standalone bridge;
7. export the dense capture library to DrumGizmo.

Read [`docs/DRUM_TOOLCHAIN_EXECUTION_PLAN.md`](docs/DRUM_TOOLCHAIN_EXECUTION_PLAN.md)
before changing project structure or sending anything to the ddrum4.

Repository navigation and the boundary with the separate WORLDE project are
documented in [`docs/workspace-organization.md`](docs/workspace-organization.md).

## Applications

- `apps/drum-sampler`: MIDI-triggered audio capture and neutral sample-library export.
- `apps/ddrum4-bank-builder`: nested ddrum4 soundbank planning, building, validation, backup, and transfer.
- `apps/ddrum4-modernizer`: ddrum4 MIDI output to SD3/DrumGizmo-compatible MIDI conversion.
- `firmware/ddrum4-midi-bridge`: deterministic DDTi/eDRUMin-to-ddrum4 bridge for Arduino Uno.
- `tools/midi-lab`: MIDI monitoring, learning, trace recording, replay, and hardware probes.
- `apps/ddti`: desktop configuration editor for the legacy 2016 ddrum DDTi, with capture, reusable presets, exact diffs, persistent last-known state, and a confirmed-fields-only SysEx writer.
- `apps/control-center`: optional PySide/CLI launcher for offline rig validation, compilation, reports, and explicit existing-tool launches.
- `hardware/enclosures`: versioned mechanical artifacts for the Arduino MIDI
  bridge enclosure.

## Documentation

- `docs/hardware-and-kit-target.md`: concise English working specification.
- `docs/reference/hardware-inventory-original.fr.md`: complete original French
  hardware inventory and kit goals.
- `docs/REVERSE_ENGINEERING.md`: current DDTi reverse-engineering knowledge.
- `docs/history/ddti-reverse-engineering-plan-original.fr.md`: preserved
  original DDTi execution brief; historical, not the current implementation
  state.
- `docs/Drum_app_design.md`: current application-design draft, to be reviewed
  and finalized after the repository organization work.

The design document is versioned now, but its final review is intentionally
deferred until the active soundbank work has stabilized.

## Safety

No automated test may write to hardware. Any explicit hardware upload must be
preceded by a verified settings backup and must require a confirmation flag.

## Development install

Install the complete portable toolchain from the repository root. This registers
all project CLIs and does not require a manual `PYTHONPATH`.
On Windows this environment is also used to launch SD3-facing workflows and
the proprietary ddrum4UI/ddrum4edit tools.  On Linux/WSL, SD3 is treated as
unavailable; the portable MIDI, DDTi, eDRUMin, ddrum4 SysEx/DIN/USB, Converter,
firmware-core, bank-planning, and DrumGizmo export paths remain usable when the
local MIDI/audio backends are installed.

```powershell
python -m pip install -e .
python -m pip install -e packages/drum-domain -e tools/rig-compiler -e tools/midi-lab
python -m pip install -e apps/drum-sampler -e apps/ddrum4-bank-builder
python -m pip install -e 'apps/ddti[gui]'
python -m pip install -e 'apps/control-center[gui]'
```

## Verification

On Windows, run `./scripts/test-all.ps1` from the repository root. It creates or reuses
the ignored project-local `.venv` with Python 3.12, installs the workspace and
`apps/ddti[api,gui]` from their declared project metadata, then runs the
offline DDTi safety suite explicitly before the complete Python, firmware-core
and modernizer-core checks. It does not open MIDI ports or send hardware data.
Dependency installation is cached from the three Python project manifests;
pass `-RefreshEnvironment` only when the environment itself must be rebuilt.

On Linux or WSL, run:

```sh
scripts/bootstrap.sh --install
scripts/test-all.sh
```

The POSIX test path uses the same ignored `.venv`, validates the Python suites,
builds the Converter core without the JUCE app, and compiles the Arduino bridge
core with `g++`. It does not require SD3, ddrum4UI, ddrum4edit, PlatformIO, or
live MIDI hardware. Use `scripts/test-modernizer-core.sh` and
`scripts/test-firmware-core.sh` for the two native core checks independently.
Run `scripts/live-preflight.sh` on a Linux machine with the MIDI/audio stack
installed before attempting a DrumGizmo session. It is read-only and reports
missing ALSA/JACK, DrumGizmo, or Python MIDI prerequisites. WSL needs USB MIDI
and the ALSA sequencer exposed before it can see physical MIDI ports.

### WSL USB MIDI

Windows owns the UMC404HD while SD3 uses its ASIO driver. Do not attach the UMC
to WSL during an SD3 session. For Linux MIDI validation, attach only the USB
controllers that are not required by Windows, such as an eDRUMin, DDTi, or the
Arduino bridge. Install `usbipd-win` from an elevated Windows terminal, inspect
the read-only report, then bind and attach each selected bus ID:

```powershell
.\scripts\wsl-usb-status.ps1
usbipd list
usbipd bind --busid <BUSID>
usbipd attach --wsl --busid <BUSID>
```

`bind` requires elevation and persists the sharing decision; `attach` does not.
After attachment, return to WSL and require all of the following before opening
any live session:

```sh
test -e /dev/snd/seq
aconnect -l
scripts/live-preflight.sh
```

The WSL user must also be able to read `/dev/snd/controlC0`. If it is owned by
the `audio` group, run the following once, then fully restart WSL from Windows
with `wsl --shutdown`:

```sh
sudo usermod -aG audio "$USER"
```

The stock WSL kernel can expose USB raw MIDI while still disabling
`CONFIG_SND_SEQUENCER`. In that state `amidi` can prove a device transport, for
example with `scripts/capture-raw-midi.sh --port hw:0,0,0 --seconds 30 --output
build/triggerio-midi.hex`, but RtMidi, JUCE Linux MIDI, `aconnect`, `a2jmidid`,
and JACK MIDI cannot run. The full Linux live stack requires native Linux or a
custom WSL kernel with ALSA sequencer support enabled. The custom kernel path is
configured globally in `%UserProfile%\\.wslconfig`; keep it as an explicit,
versioned local host configuration rather than committing it to this repository.

For a separate DrumGizmo audio test, stop SD3, attach the UMC temporarily, and
verify its ALSA card and JACK ports. Detach it again before returning to the
Windows ASIO workflow. This handoff is exclusive by design; Windows ASIO and
WSL ALSA cannot own the same UMC concurrently.

For a Linux DrumGizmo session, copy
`profiles/live-session.drumgizmo.example.json`, replace every path and JACK
port name after inspecting the live graph, then run:

```sh
scripts/start-live.sh --config profiles/live-session.drumgizmo.json \
  --state-file build/live-session-drumgizmo.json --confirm-start
scripts/stop-live.sh --state-file build/live-session-drumgizmo.json
```

The launcher starts `a2jmidid -e`, then `drumgizmo -i jackmidi -o jackaudio`,
passes the compiled runtime profile and `drumgizmo` renderer target to the
Converter, and creates only the explicitly declared JACK MIDI and audio
connections. It owns and stops only the PIDs written to its state file.
