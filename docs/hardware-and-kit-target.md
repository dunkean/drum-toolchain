# Hardware and Kit Target

This is the concise English working copy of the owner's `Infos.md`. The full
original French document is versioned at
[`reference/hardware-inventory-original.fr.md`](reference/hardware-inventory-original.fr.md).

## Physical kit

The target hybrid kit has a DDrum mesh kick, a primary central-sensor DDrum
mesh snare (head, rim and potentially positional sensing), a secondary DDrum
snare, four tom positions, and these cymbal roles: ZEITGEIST ZG H-12
continuous hi-hat, three-zone Millenium CR-18X ride, two expressive crashes
with choke, two splashes, two chinas, a stack, DDrum cymbals and optional
percussion from the older DDrum hi-hat. The exact trigger-module assignment is
intentionally not embedded in this physical model.

## Electronics and audio

- DDrum4 SE is the standalone Clavia soundbank target.
- DDTi and eDRUMin 4 are trigger/MIDI sources; eDRUMin is the likely home for
  demanding continuous hi-hat, positional snare and multi-zone work, but this
  remains a measured wiring decision, not a fixed assumption.
- An Arduino with MIDI shield translates DDTi/eDRUMin events into the generated
  nested DDrum4 routing contract. A hardware MIDI merger can precede it.
- Superior Drummer 3 is the principal Windows engine; DrumGizmo is the free
  Linux alternative.
- The UMC404HD supplies four line outputs to an XR18. Capture is initially
  stereo and must later support named `kick`, `snare`, `left`, and `right`
  channels, with ambience in left/right.

## Soundbank priorities

The DDrum4 user bank is about 8 MB and must contain no original DDrum factory
audio. It should be a playable metalcore kit first. Preserve the greatest
detail for the primary metalcore snare, expressive ZEITGEIST hi-hat, and two
main crashes. Reduce layers, round robins, duration, or articulation coverage
for lower-priority pieces when measured encoded memory requires it.

The desired variants are Main Metalcore, a brighter/reverberant Deftones-style
snare variant, a Sleep Token-oriented mix/kit variant, and a compact
electronic/drum-and-bass variant. The dense neutral capture library is the
master source; DrumGizmo keeps quality while the DDrum4 compiler selects a
small compatible subset.
