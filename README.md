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

`Drum_app_design.md` is intentionally deferred until the project organization
and the active soundbank work have stabilized.

## Safety

No automated test may write to hardware. Any explicit hardware upload must be
preceded by a verified settings backup and must require a confirmation flag.
