# Drum Toolchain: Repository Merge and Execution Plan

> Organization status (2026-08-20): the merge described by this document is
> complete. Sections describing the original workspace are historical. Use
> [`workspace-organization.md`](workspace-organization.md) for the current
> repository and archive layout.

## 1. Purpose

This document is the execution specification for reorganizing the existing drum-related projects into one maintainable monorepo and then building the ddrum4 soundbank workflow.

The mandatory order is:

1. Preserve and baseline the existing projects.
2. Merge the drum projects into the new monorepo.
3. Prove that all migrated behavior still works.
4. Establish a safe ddrum4 hardware test and backup procedure.
5. Build the sampler and ddrum4 bank compiler.
6. Create and optimize the standalone ddrum4 soundbank.
7. Adapt the modern MIDI converter.
8. Generate and validate the Arduino bridge.
9. Complete the DrumGizmo exporter and four-output workflow.

Soundbank implementation must not begin before the repository merge gate in section 9 has passed.

The user wants as little manual intervention as possible. Prefer reproducible commands, generated files, automated validation, and hardware probes over instructions that require repeated manual editing.

## 2. Current Workspace

Workspace root:

```text
D:\Workspace\Self\Studio
```

Existing projects:

```text
arduino_midi_router/
ddrum4_converter/
WORLDE_helpers/
Infos.md
```

Important facts:

- None of the three existing project directories is currently a Git repository.
- `arduino_midi_router` is approximately 1.85 GB because it contains build products, installers, manuals, factory banks, and downloaded dependencies.
- `ddrum4_converter` is approximately 774 MB because it contains multiple CMake build trees and downloaded JUCE dependencies.
- `WORLDE_helpers` is unrelated to the immediate drum work and must remain separate.
- Do not delete, overwrite, or destructively move the original directories during the merge.
- Create the monorepo as a new sibling directory and copy only source-controlled material into it.

## 3. Existing Project Assessment

### 3.1 `arduino_midi_router`

This directory currently mixes several responsibilities:

- Arduino Uno MIDI firmware;
- YAML-to-C++ mapping generation;
- MIDI probe utilities;
- soundbank planning and memory reports;
- audio capture and WAV preparation;
- ddrum4UI and `ddrum4edit` integration;
- MIDI/SysEx transport;
- a Tkinter control surface;
- manuals, installers, and factory reference files.

Relevant source locations:

```text
arduino_midi_router/
├── ddrum4kit/
│   ├── audio.py
│   ├── cli.py
│   ├── ddrum4ui.py
│   ├── gui.py
│   ├── project.py
│   ├── report.py
│   └── transport.py
├── include/
│   ├── DdrumBridge.h
│   ├── MidiDinAdapter.h
│   └── generated_mapping.h
├── src/
│   ├── DdrumBridge.cpp
│   ├── MidiDinAdapter.cpp
│   └── main.cpp
├── tools/
│   ├── generate_mapping.py
│   ├── midi_probe.py
│   └── launch_ddrum4kit_ui.cmd
├── test/
│   ├── test_bridge/
│   └── test_ddrum4kit.py
├── config/
├── docs/
├── platformio.ini
└── pyproject.toml
```

Current Python baseline:

```powershell
cd D:\Workspace\Self\Studio\arduino_midi_router
python -m unittest discover -s test -p 'test_*.py' -v
```

Expected baseline: seven tests pass.

PlatformIO was not available through the short `pio` command during the audit. The previously documented executable is:

```text
C:\Users\grego\AppData\Roaming\Python\Python313\Scripts\pio.exe
```

Do not assume this path forever. Discover it first, then support an explicit override.

### 3.2 `ddrum4_converter`

This is a C++23/JUCE real-time MIDI application that currently supports:

- simple note mapping;
- ddrum4 positional note ranges converted to a destination note plus CC;
- continuous and discrete hi-hat translation;
- Polyphonic Aftertouch routing using an active-note ledger;
- Program Change based virtual kits;
- profile validation and a compact JUCE UI.

Relevant locations:

```text
ddrum4_converter/
├── src/
│   ├── app/
│   ├── cli/
│   ├── config/
│   └── core/
├── tests/
├── config/
├── CMakeLists.txt
├── README.md
└── DESIGN_SPECIFICATION.md
```

The existing test executable passes when run with the expected working directory:

```powershell
cd D:\Workspace\Self\Studio\ddrum4_converter\build-core
.\ddrum4_core_tests.exe
```

The migrated project must be validated with a clean CMake build, not by copying `build-core` or `build-app`.

### 3.3 `WORLDE_helpers`

This project is out of scope for the initial monorepo. Leave it untouched.

It may later become a DAW or drum-toolchain control surface, but no drum-toolchain package may depend on it during the current roadmap.

## 4. Target Monorepo

Create:

```text
D:\Workspace\Self\Studio\drum-toolchain
```

Target layout:

```text
drum-toolchain/
├── README.md
├── LICENSE
├── .gitignore
├── pyproject.toml
├── CMakeLists.txt
├── docs/
│   ├── architecture.md
│   ├── hardware-bench.md
│   ├── repository-migration.md
│   ├── ddrum4-format-notes.md
│   ├── ddrum4-transfer-safety.md
│   ├── capture-workflow.md
│   └── soundbank-strategy.md
│
├── contracts/
│   ├── schemas/
│   │   ├── physical-kit.schema.json
│   │   ├── wiring-profile.schema.json
│   │   ├── capture-session.schema.json
│   │   ├── sample-library.schema.json
│   │   ├── target-profile.schema.json
│   │   ├── ddrum4-bank.schema.json
│   │   └── routing-contract.schema.json
│   └── generated/
│
├── profiles/
│   ├── physical/
│   │   └── greg-hybrid-kit.yaml
│   ├── wiring/
│   │   ├── snare-via-ddrum4.yaml
│   │   ├── snare-via-edrumin.yaml
│   │   └── snare-via-ddti.yaml
│   ├── capture/
│   │   ├── sd3-stereo.yaml
│   │   └── external-module-stereo.yaml
│   ├── targets/
│   │   ├── ddrum4-standalone.yaml
│   │   ├── superior-drummer-3.yaml
│   │   └── drumgizmo.yaml
│   ├── banks/
│   │   ├── metalcore-main.yaml
│   │   ├── deftones-variant.yaml
│   │   ├── sleep-token-variant.yaml
│   │   └── electro-dnb.yaml
│   └── setups/
│       ├── ddrum4-soundbank-development.yaml
│       ├── ddrum4-standalone-edrumin-snare.yaml
│       └── sd3-live.yaml
│
├── packages/
│   └── drum-domain/
│       ├── src/drum_domain/
│       │   ├── physical.py
│       │   ├── events.py
│       │   ├── samples.py
│       │   ├── profiles.py
│       │   ├── validation.py
│       │   └── serialization.py
│       └── tests/
│
├── apps/
│   ├── drum-sampler/
│   │   ├── src/drum_sampler/
│   │   │   ├── cli.py
│   │   │   ├── devices.py
│   │   │   ├── scheduler.py
│   │   │   ├── recorder.py
│   │   │   ├── processing.py
│   │   │   ├── quality.py
│   │   │   ├── session.py
│   │   │   └── exporters/
│   │   │       ├── drumgizmo.py
│   │   │       └── neutral_library.py
│   │   └── tests/
│   │
│   ├── ddrum4-bank-builder/
│   │   ├── src/ddrum4_bank/
│   │   │   ├── cli.py
│   │   │   ├── model.py
│   │   │   ├── nested.py
│   │   │   ├── allocator.py
│   │   │   ├── memory.py
│   │   │   ├── build.py
│   │   │   ├── backend.py
│   │   │   ├── ddrum4edit_backend.py
│   │   │   ├── transport.py
│   │   │   ├── backup.py
│   │   │   └── reports.py
│   │   └── tests/
│   │
│   └── ddrum4-modernizer/
│       ├── CMakeLists.txt
│       ├── src/
│       │   ├── app/
│       │   ├── cli/
│       │   ├── config/
│       │   └── core/
│       ├── config/
│       └── tests/
│
├── firmware/
│   └── ddrum4-midi-bridge/
│       ├── platformio.ini
│       ├── include/
│       ├── src/
│       ├── test/
│       └── generated/
│
├── tools/
│   └── midi-lab/
│       ├── src/midi_lab/
│       │   ├── cli.py
│       │   ├── monitor.py
│       │   ├── learn.py
│       │   ├── replay.py
│       │   ├── probe.py
│       │   └── traces.py
│       └── tests/
│
├── tests/
│   ├── fixtures/
│   ├── integration/
│   └── hardware/
│
└── scripts/
    ├── bootstrap.ps1
    ├── test-all.ps1
    └── verify-environment.ps1
```

The exact Python packaging mechanism may be adjusted during scaffolding, but the responsibility boundaries and import direction below are mandatory.

## 5. Dependency and Responsibility Rules

Allowed dependency direction:

```text
drum-domain
   ↑
   ├── drum-sampler
   ├── ddrum4-bank-builder
   ├── midi-lab
   └── profile/contract generators

generated routing contract
   ├── ddrum4-midi-bridge
   └── ddrum4-modernizer
```

Rules:

1. `drum-domain` must not know about audio devices, MIDI port APIs, JUCE, Arduino, ddrum4UI, or `ddrum4edit`.
2. `drum-sampler` must not contain ddrum4 encoding, memory allocation, Arduino generation, or DDrum-specific nested logic.
3. `ddrum4-bank-builder` consumes neutral sample libraries. It must not record audio directly.
4. `ddrum4-midi-bridge` must contain deterministic real-time routing only. It must not parse YAML during performance and must not control a PC GUI.
5. `ddrum4-modernizer` must translate input MIDI semantics to modern targets. It must not own sample files or build soundbanks.
6. `midi-lab` may observe, record, and replay MIDI, but it must not silently mutate production profiles.
7. DDrum4UI is a review/editor application. The Arduino must never drive it.
8. `ddrum4edit` is initially an installed external backend, not vendored software.
9. Factory sound audio must never be included in the final user bank.
10. Generated artifacts must identify their input manifest hashes and generator versions.

## 6. Configuration Model

Do not recreate the current single oversized YAML manifest. Use composable documents.

### 6.1 Physical kit

Defines physical objects and possible zones only:

```yaml
kit: greg-hybrid-kit
instruments:
  - id: snare_main
    kind: snare
    zones: [head, rim]
    capabilities: [positional_sensing]
  - id: hihat_main
    kind: hihat
    zones: [bow, edge, chick, splash]
    controllers: [openness]
```

It must not decide whether the snare is connected to the ddrum4, eDRUMin, or DDTi.

### 6.2 Wiring profile

Maps physical zones to source devices and observed MIDI events:

```yaml
profile: snare-via-edrumin
bindings:
  - physical: snare_main.head
    source: edrumin
    input: 1
    event: {channel: 11, note: 38}
    controllers: {position_cc: 16}
```

All MIDI values that depend on real hardware must be captured by `midi-lab` before being marked verified.

### 6.3 Capture session

Defines MIDI output, audio input, articulations, velocity points, repetitions, timing, and channel layout. It must support:

- VST/SD3 triggered through a virtual MIDI output;
- an external MIDI module triggered through a physical MIDI output and recorded through the UMC404HD;
- stereo capture first;
- four-channel capture later.

### 6.4 Neutral sample library

Every take must retain:

- logical instrument and articulation;
- requested MIDI note and velocity;
- repetition index;
- audio channel layout;
- raw and prepared file paths;
- capture timing;
- source and licensing statement;
- sample rate, channels, frames, peak, RMS, and clipping state;
- SHA-256 hash;
- processing history.

Raw files are immutable. Preparation always creates new files.

### 6.5 Ddrum4 bank manifest

Defines sound containers, priorities, layer policies, position policies, variations, sequences, memory constraints, and target kits.

It must distinguish:

- logical articulations;
- selected source takes;
- Clavia sample slots;
- layers;
- velocity response;
- position response;
- sequence/round-robin behavior;
- kit-level parameters;
- actual encoded block count.

### 6.6 Routing contract

The bank builder generates a machine-readable contract. Minimum fields:

```yaml
schema_version: 1
bank_id: metalcore-main
bank_hash: ...
ddrum_channel: 9
sound_id: CYMB_801
note_base: 80
note_p: 8
routes:
  - articulation: crash_1
    zone: bow
    output_note: 80
    position: 1
    velocity_transform: full
```

The Arduino mapping generator consumes this contract. It must never independently invent output notes, positions, or velocity windows.

## 7. Non-Source Assets

Do not copy these directories into Git:

```text
arduino_midi_router/.pio/
arduino_midi_router/public/
arduino_midi_router/build/
arduino_midi_router/**/__pycache__/
ddrum4_converter/build-app/
ddrum4_converter/build-core/
```

The existing installed backend is:

```text
D:\Studio\ddrum4ui\ddrum4ui.exe
D:\Studio\ddrum4ui\ddrum4edit.exe
```

Reference manuals and factory files may remain in the old directory initially. Add a Git-ignored local configuration such as:

```yaml
ddrum4ui_root: D:/Studio/ddrum4ui
reference_assets: D:/Workspace/Self/Studio/arduino_midi_router/public
sample_storage: D:/DrumSamples
```

Commit only a `.example.yaml`, never machine-specific paths or copyrighted audio.

## 8. Mandatory Repository Merge Plan

### Merge M0 — Preserve and inventory

Tasks:

1. Record file inventories and hashes for source/configuration files.
2. Record the current test commands and results.
3. Record tool versions: Python, CMake, Ninja, compiler, JUCE configuration, PlatformIO, `ddrum4ui`, and `ddrum4edit`.
4. Copy `Infos.md` into `drum-toolchain/docs/hardware-and-kit-target.md` and retain the original.
5. Do not modify the existing directories during this phase.

Acceptance criteria:

- The inventory is stored in `docs/repository-migration.md`.
- Seven current Python tests pass.
- The existing converter core tests pass.
- Missing PlatformIO availability is explicitly recorded rather than hidden.

### Merge M1 — Scaffold the monorepo

Tasks:

1. Create `drum-toolchain` with the target top-level layout.
2. Initialize Git in the new directory.
3. Add a comprehensive `.gitignore` for Python, PlatformIO, CMake, JUCE, audio, generated banks, dumps, and local paths.
4. Add root bootstrap and test scripts.
5. Add a concise root README explaining the applications and the required workflow order.
6. Add an initial license decision or mark it explicitly pending if the user has not selected one.

Acceptance criteria:

- A clean clone/scaffold does not include build products, installers, factory banks, dumps, or captured audio.
- `git status` shows only intentional source files.
- `scripts/verify-environment.ps1` reports missing tools without changing the machine.

### Merge M2 — Extract the shared domain

Source material:

```text
arduino_midi_router/ddrum4kit/project.py
arduino_midi_router/ddrum4kit/report.py
arduino_midi_router/config/*.yaml
```

Tasks:

1. Create explicit physical-kit, wiring, capture, target, bank, and setup models.
2. Preserve support for loading the existing manifests through a temporary compatibility adapter.
3. Separate validation from parsing.
4. Add JSON schemas or equivalent strict schema tests.
5. Port the existing allocation, route lookup, velocity mapping, and hi-hat CC tests.
6. Add tests proving that the physical snare is not tied to a source module.

Acceptance criteria:

- Existing YAML fixtures can be loaded or converted.
- New composable profiles resolve into one deterministic setup.
- Invalid MIDI ranges, duplicate routes, unknown sounds, and memory overflow are rejected.
- No shared-domain module imports `mido`, `sounddevice`, JUCE, Arduino headers, or subprocess APIs.

### Merge M3 — Move the firmware project

Copy and adapt:

```text
arduino_midi_router/platformio.ini
arduino_midi_router/include/DdrumBridge.h
arduino_midi_router/include/MidiDinAdapter.h
arduino_midi_router/src/DdrumBridge.cpp
arduino_midi_router/src/MidiDinAdapter.cpp
arduino_midi_router/src/main.cpp
arduino_midi_router/test/test_bridge/
arduino_midi_router/tools/generate_mapping.py
```

Tasks:

1. Move the firmware into `firmware/ddrum4-midi-bridge`.
2. Preserve native testability of the routing core.
3. Change the generator input from the old combined manifest to the resolved routing contract while retaining a compatibility mode until migration is complete.
4. Generate headers under `firmware/ddrum4-midi-bridge/generated` or `include/generated`.
5. Never edit generated mapping headers manually.
6. Document Uno memory and real-time constraints.

Acceptance criteria:

- Native bridge tests pass.
- An Uno firmware build succeeds when PlatformIO is available.
- The generated mapping is byte-for-byte deterministic for identical input.
- Unknown traffic remains safely filtered according to profile policy.

### Merge M4 — Extract `midi-lab`

Source material:

```text
arduino_midi_router/tools/midi_probe.py
reusable MIDI monitor/dump code from ddrum4kit/transport.py
```

Tasks:

1. Implement `ports`, `monitor`, `learn`, `record`, `replay`, and targeted probe commands.
2. Store recorded traces in a documented JSON or JSON Lines format.
3. Add guided capture for notes, CC4, Poly Aftertouch, choke, and positional data.
4. Ensure capture commands never alter production profiles automatically; emit a proposed patch instead.

Acceptance criteria:

- A synthetic trace can be recorded and replayed in tests.
- MIDI port matching rejects ambiguous matches.
- A guided learn session can produce a wiring-profile patch.

### Merge M5 — Extract `drum-sampler`

Copy and adapt:

```text
arduino_midi_router/ddrum4kit/audio.py
audio-related commands from ddrum4kit/cli.py
audio-related controls from ddrum4kit/gui.py only as behavioral reference
arduino_midi_router/config/audio_quality.yaml
```

Tasks:

1. Separate device discovery, scheduling, recording, processing, and export.
2. Replace route-based capture with capture-session based velocity/repetition grids.
3. Add resumable sessions and immutable raw takes.
4. Add clipping, silence, peak, RMS, and duration checks.
5. Preserve stereo now and design the model for four channels.
6. Do not migrate the Tkinter GUI as a dependency. A future GUI must call the same application library.

Acceptance criteria:

- Existing WAV processing tests pass.
- A simulated or loopback capture session produces a valid neutral sample library.
- Re-running a completed session skips valid takes and reports why.
- Processing never overwrites raw audio.

### Merge M6 — Extract `ddrum4-bank-builder`

Copy and adapt:

```text
arduino_midi_router/ddrum4kit/ddrum4ui.py
arduino_midi_router/ddrum4kit/transport.py
bank/memory/report portions of ddrum4kit/project.py and cli.py
arduino_midi_router/docs/ddrum4ui_strategy.md
arduino_midi_router/docs/ddrum4kit_usage.md
```

Tasks:

1. Define a `SoundBackend` protocol.
2. Implement `Ddrum4EditBackend` around the installed executable without shell interpolation.
3. Capture backend version, command arguments, return code, stdout, stderr, and output hashes.
4. Parse encoded block counts and sound metadata.
5. Add backup, upload planning, and explicit transfer commands.
6. Keep DDrum4UI launch support but do not automate mouse or keyboard actions.
7. Implement placeholder interfaces for nested allocation without starting production soundbank work yet.

Acceptance criteria:

- A known reference sound can be inspected read-only.
- Block count parsing is tested.
- A small synthetic WAV/config fixture can be encoded or the unsupported backend operation is documented with an isolated failing test.
- No hardware transfer occurs during automated tests.

### Merge M7 — Move `ddrum4-modernizer`

Copy source only from `ddrum4_converter`; do not copy build trees.

Tasks:

1. Place the C++ project under `apps/ddrum4-modernizer`.
2. Adjust root and local CMake files.
3. Preserve the standalone core-test target and GUI application target.
4. Preserve YAML compatibility initially.
5. Add a future adapter boundary for generated target profiles and routing contracts.
6. Do not redesign MIDI behavior during the merge unless required to fix a migration regression.

Acceptance criteria:

- Clean configure and build succeed.
- Core tests pass.
- The application starts and can load its migrated example profile.
- No absolute build paths from the original directory remain.

### Merge M8 — Consolidate documentation and profiles

Tasks:

1. Move maintained architectural documentation into `docs`.
2. Mark old assumptions as historical when they bind a pad to a module without measurement.
3. Convert `Infos.md` into the authoritative physical inventory and kit target.
4. Add local hardware test instructions using stable port-name matching.
5. Clearly distinguish templates, measured profiles, and generated profiles.

Acceptance criteria:

- Every example profile is labeled `template`, `measured`, or `generated`.
- No template value is described as a verified hardware fact.
- The README links to one canonical workflow.

### Merge M9 — Full baseline verification

Run from a clean build state:

```powershell
scripts\verify-environment.ps1
scripts\bootstrap.ps1
scripts\test-all.ps1
```

The test script must cover:

- shared Python domain tests;
- sampler unit tests;
- bank-builder unit tests;
- MIDI-lab tests;
- native Arduino routing tests;
- clean CMake build and modernizer core tests;
- schema and example-profile validation.

Produce `build/reports/merge-baseline.md` containing versions, commands, results, and known hardware tests not executed.

## 9. Mandatory Merge Gate Before Soundbank Work

Soundbank implementation may start only when all conditions below are true:

- [x] The new `drum-toolchain` Git repository exists.
- [x] The old source directories remain intact.
- [x] Build products and reference assets are excluded from Git.
- [x] Shared domain models and composable profiles exist.
- [x] Existing Python behavior has migrated and tests pass.
- [x] Firmware native tests pass from the new location.
- [x] The modernizer builds cleanly and its core tests pass.
- [x] The sampler can create a neutral sample-library fixture.
- [x] The bank builder can discover and inspect `ddrum4edit`.
- [x] MIDI-lab can list, match, record, and replay ports/traces.
- [x] One root command runs the complete non-hardware test suite.
- [x] `build/reports/merge-baseline.md` exists and contains no unexplained regression.

**Gate passed — 2026-08-10.** Evidence is retained in
`build/reports/merge-baseline.md`, `docs/repository-migration.md`, and the
root `scripts/test-all.ps1` suite. The current suite has subsequently grown
beyond the original baseline; soundbank work is therefore permitted and must
continue to preserve the safety rules below.

If any item fails, fix the merge first. Do not compensate by adding soundbank-specific work to the wrong project.

## 10. Hardware Bench After the Merge Gate

Observed devices on the current PC:

```text
Miditech Midiface 4x4 port 1 input:  MIDI4x4
Miditech Midiface 4x4 port 1 output: MIDI4x4
UMC stereo input:                    IN 1-2 (BEHRINGER UMC 404HD 192k)
UMC four-channel input:              IN 1-4 (BEHRINGER UMC 404HD 192k)
SD3 virtual MIDI candidates:         out_APC, out_ClyphX, out_WORLDE
```

Physical wiring reported by the user:

```text
PC Midiface port 1 OUT -> ddrum4 MIDI IN
ddrum4 MIDI OUT         -> PC Midiface port 1 IN
ddrum4 audio OUT 1/2    -> UMC audio IN 1/2
```

Never rely on numeric device indexes; they are unstable across boots and APIs.

Before any sound upload:

1. Receive and store a settings dump.
2. Record the module firmware/version information.
3. Inventory current Sound IDs and free memory if possible.
4. Reserve a confirmed-safe test Sound ID range.
5. Verify that the backup file is non-empty and can be parsed or replayed.
6. Store dumps outside Git with hashes and metadata.

Do not claim that a settings dump contains the module's audio sound files. Settings and sound files are separate backup concerns.

## 11. Soundbank Product Requirements

The final ddrum4 bank contains no original factory audio.

Primary standalone kit:

- modern metalcore kick;
- flagship modern metalcore snare with head, rim, velocity detail, and positional response when possible;
- expressive ZEITGEIST hi-hat with bow, edge, continuous openness, chick, and splash;
- four toms;
- three-zone ride;
- two primary expressive crashes with choke;
- two splashes;
- two chinas;
- one stack;
- optional percussion;
- small electronic sounds where memory permits.

Variants:

1. Main Metalcore.
2. Deftones-style brighter/reverberant snare variant.
3. Sleep Token-oriented mix and possible snare/tom variation.
4. Electro/Drum-and-Bass with short electronic kicks, snares, hats, claps, and FX while reusing acoustic cymbals.

Quality priority:

1. Main snare.
2. Main hi-hat.
3. Primary crashes.
4. Kick and ride.
5. Toms.
6. Splashes, chinas, stack, and percussion.
7. Small electronic additions.

The actual memory limit and block accounting must be read from the module/backend. Treat approximately 8 MB as a planning constraint, not as an excuse to hard-code an unverified block total.

## 12. Sampling Roadmap

### Sampling S0 — Resolve SD3 audio return

SD3 currently listens to the virtual MIDI interfaces, but its audio is sent to UMC outputs 1/2. The UMC did not expose an obvious native loopback device during the audit.

Evaluate in this order:

1. Host/driver loopback that preserves the current monitoring path.
2. Internal recording inside the VST host or DAW.
3. Physical patch from UMC OUT 1/2 to IN 3/4 while keeping monitoring on another output pair.

Do not start a large capture session before a ten-minute test proves that recorded audio is clean, sample-accurate enough, not clipping, and free of feedback.

### Sampling S1 — Stereo capture MVP

Implement explicit MIDI-triggered recording for both:

- SD3/VST through a virtual MIDI output and loopback audio input;
- an external module through a physical MIDI output and UMC input.

Minimum session parameters:

- MIDI port, channel, note, and optional Program Change;
- audio device and selected channels;
- velocity list;
- repetitions per velocity;
- pre-roll, note gate, tail, and cooldown;
- sample rate and sample format;
- retry and silence policies.

Initial dense-capture guidance:

- flagship snare/hi-hat/crashes: 16-24 velocity points and 4-8 repetitions;
- kick/ride/toms: 12-16 velocity points and 3-6 repetitions;
- small electronic sounds: 1-8 velocity points and 1-3 repetitions.

These are editable profiles, not fixed limits.

Acceptance criteria:

- A complete snare articulation session can run unattended.
- Interrupted sessions resume without overwriting valid takes.
- Repeated notes at the same SD3 velocity capture different internal round-robin variants when SD3 provides them.
- Raw, processed, and rejected takes are clearly separated.

### Sampling S2 — Four-channel capture

After stereo is stable, support:

```text
kick
snare
left ambience/mix
right ambience/mix
```

The neutral library must support named channels now even if the initial captures contain only left/right.

## 13. Ddrum4 Backend Strategy

Use `ddrum4edit` first.

Reasons:

- It already parses sound headers, ten layers, variations, sequences, samples, cue/compression packets, and actual block counts.
- The current installed version is 1.3.0.
- Reimplementing a complete, safe Clavia encoder and transfer stack is unlikely to fit within four days.

Required backend operations:

- inspect a sound;
- extract samples/configuration where supported;
- build from a generated configuration;
- emit MIDI or raw SysEx where supported;
- report encoded blocks;
- preserve and log exact backend version and command line.

Native format work is permitted only after a time-boxed backend spike demonstrates a missing operation that blocks automation. If native work begins:

1. Start with a read-only parser.
2. Add byte-for-byte round-trip tests.
3. Preserve unknown fields.
4. Do not replace the proven backend until generated sounds have been tested on hardware.

The user should not need to manually repeat DDrum4UI edits for every build. If a single manual reference operation is necessary to understand an undocumented field, capture it once, document it, and automate the resulting transformation.

## 14. Soundbank Roadmap

### Bank B0 — Safe transfer and capture loop

Tasks:

1. Back up settings.
2. Build or clone a sacrificial test sound using non-copyrighted synthetic audio.
3. Upload it to a reserved test ID.
4. Trigger it over `MIDI4x4` at several velocities.
5. Record ddrum4 OUT 1/2 through UMC IN 1/2.
6. Confirm note, velocity, sound ID, transfer pacing, and actual memory use.
7. Verify that a failed transfer stops the queue.

Acceptance criteria:

- One command builds, uploads, triggers, records, and reports the test sound with explicit confirmation before the upload step.
- The test does not overwrite an unreserved sound.

### Bank B1 — Flagship snare

Use the dense master library and select at most ten Clavia samples/layers.

Candidate allocation:

- 6-7 head dynamics;
- 2 rim dynamics;
- 1 cross-stick or strong head variant;
- positional response applied with layer position curves rather than duplicating every position when possible.

Tasks:

1. Implement sample selection by velocity/power distribution.
2. Generate the sound configuration.
3. Encode and parse the result.
4. Upload to a test ID.
5. Trigger a full velocity sweep and positional-note sweep.
6. Record the module output.
7. Compare source and module renders for transient, tone, tail, noise, and dynamics.
8. Iterate on trim, gain, decay, and cue markers.

Acceptance criteria:

- The sound rebuilds from manifests without manual DDrum4UI edits.
- The encoded block count is recorded.
- No factory audio remains.
- The snare passes an audible velocity sweep without obvious gaps or reversed layers.

### Bank B2 — Nested sound compiler

Implement the compiler that maps logical articulations to Clavia positions, layers, sequences, and optional velocity windows.

Selection priority:

1. Position/Note P for deterministic articulation selection while retaining full velocity.
2. Layers for dynamics.
3. Sequences or validated variation behavior for round-robin.
4. Velocity-window multiplexing only when channel/position pressure justifies reduced dynamics.

The compiler must produce:

- sound files/configurations;
- kit/channel assignments;
- encoded memory report;
- articulation coverage report;
- warnings for sacrificed velocity or zones;
- `routing-contract.json`;
- generated Arduino mapping fixtures, but not production firmware yet.

Acceptance criteria:

- Changing a position or Note P value regenerates both the bank plan and routing contract.
- Impossible layouts fail with explanations.
- The planner compares at least two candidate allocations when priorities conflict.

### Bank B3 — Main acoustic kit

Candidate packing strategy to validate experimentally:

```text
CH1   Kick main, with optional short alternate
CH2   Snare main: head/position/rim nested where practical
CH3   Rim/cross-stick, alternate snare, or short auxiliary bank
CH4   Tom 1 + Tom 2 nested
CH5   Tom 3 + Tom 4 nested
CH6   Auxiliary percussion/electronic or freed channel
CH7   Auxiliary cymbals or freed channel
CH8   Ride main, three zones
CH9   Primary crash bank
CH10  Hi-hat main
```

Do not assume every channel accepts every sound category until tested. If CH6/CH7 cannot host the proposed auxiliary cymbal sounds, repack into the validated channels and report the quality cost.

Crash strategy:

- Prioritize velocity quality over separate bow/edge audio when necessary.
- Choke may use the same active crash audio plus Polyphonic Aftertouch.
- Two crashes with five useful dynamics each may be preferable to four zone-specific samples with weak dynamics.

Initial memory targets, subject to actual encoded blocks:

| Family | Planning share |
|---|---:|
| Main snare | 15-18% |
| Main hi-hat | 15-20% |
| Two primary crashes | 20-26% |
| Ride | 8-12% |
| Kick | 5-8% |
| Four toms | 12-16% |
| Splash/china/stack | 5-8% |
| Electro and reserve | 5-10% |

Acceptance criteria:

- The complete main kit fits the measured module memory.
- Every required articulation is either implemented or explicitly listed as sacrificed.
- Snare, hi-hat, and two crashes receive the highest listening-test priority.
- The kit can be played entirely by PC-generated ddrum4 MIDI before Arduino work begins.

### Bank B4 — Hi-hat

The hi-hat is a special validation project.

Requirements:

- bow and edge;
- closed through open continuous response;
- chick;
- foot splash;
- closing an already sounding open sample;
- reliable repeated hits while moving the pedal.

It is acceptable to use a factory sound as a structural reference or template only if all factory audio samples are removed/replaced. Record exactly which non-audio parameters are retained.

Acceptance criteria:

- Ten documented listening/behavior tests pass.
- CC4 polarity and ranges are recorded, not assumed.
- The final sound contains no factory audio.

### Bank B5 — Alternative kits

Implement in this order:

1. Deftones-style variant.
2. Sleep Token-oriented variant.
3. Electro/DnB kit.

Prefer reuse:

- Derive the Deftones snare through pitch, decay, level, and mix first.
- Reuse acoustic sounds for Sleep Token while changing kit parameters.
- Use short electronic samples for additional kicks, snares, hats, claps, clicks, and FX.
- Reuse acoustic cymbals in the electro kit.

Acceptance criteria:

- Kit changes do not duplicate unchanged acoustic samples.
- Each added sound reports its incremental block cost.
- The main kit always retains a safety reserve.

## 15. Modernizer Roadmap

Start only after the main ddrum4 bank is playable. In PC mode, DDrum4 MIDI OUT
must feed UMC MIDI IN directly with `L.ON`; do not put the current selective
Arduino bridge in the raw DDrum4-to-modernizer path. See
`docs/midi-operating-modes.md`.

Validation order:

```text
ddrum4 MIDI OUT
-> ddrum4-modernizer
-> virtual MIDI port
-> Superior Drummer 3
```

Then add an optional DDTi USB input adapter if its direct SD3 mapping is insufficient. eDRUMin may continue to feed SD3 directly while it already behaves correctly.

Refactor toward logical events:

```text
snare.head
snare.rim
snare.position
hihat.bow
hihat.edge
hihat.openness
ride.bow
ride.bell
ride.edge
cymbal.choke
```

Acceptance criteria:

- ddrum4 positional notes, CC4, and Poly Aftertouch are converted correctly.
- The application consumes a generated or versioned target profile.
- Changing a physical wiring profile does not require rewriting the ddrum4-output decoder.

## 16. Arduino Roadmap

Start production Arduino integration only after the soundbank routing contract is stable.

Tasks:

1. Capture actual DDTi and eDRUMin messages with `midi-lab`.
2. Compare wiring profiles only when a hardware decision is needed.
3. Generate the Arduino table from the bank routing contract plus selected wiring profile.
4. Support note mapping, velocity curves, positional input, CC4, choke conversion, and active-note tracking.
5. Test MIDI bursts, Note Off correctness, latency, and queue behavior.
6. Keep unknown-message behavior explicit and safe.

Final standalone path:

```text
DDTi MIDI OUT --------\
                       MIDI merger -> Arduino -> ddrum4 MIDI IN -> ddrum4 audio
eDRUMin MIDI OUT -----/
```

Acceptance criteria:

- No manually duplicated nested mapping exists in firmware source.
- The generated header identifies the bank/routing-contract hash.
- The complete physical kit can trigger the intended ddrum4 sounds without a PC.

## 17. DrumGizmo Roadmap

The neutral capture library is the source. DrumGizmo and ddrum4 use different selections from the same master takes.

Stereo MVP output:

- prepared WAV files;
- instrument XML files with power values;
- drumkit XML;
- MIDI map XML;
- validation report.

Later four-output layout:

```text
kick
snare
left including ambience
right including ambience
```

The ddrum4 compiler may aggressively reduce velocities, repetitions, duration, and bandwidth. The DrumGizmo exporter should retain the dense master quality.

Acceptance criteria:

- A generated stereo kit loads and plays in DrumGizmo.
- MIDI mapping is derived from the same logical target model.
- Four named output channels can be represented without changing the neutral-library schema.

## 18. Operational Safety Rules

1. Do not send SysEx or sound files before the backup step has passed.
2. Resolve MIDI ports by unique names, not numeric indexes.
3. Require an explicit command flag or confirmation for hardware writes.
4. Stop a transfer queue on the first failed or unverified transfer.
5. Never overwrite raw captured audio.
6. Never commit commercial samples, user dumps, generated banks, or machine-specific paths.
7. Do not delete the old project directories during migration.
8. Do not automate DDrum4UI mouse/keyboard interaction unless a documented CLI/backend path is proven impossible and the fallback is explicitly isolated.
9. Do not claim a memory fit until actual encoded block counts are available.
10. Do not mark template MIDI values as measured facts.
11. Do not hard-code the snare source module in the physical-kit model.
12. Do not start WORLDE integration during the soundbank roadmap.

## 19. Agent Progress Reporting

At the end of every merge or product phase, the implementing agent must report:

- files created, moved, or intentionally left in place;
- tests executed and their exact results;
- generated artifacts and their locations;
- hardware actions performed, if any;
- remaining assumptions;
- blockers requiring physical rerouting or user audition;
- whether the phase acceptance criteria passed.

Do not declare a phase complete because its code compiles. Completion requires its stated acceptance criteria.

## 20. Immediate Execution Order

The next agent should execute these tasks in order:

1. Merge M0: inventory and baseline.
2. Merge M1: scaffold the new Git monorepo.
3. Merge M2: extract shared domain and composable profiles.
4. Merge M3: migrate firmware and generator.
5. Merge M4: extract MIDI-lab.
6. Merge M5: extract sampler.
7. Merge M6: extract bank builder.
8. Merge M7: migrate modernizer.
9. Merge M8: consolidate documentation and profiles.
10. Merge M9: run the full baseline and produce the merge report.
11. Verify every checkbox in the mandatory merge gate.
12. Execute hardware bench backup and safe transfer characterization.
13. Resolve the SD3 audio return.
14. Capture the first dense snare library.
15. Build and audition the first Clavia snare.
16. Implement nested allocation and build the main Metalcore bank.
17. Build the alternative kits.
18. Validate ddrum4 -> modernizer -> SD3.
19. Generate and validate the Arduino bridge.
20. Complete the DrumGizmo stereo and four-output exporters.
