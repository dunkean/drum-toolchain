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
  `MidiFile.play()` had already honoured DDrum4UI's 376 ms SMF delta. A native
  DDrum4UI capture proved that its real packet interval is 400 ms, so the
  sound replay now uses that pace directly instead of applying both delays;
  the behavior is covered by a regression test. A complete native capture
  additionally showed two MIDI Reset observations before the 11 SysEx packets
  and one afterward. Follow-up physical testing established these as
  Windows/port-reset artefacts, not sound-file bytes: replay deliberately
  excludes them because a System Reset can abort the DDrum4 receiver.
- The general Python MIDI backend reproduced the stream on loopMIDI but was
  still rejected by the physical module. DDrum4UI's binary reveals a WinMM
  `midiOutLongMsg` sender, so all-SysEx sound replay now uses that same API.
  Its isolated 1,172-byte B0 packets were captured intact through the virtual
  bench before the next hardware attempt.
- DDrum4UI's bundled native sender uses Windows MM/libremidi and exposes an
  inter-message-pause setting. Its public user documentation does not specify
  its exact packet framing or timing. A loopMIDI capture port was proven to
  carry long SysEx messages, but the ordinary Python input API silently drops
  packets above 1 KiB. Added a Windows-MM long-message receiver with 4 KiB
  buffers and a guarded `record-sysex` command; an internal 1,174-byte virtual
  SysEx capture succeeds. The public command was also exercised end-to-end on
  `in_dunk`: it wrote one intact 1,172-byte SysEx message to the isolated
  self-test MIDI file. No native DDrum4UI sound stream has been captured yet.
- Next hardware action: replay the validated B0 `.mid` with its embedded
  timing only, while the user observes the module display. Do not attempt a
  bulk bank transfer before this produces the expected block countdown and
  audible test sound.

## B0/B1 complete-path verification — 2026-08-10

- The B0 transfer was accepted through `UMC404HD 192k MIDI Out 9` with
  255-byte SysEx transport fragments: the module displayed all 11 blocks and
  `KICK_999` was heard with `SHIFT + LISTEN`.
- `ddrum4edit` configuration export and reconstruction are now demonstrated
  locally. `-e -i <sound.mid>` exports its `.cfg` and sample files; `-c
  <config.cfg>` creates the destination declared inside that configuration.
  The rebuilt disposable fixture parses at 11 encoded blocks. The bank backend
  enforces that output declaration and refuses overwrites.
- A local Superior Drummer 3 Modern Metal EZX / Djentle Beast snare WAV was
  prepared and encoded as `SNRE_999` (137 blocks), transferred to the module,
  and audibly confirmed. This is the first complete original-audio pipeline;
  no factory audio is present in the generated sound.
- A seven-layer B1 velocity-crossfade configuration was generated from an
  original SD3 capture selection. It uses documented DDrum4 layer velocity
  curves, prepared mono source WAVs and 94 actual encoded blocks as
  `SNRE_998`; transfer completed without a PC or module error. The remaining
  B1 gate is a module output velocity/position sweep with recordings.

## B3 priority candidates — 2026-08-10

- `KICK_997` was generated from seven original SD3 kick velocity captures with
  the same crossfade layout, encoded at 124 blocks, and transferred
  successfully through the UMC route.
- `HHAT_996` was generated from nine original SD3 CC4 opening positions
  (0, 16, …, 127), encoded at 43 blocks, and transferred successfully through
  the UMC MIDI route. Its layer parameters are a one-time transcribed
  continuous-hi-hat *structure*; no factory sample files are included in the
  generated sound or repository.
- The bank planner now uses the measured 1,270-block starting budget rather
  than an unverified nominal 8,192-block figure. Every future transfer batch
  must re-read `SHIFT+MEM.LEFT` before being declared to fit.
- Two original SD3 crash sounds were encoded as real Cymbal group files and
  transferred successfully: `CYMB_995` at 350 blocks and `CYMB_994` at 308
  blocks. Along with `SNRE_998`, `HHAT_996` and `KICK_997`, this creates a
  five-sound core for the first listening pass. The live remaining-memory
  value and each module audition are still required before packing toms/ride.
- Four compact original SD3 toms were then encoded and transferred: `TOM_993`
  (21 blocks), `TOM_992` (52), `TOM_991` (37), and `TOM_990` (52). The actual
  encoded ten-sound report totals 1,218 / 1,270 blocks, leaving a nominal 52
  blocks. Do not transfer ride, percussion, or any further sound until the
  module's live free-memory display is read and the listening pass approves
  the quality trade-offs.
- The module was then read with `SHIFT+MEM.LEFT`: **45 blocks free**. This is
  the authoritative post-transfer value; it differs by seven blocks from the
  offline 52-block remainder, consistent with module-side allocation. The
  first core is therefore memory-full for practical purposes. Future sounds
  require replacing an existing Sound ID or a smaller rebuilt candidate.
- `RIM_999` was then transferred: two rimshot dynamics plus cross-stick
  source, encoded at 30 blocks. This revealed an incorrect assumption:
  DDrum4 Sound IDs are a pair of *instrument group* and number, so
  `RIM_999` does **not** replace `SNRE_999`. The live `SHIFT+MEM.LEFT`
  reading is therefore 15 blocks (45 - 30), exactly matching the new rim
  sound cost. No further transfer may run until the one-layer `SNRE_999`
  proof is explicitly deleted on the module. Deleting its measured 137 blocks
  should restore approximately 152 free blocks while retaining `RIM_999` and
  the seven-layer `SNRE_998`.

## Empty-module baseline and core reload — 2026-08-10

- The owner explicitly cleared every DDrum4 sound group through the supported
  front-panel group-mark/delete operation. `SHIFT+MEM.LEFT` then reported
  **8.12**, establishing the real empty sound-memory capacity as 8,120 blocks.
  This supersedes the earlier 1,270-block *free-space* baseline; that smaller
  number was not the total module capacity.
- The previous compact candidates were intentionally retained as an auditable
  first core, not mistaken for the final quality allocation. Their freshly
  generated actual report is outside Git at
  `D:\Studio\ddrum4-b3\empty-module-core-bank-report-20260810.json`:
  13 sounds, 1,240 encoded blocks, and 6,880 planned blocks remaining.
- All 13 files were sent one at a time through `UMC404HD 192k MIDI Out 9`,
  with a non-overwriting receipt beside each source sound. The list is
  `RIM_999`, `SNRE_998`, `HHAT_996`, `CYMB_995`, `CYMB_994`, `KICK_997`, four
  toms, and the three compact ride-zone candidates. The next authoritative
  step is the module's post-transfer `SHIFT+MEM.LEFT` reading and audition;
  no mapping or kit assignment has been assumed or written yet.
- A compact three-file ride candidate is built but intentionally not yet
  transferred: bow 20 blocks, bell 20 blocks, edge 89 blocks. The revised
  offline complete-kit report is 1,240 / 1,270 blocks (30 nominal free); use
  the post-replacement `MEM.LEFT` display as the final go/no-go gate.
- The owner subsequently confirmed `MEM.LEFT = 6.88` after the 13-file core
  load. This matches 8,120 - 1,240 = 6,880 blocks exactly, so the transfer
  receipts and the block accounting are now hardware-verified.

## Central Local-OFF routing preparation — 2026-08-10

- The chosen next architecture is documented in
  `docs/ddrum4-local-off-central-routing.md`: DDrum4 pads become a third MIDI
  source with `Local OFF`, and the Arduino is the sole route/branch owner
  before DDrum4 MIDI IN. This removes the direct-pad limitation that would
  otherwise make `CYMB 2` unavailable for nested routing.
- Firmware routing now derives its Program-Change allow-list from all declared
  `midi.sources`, rather than hard-coding only DDTi and eDRUMin. A test
  exercises a third source on channel 12. No live channel or module setting
  has been changed: a three-pad trace-and-echo proof remains the next hardware
  gate.

## Local-OFF echo and palette-scene evidence — 2026-08-10

- The Local-OFF bench revealed that this DDrum4 path retransmits received MIDI
  events to MIDI OUT. `DdrumBridge` now has a bounded immediate-echo guard;
  native tests include both ordinary and out-of-order return echoes. The guard
  is comparison-only and does not introduce a timing delay.
- A temporary diagnostic profile is retained at
  `profiles/diagnostics/ddrum4-local-off-cymb2-echo.yaml`. It records the
  observed C12/note-17 CYMB2-input proof and is not a production kit map.
- Palette selection is now an explicit cross-engine scene concept, documented
  in `docs/ddrum4-palettes-and-pc-scenes.md`. Its concrete emitted MIDI event
  is still a learn gate, not an assumption.

## DrumGizmo actual export — 2026-08-10

- The dense original SD3 kick/tom capture library was exported as a
  self-contained stereo DrumGizmo 2.0 kit at
  `D:\Studio\drumgizmo\sd3-modern-metal-core-kick-toms`. It contains eight
  instrument XML files and 168 copied captured WAVs; generated XML is parsed
  by the exporter. This is intentionally independent of the compact DDrum4
  selections. The subsequent consolidated kit resolves its target MIDI-note
  collisions explicitly rather than discarding those articulations.
- That target map is now implemented and a complete consolidated stereo kit
  was generated at
  `D:\Studio\drumgizmo\sd3-modern-metal-djentle-beast-stereo-v1`.
  It contains 469 original captured WAVs across 28 instrument XML files:
  kick(s), toms, main snare, three snare-position captures, rimshot,
  cross-stick, six hi-hat states, both main crashes, ride bow/bell/edge,
  china, splash and auxiliary cymbal. The export uses explicit target notes
  for the otherwise ambiguous snare-position and CC4 hi-hat articulations
  (22–24 and 81–83); ordinary GM-like notes remain unchanged. The generated
  `drumkit.xml` and `midimap.xml` were parsed by the exporter, and the WAVs
  are copied rather than modified.
