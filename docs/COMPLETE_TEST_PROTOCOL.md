# Complete Test Protocol — eDrum / DDrum4 / SD3 / DrumGizmo

## Master-capture rule

Record the reference library as **48 kHz stereo 32-bit float WAV**. Do not use
a DDrum4-ready or other 16-bit derivative as a source for a later export.
Keep the raw master immutable, then create each DDrum4 and DrumGizmo rendition
from that master through a named preparation profile.

This is the reproducible operator runbook for the rig described in
`architecture_finale_edrum_ddrum4_sd3.md`.

## Goal and source of truth

SD3 is the capture source. Load one SD3 MegaKit containing every sound to be
sampled, capture it completely, then derive two target kits from one approved
library:

```text
SD3 MegaKit → immutable complete capture library
                    ├─ DDrum4: compact base kit + selected variations
                    └─ DrumGizmo: complete kit, all approved layers
```

The capture library is the source of truth. A DDrum4 bank is never the only
copy of a sound; DrumGizmo files must be generated from recorded, traceable
inputs. The same physical event must also be traceable through all renderers:

```text
raw source → Physical Event → Scene / VP → DDrum4 MIDI IN / audio
                                      ├─→ SD3 MegaKit / audio
                                      └─→ DrumGizmo kit / audio
```

Only one renderer is audible in the mixer at a time. DDrum4 is the fallback.

## Non-negotiable rules

- Run gates in order. A successful read-only test never authorizes a write.
- Never let two programs open the same MIDI input at the same time.
- Do not send SysEx, transfer a DDrum4 Sound, flash firmware, or write DDTi
  settings without explicit confirmation at the relevant stop point.
- Keep dated raw MIDI, WAV files, dumps, reports, command logs, and hashes
  outside Git. Never overwrite a capture.
- `MEASURE_ME_*`, note `0`, `planned`, `unknown`, and `user-confirmed` are not
  validated hardware values.
- The simulator proves routing rules only; it cannot prove a port, sound, or
  latency.

## 0. Reproducible run folder and baseline

Create one immutable run folder, for example
`D:\Studio\drum-runs\2026-08-23-sd3-megakit-v1`, containing:

```text
run.json                         operator, date, Git commit, Windows version
environment.txt                  tool, driver, interface, SD3, VST versions
capture-inventory.yaml           reviewed list of every SD3 sound to capture
capture-session.json             generated sampler plan; resumable
commands.ps1                     exact commands used for the run
raw-midi/                        timestamped source observations
raw-wav/                         never modified after capture
reports/                         quality, library, DDrum4, DrumGizmo reports
checksums.sha256                 SHA-256 manifest for retained artefacts
```

Record SD3 and expansion versions, exact MegaKit/preset name, MIDI map, sample
rate, buffer, UMC404HD driver, input gains, routing, and the repository commit
in `run.json`. Export or photograph the SD3 preset and routing. WAV files alone
are not sufficient to reproduce a run.

Run the software baseline from the repository root:

```powershell
.\scripts\bootstrap.ps1
.\scripts\test-all.ps1
pio test -d firmware\ddrum4-midi-bridge -e native
pio run -d firmware\ddrum4-midi-bridge
```

Inventory devices read-only:

```powershell
.\.venv\Scripts\python.exe -m ddti devices
.\.venv\Scripts\python.exe -m midi_lab.cli list
.\.venv\Scripts\python.exe firmware\ddrum4-midi-bridge\tools\midi_probe.py --list
```

**Gate 0:** baseline is green, ports are inventoried, and the run folder is
created. Record port names; do not guess them after reconnecting hardware.

## 1. Hardware backups and initial state

### DDrum4

1. Record active Program, Palette, Local, MIDI channel, NOTE#, NOTE P,
   Sounds/Variations, and audio outputs.
2. Capture a settings dump through the documented panel/tool workflow. Start
   the receiver before a manual export; never issue an unknown SysEx request.
3. Validate and hash the dump before any Sound-bank transfer.

### DDTi and Arduino

1. Receive a DDTi dump with `--listen`; start it from the DDTi panel.
2. Verify the `.syx`, `.hex`, and metadata triad and retain hashes.
3. Photograph Arduino IN/OUT/THRU wiring and note installed firmware.
4. Do not flash firmware before Gate 7.

**Gate 1:** DDrum4 settings and the DDTi golden dump are safe; initial wiring
is documented.

## 2. Measure raw MIDI sources

Create a measured profile; do not fill a template with assumptions. For each
module (eDRUMin, DDTi, DDrum4), pad, and zone:

1. Open one read-only MIDI receiver.
2. Play soft, medium, and hard hits; test head/rim/bell/edge as applicable.
3. Sweep CC4 closed-to-open; test chick and splash.
4. Record aftertouch/choke as raw messages without guessing their meaning.
5. Repeat critical observations at least three times.
6. Save timestamped raw MIDI and label the physical pad.

For eDRUMin and DDTi, capture USB direct only, DIN/UMC only, and both. Declare
de-duplication only after proving that the selected route produces one event
per hit.

For DDrum4 Local Off, disconnect Arduino OUT first. A DDrum4 pad must emit raw
MIDI OUT but no local audio. Reconnect Arduino OUT only after that result.

**Gate 2:** endpoints, channels, notes, expressions, and duplicate paths are
measured. Clone the template into an out-of-repository `measured` profile and
replace all sentinels from evidence.

## 3. SD3 inventory and sound detection

Sound detection has two meanings:

- **Inventory detection:** the reviewed mapping from an SD3 MIDI event to its
  instrument, articulation, velocity layer, and variation.
- **Audio quality detection:** automated checks for silence, clipping, onset,
  level, and tail after recording. It cannot reliably name an unknown sound.

Before recording, build and review `capture-inventory.yaml`. It is the
reproducible contract for the entire SD3 MegaKit. One row is required for every
sound/articulation to keep in DrumGizmo and every candidate for DDrum4:

| Field | Required value |
|---|---|
| `instrument_id` | Stable English ID, e.g. `snare_main` |
| `sd3_name` | Exact SD3 instrument/articulation name |
| `midi_note`, `channel` | Measured SD3 trigger event |
| `articulation` | Stable English ID, e.g. `rimshot` |
| `velocities` | Exact ascending capture velocities |
| `repetitions` | Round-robin / variation count per velocity |
| `tail_seconds` | Required decay capture time |
| `audio_input`, `channels` | Physical recording input/layout |
| `ddrum4_tier` | `base`, `variation`, or `exclude` |
| `drumgizmo` | `include` or `exclude`, with reason |

Inventory kick, all snares/rims/side-sticks, toms, hi-hat states/chicks/splashes,
crashes/chokes, ride zones, stacks, and percussion. Audition every row in SD3
before capture. A changed MegaKit, map, velocity grid, or routing requires a
new inventory revision and session.

Use English identifiers in inventory, generated kit files, UI labels, and
reports. Preserve an SD3 proper name verbatim in `sd3_name`.

## 4. Create and run the resumable capture plan

Generate a sampler session from the reviewed inventory. Keep the exact command
in `commands.ps1` and retain both inventory and generated JSON. Example for one
reviewed inventory row:

```powershell
drum-sampler plan `
  --id sd3-megakit-v1 `
  --midi-output "<SD3 MIDI input>" `
  --audio-input "<UMC404HD ASIO input>" `
  --channels 2 `
  --request "snare_main:rimshot:38:24,40,56,72,88,104,120:4" `
  --session-output "D:\Studio\drum-runs\2026-08-23-sd3-megakit-v1\capture-session.json"
```

Create equivalent requests for every reviewed inventory row. Do not hand-edit a
generated session: regenerate it from the versioned inventory if the plan
changes. Review the take count against the inventory before recording.

Capture sends MIDI and records audio. Confirm SD3 MIDI input, UMC input, gains,
monitor path, and raw directory immediately before running:

```powershell
drum-sampler capture `
  --session "D:\Studio\drum-runs\2026-08-23-sd3-megakit-v1\capture-session.json" `
  --raw-directory "D:\Studio\drum-runs\2026-08-23-sd3-megakit-v1\raw-wav" `
  --library-output "D:\Studio\drum-runs\2026-08-23-sd3-megakit-v1\library.json" `
  --id sd3-megakit-v1 --source sd3 --license "<licence/provenance>" `
  --confirm-capture
```

If a take fails, retain its raw WAV and rejection reason. Correct only the
failed cell and resume the same session; record interventions in `run.json`.

**Gate 4:** all inventory rows have approved takes or a reviewed exception;
every raw WAV has provenance and a session ID.

## 5. Quality, library, and preservation

Run quality checks on the complete library:

```powershell
drum-sampler audit-quality `
  --library "D:\Studio\drum-runs\2026-08-23-sd3-megakit-v1\library.json" `
  --audio-root "D:\Studio\drum-runs\2026-08-23-sd3-megakit-v1\raw-wav" `
  --report "D:\Studio\drum-runs\2026-08-23-sd3-megakit-v1\reports\quality.json"
```

Review automated flags by listening. They find technical defects, not artistic
equivalence between articulations. Preserve rejected raws and report entries;
do not normalize, trim, or replace an immutable raw. Make a derived file and
record its parent hash when processing is needed.

After approval, hash the inventory, session, library, every raw, reports, SD3
preset export, measured profile, and commands file into `checksums.sha256`.
Archive the full run folder before producing either target kit.

**Gate 5:** the complete library is resumable, quality-reviewed, and archived.

## 6. Derive the DDrum4 kit

The DDrum4 kit is deliberately curated for Flash/memory limits; it is not the
complete library.

1. Create a versioned selection document from approved entries.
2. Mark a compact **base kit** of essential instruments and reliable layers.
3. Add **variations** only where memory measurement permits.
4. Build WAV/cfg and Sounds offline with `ddrum4edit`.
5. Retain selection, build log, input/output hashes, Sound inventory, NOTE P /
   variation map, and memory observations.
6. Re-run the simulator using final DDrum4 return notes.

Before upload, validate the settings dump, target, reserved Sound list, build
hashes, and transfer plan, then obtain explicit confirmation. After upload,
inspect the module, measure `MEM.LEFT` where possible, test Local Off return
notes, and save the receipt. Never delete raw capture data.

**Gate 6:** the reproducible compact base kit and approved variations are built;
at least one converted return note is audible through DDrum4 with Local Off.

## 7. Firmware and DDrum4 loop

1. Generate firmware headers only from a `ready` mapping with measured channel.
2. Compile and hash the `.hex`; verify board and port twice.
3. Obtain explicit confirmation before flashing.
4. Test DDrum4 raw → Arduino → DDrum4 MIDI IN → audio.
5. Test eDRUMin and DDTi routes, Note Off, rolls, velocity extremes, CC4, and
   proven chokes.

**Gate 7:** Arduino and Converter agree on Physical Event/Logical Sound, with
no duplicate hit in the tested matrix.

## 8. Derive and validate the complete DrumGizmo kit

DrumGizmo uses the complete approved library, not the DDrum4 subset:

```powershell
drum-sampler export-drumgizmo `
  --library "D:\Studio\drum-runs\2026-08-23-sd3-megakit-v1\library.json" `
  --audio-root "D:\Studio\drum-runs\2026-08-23-sd3-megakit-v1\raw-wav" `
  --output-directory "D:\Studio\drum-runs\2026-08-23-sd3-megakit-v1\drumgizmo-kit" `
  --note-map "<compiled-drumgizmo-midimap.json>" `
  --report "D:\Studio\drum-runs\2026-08-23-sd3-megakit-v1\reports\drumgizmo-export.json"

drum-sampler verify-drumgizmo `
  --kit-directory "D:\Studio\drum-runs\2026-08-23-sd3-megakit-v1\drumgizmo-kit"
```

Validate XML, WAV paths, channels, file channels, notes, articulation coverage,
and backend report. On Linux, preflight ALSA/JACK, confirm kit and ports, then
play every inventory articulation. Document unsupported expression rather than
silently collapsing it.

**Gate 8:** DrumGizmo loads and plays every approved complete-kit row; every
intentional omission is recorded.

## 9. Offline routing, SD3, state, and Master Merger

Before a hardware write, compile and simulate the measured profile:

```powershell
drum-control-center validate <measured-profile.yaml>
drum-control-center compile <measured-profile.yaml> --output <build-directory>
drum-control-center simulate <measured-profile.yaml> --source ddrum4 --note <raw-note> --velocity 106 --scene <scene>
```

For Metalcore and electronic/DnB cases, verify raw source → Physical Event →
Scene/VP → final DDrum4, SD3, and DrumGizmo targets. Archive runtime profile,
compiled maps, and hashes. Save the SD3 MegaKit manually and mark it
`user-confirmed`.

Without a Master Merger, DDrum4 is global-state authority and external PC
commands are `SD3-only` unless a return path is proven. With one, test DDrum4
panel, PC channel 15, and controller channel 14 for Scene and VP1–VP4
convergence and idempotent echoes.

**Gate 9:** source routes and renderer notes are reviewed; state converges or
documented limits are reflected in the UI.

## 10. Latency, soak, and fallback

- Log retained ASIO sample rate/buffer, profile, firmware, wiring, renderer.
- Measure at least 1,000 spaced events for DDrum4 and SD3; retain p50, p95,
  p99, max, drops, duplicates, and raw observations.
- Repeat with real sounds to separate MIDI transport from audio attack.
- Play for at least 30 minutes, including rolls, flams, chokes, CC4, Scenes.
- Perform one controlled reconnect. Stop/mute SD3 and open DDrum4 stems; no
  MIDI remapping should be needed for fallback.
- Verify Panic, shutdown, power-plan restoration, and no orphaned processes.

**Gate 10:** no loop, duplicate, or loss at normal rate; fallback works and
latency reports are archived.

## Per-test result sheet

| Field | Value |
|---|---|
| Date / operator | |
| Run ID / Git commit / profile hash | |
| SD3 MegaKit/preset and inventory revision | |
| Wiring and mode | |
| Source, pad, zone, velocity / raw MIDI | |
| Physical Event / Scene / VP | |
| SD3 instrument/articulation heard | |
| Raw WAV / library entry / quality verdict | |
| DDrum4 tier, return note, sound heard | |
| DrumGizmo note/instrument/articulation heard | |
| Drops / duplicates / echo guard / latency | |
| Artefact hashes, report, final verdict | |

## Starting a supervised session

When ready, provide the gate, active module and wiring, already-open MIDI
applications, run folder, SD3 MegaKit/preset revision, and whether any write
is authorized. We will run one gate at a time, starting read-only. No write is
performed without confirmation at its stop point.
