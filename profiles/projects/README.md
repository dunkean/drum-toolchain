# Project profiles

Files in this directory are the versioned, data-driven description of a
playable rig.  They are not capture records and do not turn a planned mapping
into a measured one.

`greg-hybrid-mvp.yaml` is the M1 vertical-slice fixture.  It deliberately
describes only the wiring already known:

```text
USB modules (including UMC404HD) <-> PC
DDrum4 MIDI OUT -> Arduino MIDI IN
UMC404HD MIDI OUT -> DDrum4 MIDI IN
```

Every USB endpoint label, source MIDI channel, incoming note, controller,
output note, Program Change and final renderer mapping that has not been
measured is marked `planned` with a `MEASURE_ME_*` value.  Such a value is not
usable as a runtime MIDI address.

## Operating boundary

`LIVE_USB_PRIMARY` is the only intended PC-assisted profile in this fixture:
USB sources are primary and duplicate DIN copies are rejected by identity,
not by a time-only heuristic.  `DIN_ONLY` is available for the standalone
DIN path and disables USB sources.

`DUAL` is explicitly forbidden.  It requires the isolated hardware echo and
DIN gate plus the missing Master Merger; this profile must not be used to
claim that either is installed or verified.  Until then, UI-originated scene
or VP controls are SD3-only, while a DDrum4-originated native control may be
considered only after its address is measured.

SD3's mega kit remains a manual mapping operation.  The profile can name
logical sounds but it neither supplies nor implies an SD3 preset, MIDI note,
or successful import.

## Scene and VP variants

A `logical_routes` value may remain one logical target, or be a list of
variants.  A list has exactly one fallback without `when`; each other item
names `logical_target` and one or more state variables under `when`.

```yaml
snare_main.head:
  - logical_target: snare.electronic.head
    when: {vp1_snare1: 1}
  - logical_target: snare.metalcore.head
```

Conditional predicates must not overlap.  The compiler places them before the
fallback in `runtime-profile.yaml`, so the C++ Converter resolves Scene and VP
before selecting the SD3, DDrum4, or DrumGizmo renderer note.

## Filling placeholders

Replace a placeholder only with the capture/bench reference that established
it, then change its status to `measured` (or `user-confirmed` for a manual
SD3 assignment).  A routing/compiler validation must pass after each change.
Do not infer MIDI addresses from module defaults, old profile files, or
listening tests.
