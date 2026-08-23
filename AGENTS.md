# Repository Guidelines

## Project Structure & Module Organization

This is a mixed Python, C++23, and Arduino/PlatformIO workspace. User-facing tools live under `apps/`. Shared Python domain code is in `packages/drum-domain/src`, MIDI utilities are in `tools/midi-lab/src`, and embedded code is in `firmware/ddrum4-midi-bridge`. Keep schemas in `contracts/schemas`, hardware and capture profiles in `profiles`, documentation in `docs`, and enclosure assets in `hardware`. Cross-project Python tests belong in `tests/python`; component-specific C++ tests stay beside their component.

## Build, Test, and Development Commands

- `./scripts/bootstrap.ps1` checks that Git, Python, CMake, Ninja, PlatformIO, and optional ddrum tools are available.
- `python -m pip install -e .` installs the Python 3.12 workspace dependencies for local development.
- `python -m pip install -e 'apps/ddti[api,gui]'` installs the DDTi app with API and desktop extras.
- `./scripts/test-all.ps1` runs the shared Python suite plus firmware-core and modernizer-core tests.
- `cmake -S . -B build -G Ninja; cmake --build build` configures and builds the C++ modernizer.
- `pio run -d firmware/ddrum4-midi-bridge` builds the default Arduino Uno firmware.
- `pio test -d firmware/ddrum4-midi-bridge -e native` runs PlatformIO's native firmware tests.

Run commands from the repository root unless a component README says otherwise.

## Coding Style & Naming Conventions

Use four spaces in Python, type annotations for public interfaces, and docstrings for non-obvious behavior. Name Python modules and functions `snake_case`, classes `PascalCase`, and constants `UPPER_SNAKE_CASE`. For C++, retain the local C++23 style: `PascalCase` types, `camelCase` functions, and trailing underscores for private members. No repository-wide formatter or linter is configured; match adjacent code. Use descriptive kebab-case profile names, such as `profiles/targets/ddrum4-standalone.yaml`.

## Testing Guidelines

Python tests use `unittest` discovery and files named `test_*.py`; test methods begin with `test_`. Add regressions near the affected subsystem. C++ tests are executable-based, with PlatformIO Unity tests for firmware. There is no stated coverage threshold; prioritize boundaries, MIDI routing, serialization, and hardware-safe failures. Run `./scripts/test-all.ps1` before submitting.

## Commit & Pull Request Guidelines

Follow the existing Conventional Commit pattern: `feat:`, `fix:`, `test:`, `docs:`, or `chore:` followed by an imperative summary. Keep commits scoped to one logical change. Pull requests should explain intent, list validation commands, link related issues, and call out profile/schema or hardware behavior changes. Include screenshots for GUI updates and sanitized logs for MIDI or device workflows; never commit captures, audio, local profiles, generated binaries, or device-specific secrets.
