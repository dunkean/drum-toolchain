# DDrum4 palettes as cross-engine scenes

## Decision

Use DDrum4 **Palette** mode as the primary editable composition surface.
Sounds remain stored once in DDrum4 memory; a palette assigns a coherent set
of those sounds to the ten stable logical roles. DDrum4 kits `P1`–`P26` are
then lightweight performance/routing presets, not the place where every sound
combination is manually rebuilt.

This reflects the physical rig: the Arduino routes pads to stable logical
roles, while a palette decides which musical identity is currently loaded for
those roles.

## Roles that remain stable

```text
kick | snare | rim | tom-high | tom-mid | tom-low | perc | cymb-1 | cymb-2 | hi-hat
```

The Arduino targets a role's fixed DDrum4 input note/Note-P branch and never a
palette number. Therefore replacing a snare palette item does not require an
Arduino reflash, as long as the role's MIDI layout remains stable.

## Exact DDrum4 Program Change contract

The DDrum4 SE v1.5 manual explicitly documents that the module both receives
and transmits these Program Change messages whenever a kit or palette is
selected. They use the module's configured MIDI channel (`C1`..`C16`):

| Program Change | DDrum4 action |
| ---: | --- |
| 0..25 | select user kit `P.1`..`P.26` |
| 26..98 | select factory kit `F.27`..`F.99` |
| 99 | return to default `PAL` mode |
| 100..104 | select Kick palette 1..5 |
| 105 | revert Kick group to the selected kit |
| 106..110 | select Snare palette 1..5 |
| 111 | revert Snare group to the selected kit |
| 112..116 | select Toms palette 1..5 |
| 117 | revert Toms group to the selected kit |
| 118..122 | select Percussion palette 1..5 |
| 123 | revert Percussion group to the selected kit |

Set the module's Program Change policy to `P.On`. `P.OF` disables this
bidirectional behavior. Do **not** use `P.TH` in the closed DDrum4/Arduino
loop: that setting immediately copies incoming Program Changes to MIDI OUT
and can feed the same event around the loop again.

With the fixed wiring, a local DDrum4 selection reaches the PC unchanged over
the shield's hardware THRU and is therefore observable even while Arduino DIN
OUT is filtering notes. A PC-originated selection travels directly from UMC
MIDI OUT to DDrum4 MIDI IN. The Arduino does not need to echo a DDrum-origin
Program Change back to the same module.

`midi-lab record` now retains Program Change values in trace files and
`trace-info` prints their decoded DDrum4 meaning. A single external selection
can be sent only behind the explicit write flag, for example:

```powershell
$env:PYTHONPATH = 'tools/midi-lab/src'
python -m midi_lab.cli send-ddrum4-program `
  --output 'UMC404HD 192k MIDI Out 9' --channel 12 --program 108 --send
```

This selects Snare palette 3 when the module uses MIDI channel 12. The channel
is an explicit argument because it must match the live `C1..C16` setting.

## Scene contract

The modernizer interprets the decoded event as a scene selector rather than
treating it as a drum note.

One scene record will contain:

| Field | Meaning |
| --- | --- |
| `scene_id` | stable semantic name, e.g. `metalcore-main` |
| `ddrum_palette_event` | learned MIDI message emitted by palette selection |
| `ddrum_palette_assignments` | ten logical-role sound assignments |
| `modernizer_profile` | SD3 / DrumGizmo note/articulation mapping profile |
| `external_actions` | optional DAW, lighting, or automation events |

Examples of future scenes: `metalcore-main`, `dnb-snare`, `sleep-token-hybrid`,
and `electro-layered`.

## PC mode

When SD3 is the sound engine, the same palette event is carried through the
modernizer. It may select a mapping profile, emit an explicit virtual-MIDI
automation event to Live, or both. SD3 does not need to mirror the DDrum4
sound-memory layout; it only needs a complete kit and an articulation map for
the selected scene.

The first bank phase observes and logs palette messages. Mapping changes or
DAW actions still require an explicit scene contract, preventing an accidental
palette press from silently changing a live PC configuration.
