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
