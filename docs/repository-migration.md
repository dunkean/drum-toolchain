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

## M1 scaffold — in progress

- Created the `drum-toolchain` Git monorepo scaffold.
- Added ignore rules for all generated binaries, dumps, audio, local settings,
  downloaded dependencies, and reference assets.
- No legacy project file has been moved, deleted, or modified.
