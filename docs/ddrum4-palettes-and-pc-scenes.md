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

## Scene contract

A palette selection made on the DDrum4 emits a MIDI event. Its exact message
type/value is deliberately learned and recorded on this hardware before it is
made a contract. The modernizer then interprets that learned event as a scene
selector rather than treating it as a drum note.

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

The initial implementation will only **observe and log** palette messages.
Mapping changes or DAW actions require an explicit scene contract, preventing
an accidental palette press from silently changing a live PC configuration.
