# Repository Migration Log

## M0 baseline — 2026-08-09

Source directories were preserved in place:

```text
D:\Workspace\Self\Studio\arduino_midi_router
D:\Workspace\Self\Studio\ddrum4_converter
D:\Workspace\Self\Studio\WORLDE_helpers
```

`WORLDE_helpers` is deliberately excluded from this monorepo until a later
control-surface integration phase.

### Tool baseline

| Tool | Result |
| --- | --- |
| Git | 2.34.1.windows.1 |
| Python | 3.13.7 |
| ddrum4edit | 1.3.0 |
| ddrum4UI | 3.6.1 |
| `pio` on `PATH` | unavailable |
| fallback PlatformIO executable | present at the documented Python 3.13 scripts location |
| CMake on `PATH` | unavailable |
| GCC/G++ for PlatformIO native tests | unavailable |

### Source baseline

| Directory | Total files | Source candidates | Notes |
| --- | ---: | ---: | --- |
| `arduino_midi_router` | 1,979 | 30 | build products and public reference assets excluded |
| `ddrum4_converter` | 5,547 | 15 | CMake/JUCE build trees excluded |
| `WORLDE_helpers` | 1,146 | 1,146 | out of scope |

### Known baseline tests

```powershell
cd D:\Workspace\Self\Studio\arduino_midi_router
python -m unittest discover -s test -p 'test_*.py' -v
```

Expected result: seven tests pass.

```powershell
cd D:\Workspace\Self\Studio\ddrum4_converter\build-core
.\ddrum4_core_tests.exe
```

Expected result: `converter tests passed`.

## M1 scaffold — complete

- Created the `drum-toolchain` Git monorepo scaffold.
- Added ignore rules for all generated binaries, dumps, audio, local settings,
  downloaded dependencies, and reference assets.
- No legacy project file has been moved, deleted, or modified.

## M2-M7 extraction — in progress

- Extracted a pure `drum-domain` package with a physical-kit model, normalized
  events, composable setup references, legacy project compatibility, and stable
  serialization helpers.
- Extracted the initial sampler grid planner and existing non-destructive WAV
  processing module.
- Extracted the `ddrum4edit` discovery/transport code, explicit backend
  adapter, nested-layout validation, neutral routing-contract serializer, and
  compatibility with the existing mapping generator.
- Extracted the initial MIDI port resolver and JSON Lines trace format.
- Migrated Arduino firmware source, generator, and native test source.
- Migrated modernizer source/configuration/tests without copying CMake build
  trees.
- Copied the legacy extended-kit and electronic-bank manifests into
  `profiles/legacy` as regression fixtures. They are explicitly legacy combined
  manifests, not the future composable profile format.

### Verification status

- The new shared Python test entry point passes fifteen tests, including the
  original planning, velocity-window, mapping-generation, WAV-processing, and
  quality-profile behavior.
- PlatformIO native test execution was attempted through the documented
  fallback executable. It cannot compile because `gcc` and `g++` are absent.
  This is an environment blocker, not a source failure. An MSVC bridge-core
  test was added as a local verification path; PlatformIO/Unity remains the
  target test framework for environments with GCC.
- CMake is not on `PATH`, but the Visual Studio 2022 bundled CMake and MSVC
  toolchain are present. A clean modernizer core build and test pass through
  the documented Visual Studio developer environment.
- Safe command-line entry points now create neutral sampler fixtures, discover
  and inspect the local `ddrum4edit` backend, and list/match/record/replay MIDI
  traces. MIDI replay requires the explicit `--send` hardware-write flag.

## M8 merge gate — ready for review

- `scripts/test-all.ps1` is the single non-hardware verification command.
- `scripts/write-merge-baseline.ps1` writes the ignored operational report at
  `build/reports/merge-baseline.md` after that suite passes.
- The report generator does not open MIDI ports, send MIDI/SysEx, capture audio,
  or transfer a sound. No hardware action has been performed in this phase.
- The DDrum4 hardware bench and backup procedure are the next gated phase; no
  soundbank transfer is permitted yet.

## Product foundation progress — 2026-08-09

- Added a versioned neutral sample-library record with immutable raw path,
  channel layout, source/licensing declaration, audio facts, SHA-256 hash, and
  processing-history field.
- Added a versioned capture-session document, dense take planning, resumable
  capture execution, and a CLI confirmation gate before any MIDI-triggered
  audio recording.
- Four named capture channels are now supported by the sampler API for the
  future `kick`, `snare`, `left`, and `right` layout; initial real sessions may
  still use `left`/`right` only.
- Added DDrum4 settings-backup validation and adjacent metadata hashing. The
  receiver is implemented but has not been run against the module yet.
- All changes were verified with `scripts/test-all.ps1`: 20 Python tests, the
  portable firmware core test, and the clean modernizer core build/test pass.

## Sampling S0 discovery — 2026-08-09

- Read-only audio-device enumeration found UMC404HD physical input pairs and
  output pairs, but no identifiable UMC loopback capture device.
- SD3 is currently routed to UMC OUT 1/2. The next SD3 capture proof therefore
  needs either host/DAW internal rendering/recording or an explicit physical
  OUT 1/2 -> IN 3/4 patch with separate monitoring. This is recorded in
  `docs/capture-workflow.md`; no capture was attempted.

## DrumGizmo exporter foundation — 2026-08-09

- Downloaded DrumGizmo 0.9.20 source into ignored `build/` reference storage
  and verified the generated XML structure against its own parser tests.
- Added a DrumGizmo 2.0 exporter for captured neutral libraries. It creates
  `drumkit.xml`, `midimap.xml`, one instrument XML per logical articulation,
  and optionally a non-overwriting copy of each WAV into the generated kit.
- It supports the future four-channel `kick`, `snare`, `left`, `right` layout
  and refuses ambiguous MIDI-note-to-articulation mappings.
- XML is parsed after generation in automated tests. Loading a real generated
  kit in the DrumGizmo engine remains pending on actual captured audio.

## DDrum4 backend spike — 2026-08-09

- Read-only `ddrum4edit` inspection and encoded-block parsing are demonstrated.
- Configuration-to-sound rebuilding has not yet been proven with a local,
  non-factory fixture. The build adapter therefore fails closed instead of
  guessing flags or emitting transferable output. This is a prerequisite for
  the synthetic B0 sound after the settings backup.

## Hardware bench backup — 2026-08-10

- Captured a user-initiated `D.AL` DDrum4 settings dump through Midiface port
  1 input (`MIDI4x4 30`): 56 SysEx messages, with adjacent SHA-256 metadata.
- The backup is stored outside Git at
  `D:\Studio\ddrum4-backups\settings-20260810.mid`; no MIDI/SysEx was sent to
  the module and no sound or setting was modified.
- Added a local-only inspection command that reports dump framing facts, plus
  exact-name MIDI port preference so the Midiface port-1 alias is handled
  safely. Vendor payload semantics remain intentionally undecoded.
- Remaining B0 gate: record firmware/version, observed free memory and a
  user-confirmed sacrificial Sound ID before any transfer characterization.

## B0 offline fixture — 2026-08-10

- Added `create-b0-fixture`, which writes a deterministic, non-copyrighted
  16-bit mono WAV test click plus SHA-256/provenance manifest. It refuses to
  overwrite either file and has no MIDI-port or module-write capability.
- Added `docs/ddrum4-transfer-safety.md`, which records the remaining explicit
  inventory and one-time ddrum4UI build evidence required before transfer.
- Verified fixture framing at the module-native 44.1 kHz (7,938 frames) and
  the full suite: 28
  Python tests, firmware bridge-core and modernizer-core all pass.

## Nested compiler foundation — 2026-08-10

- Added the backend-neutral `compile-nested` command and a minimal fixture.
  One declared nested layout now produces both the Arduino-facing routing
  contract, optional generated Arduino mapping header, and an
  articulation-coverage report, while invalid positions or aggregate
  sample/layer budgets fail with direct explanations.
- Sound encoding and DDrum4UI transfer remain deliberately separate and gated
  on the verified backend build fixture and hardware inventory.

## B1 snare selection foundation — 2026-08-10

- Added deterministic selection from dense captured libraries: seven evenly
  distributed head layers, two rim layers, and a cross-stick/strongest-head
  accent candidate within the ten-sample cap.
- Selection rejects unproven provenance and records any intentional fallback;
  it does not substitute factory audio or encode/send a sound.

## Hardware inventory observation — 2026-08-10

- The connected DDrum4 reports firmware `1.50` at boot and 1,270 free blocks
  through the read-only `SHIFT` + `MEM.LEFT` display.
- The user authorized replacing all existing sounds if later required, but B0
  uses the available free memory first. A deterministic 44.1 kHz B0 WAV and
  manifest were written outside Git at `D:\Studio\ddrum4-b0\` for manual UI
  import; no module transfer has occurred.

## B0 local-build verification — 2026-08-10

- Added `verify-b0-build`: it checks the B0 WAV against its manifest hash,
  invokes the read-only `ddrum4edit -p` inspection on a locally saved sound,
  records its real encoded block count, and refuses overwrite of the record.
- The command has no MIDI output path. B0 remains pending only on the local
  DDrum4UI sound save, then the separately confirmed hardware transfer.

## B0 transport characterization — 2026-08-10

- The manual DDrum4UI build was saved as `D:\Studio\ddrum4-b0\KICK_999.mid`.
  It is a 13,076-byte, 11-SysEx-message sound and `ddrum4edit` reports 11
  encoded blocks. Its build record retains the source WAV and sound hashes.
- The physical PC-to-module MIDI route was independently proven by triggering
  the DDrum4. Its installed mapping labels MIDI numbers 13/14/15 as
  `C#0`/`D0`/`D#0`; this is an octave-label convention difference, not a
  routing failure.
- The first direct replay produced `ERR` on the module. Investigation found
  that the replay path was applying an additional 400 ms SysEx pause after
  `MidiFile.play()` had already honoured DDrum4UI's 376 ms packet timing.
  The duplicate pause was removed and covered by a regression test.
- DDrum4UI's bundled native sender uses Windows MM/libremidi and exposes an
  inter-message-pause setting. Its public user documentation does not specify
  its exact packet framing or timing. A loopMIDI capture port was proven to
  carry long SysEx messages, but only DDrum4UI reset events were observable
  during this bench session; no native sound stream was captured yet.
- Next hardware action: replay the validated B0 `.mid` with its embedded
  timing only, while the user observes the module display. Do not attempt a
  bulk bank transfer before this produces the expected block countdown and
  audible test sound.
