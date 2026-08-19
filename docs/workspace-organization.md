# Workspace Organization

## Active Git repositories

The Studio workspace has two active repositories with independent histories:

```text
Studio/
├── drum-toolchain/            # battery monorepo
└── worlde-control-surface/    # WORLDE/Ableton controller project
```

`drum-toolchain` owns every battery responsibility: DDTi editing, sampling,
ddrum4 bank construction and transfer, modern MIDI conversion, shared kit
profiles, MIDI diagnostics, and the Arduino bridge.

`worlde-control-surface` owns the WORLDE configuration converters, MIDI helper
scripts, and Ableton Remote Script. The drum monorepo must not import it.

## Battery monorepo boundaries

```text
apps/ddti/                  DDTi configuration and reverse engineering
apps/drum-sampler/          MIDI-triggered audio capture and neutral libraries
apps/ddrum4-bank-builder/   ddrum4 encoding, allocation, nested sounds, transfer
apps/ddrum4-modernizer/     ddrum4 MIDI to modern software targets
firmware/ddrum4-midi-bridge Arduino real-time standalone routing
packages/drum-domain/       shared hardware, event, and profile models
tools/midi-lab/             diagnostic capture and replay utilities
profiles/                   versioned input, capture, bank, and target intent
hardware/enclosures/        mechanical artifacts associated with hardware
docs/                       maintained specifications and historical records
```

Generated builds, audio captures, local dumps, downloaded tools, factory
assets, and machine-specific paths are excluded from Git.

## Legacy archive

The original `arduino_midi_router`, `ddrum4_converter`, and `WORLDE_helpers`
directories are preserved under `Studio/_archive/legacy`. They are snapshots,
not active projects. The original converter source is byte-identical to
`apps/ddrum4-modernizer`; the Arduino monorepo implementation has evolved past
its snapshot. Downloaded Ableton trees and build products remain only in the
archive.

Loose pre-merge documents and the original `WORLDE_helpers.7z` are stored
under `Studio/_archive/workspace-root`. Maintained copies of useful documents
are versioned in the active repositories.

## Working rule

Start new battery work in the appropriate `drum-toolchain` responsibility.
Start WORLDE/Ableton controller work in `worlde-control-surface`. Do not revive
or edit an archived snapshot; recover a missing file into the matching active
repository first.

