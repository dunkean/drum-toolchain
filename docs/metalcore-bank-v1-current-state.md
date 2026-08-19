# Metalcore standalone bank v1 — current hardware state

## Clean reload on 2026-08-19

The owner performed `F.AL`, erased the complete sound memory and confirmed the
empty hardware baseline at `MEM.LEFT = 8.12`. The automated verified-core
transfer then sent all 13 frozen sounds through the UMC route, with individual
receipts under `D:\Studio\ddrum4-transfers\core-20260819-154801`. The final
panel reading is `MEM.LEFT = 6.88`, exactly matching 1,240 installed blocks.

This core is deliberately a playable safety net, not the target allocation.
The approved direction is now one flagship metalcore kit using approximately
6,500 blocks, with priority on the positional snare and multi-state ZEITGEIST
hi-hat. Flagship replacements use unused IDs and are auditioned before any
core sound is removed.

Status: active soundbank work. This document distinguishes sounds merely
stored in DDrum4 memory from a palette-assigned, playable kit.

## Verified stored core

The DDrum4 was emptied, then its capacity was measured as 8,120 blocks. The
following original SD3-derived sounds were transferred successfully and the
module subsequently reported 6,880 blocks free. The reported 1,240 used
blocks therefore agree exactly with the hardware display.

| DDrum4 sound | Blocks | Intended role |
| --- | ---: | --- |
| `KICK_997` | 124 | main metalcore kick |
| `SNRE_998` | 94 | main snare, seven velocity layers |
| `RIM_999` | 30 | rimshot / cross-stick bank |
| `HHAT_996` | 43 | initial hi-hat CC4 candidate |
| `TOM_993`, `TOM_992`, `TOM_991`, `TOM_990` | 21, 52, 37, 52 | four compact tom identities |
| `CYMB_995`, `CYMB_994` | 350, 308 | compact crash candidates; not approved as flagship crashes |
| `CYMB_987`, `CYMB_988`, `CYMB_989` | 89, 20, 20 | compact ride bow / bell / edge candidates |

This is a **stored sound core**, not yet a complete palette. It must remain
intact while replacements are auditioned. A group-and-number that already
exists cannot be overwritten: DDrum4 shows `dUP` and ignores the transfer.

## Positional snare candidate

`SNRE_950` was reproducibly built and transferred on 2026-08-19. It contains
ten original SD3 Modern Metal / Djentle Beast samples: five velocity bands at
CC16 position 0 and the same five bands at position 127. Its layer matrix
covers each of the eight DDrum4 velocity points and eight Note-P position
points exactly once. `ddrum4edit` reports 236 encoded blocks and the complete
236-message transfer through `UMC404HD 192k MIDI Out 9` has a receipt at
`D:\Studio\ddrum4-transfers\snre-950-positional-20260819.json`.

The two source-position families are measurably distinct, particularly at the
harder velocities, but hardware acceptance is not yet a listening result.
Until the owner confirms `SNRE_950` with `SHIFT + SOUND`, `SHIFT + LISTEN`, and
a new `MEM.LEFT` reading, retain `SNRE_998` and treat 950 as a candidate only.

## Hi-hat source correction

`HHAT_996` is retained only as a protocol candidate. Its nine nominal CC4
openings are nearly identical short closed hits because the capture sent GM
closed-hat note 42. The corrected dense plan uses Toontrack's direct notes for
five-plus tip openness states, edge states, pedal chick, and foot splash; see
`profiles/capture/sd3-djentle-beast-flagship-hihat.json`. Do not build a
flagship sound from the old CC4-fine WAVs.

## New isolated cymbal reference

`CYMB_993` was built and sent on 2026-08-10 as the first unambiguous cymbal
reference:

- one original `crash_main_1` source capture at MIDI velocity 56;
- one active layer only, rather than an undocumented partial 2–6 layer curve;
- mono 44.1 kHz, 6.5 seconds, 327 DDrum4 blocks;
- 327 SysEx packets sent via `UMC404HD 192k MIDI Out 9` and recorded in
  `D:\Studio\ddrum4-b6\cymb_993_one_layer\transfer-receipt.json`.

The module accepted the sound and `SHIFT + MEM.LEFT` reported **5,930 blocks**
free. Its real allocation cost is therefore **950 blocks**, not the 327
encoded packets reported by `ddrum4edit`. This is a material codec/allocation
difference: from now on `MEM.LEFT` is the only authority for long cymbals and
an encoded-block report is only a transfer-size estimate.

The first listening gate is intentionally simple: assign `CYMB_993` to a
temporary CYMB palette role, select variation 1 and panel decay 100, then
test the panel button at low, medium and high velocity. It isolates sample
tail and channel decay from pad calibration and from any nested routing. This
gate passed: the owner confirmed the sound is good.

`CYMB_991` is the second long mono crash candidate. It uses the independent
`crash_main_2` source at velocity 88, the same 6.5-second preparation and one
active layer. The PC sender completed its 327-packet UMC transmission, but the
module did **not** accept/store it: `MEM.LEFT` remained `5.93` MB. Direct audio
probes sent from that UMC MIDI output likewise produced only the input noise
floor. The likely cause is that the UMC MIDI OUT no longer reaches DDrum4 MIDI
IN (which is currently needed by the Arduino loop). Do not retransmit this
sound until the single physical DDrum4 MIDI-IN source is confirmed. Once the
route is restored, reserve about 950 real blocks rather than trusting the 327
encoded packets.

## Important audio finding

The current SD3 `Djentle Beast` source captures do not yet meet the flagship
crash requirement. At the loudest captured hit, real signal remains above
-66 dBFS for approximately:

| Source | Measured useful tail |
| --- | ---: |
| crash main 1 | 2.55 s |
| crash main 2 | 2.04 s |
| ride bow | 3.77 s |
| ride edge | 5.34 s |

The later 6.5-second preparation keeps low-level material but cannot create a
new musical crash tail. Do not call either crash a finished metalcore sound
until SD3 is captured through a mixer/output configuration with a genuine
longer tail, or a different approved source is selected.

## Palette target after listening gates

The stable roles remain:

```text
kick | snare | rim | tom-high | tom-mid | tom-low | perc | cymb-1 | cymb-2 | hi-hat
```

The first playable palette will assign the verified core to these roles. Ride,
alternate snare and electro content will occupy nested role branches only
after the current crash and hi-hat behavior have passed listening. This keeps
the Arduino contract stable while palette assignments evolve.

## Next soundbank actions

1. Confirm that `SNRE_950` is present and audible, and record `MEM.LEFT`.
2. Restore SD3 Modern Metal / Djentle Beast, its `out_WORLDE` MIDI input, and
   the UMC output-3/4 to input-3/4 audio loop; then execute the direct-note
   flagship hi-hat capture grid.
3. Capture/select an SD3 crash source with a measured musical tail beyond four
   seconds, then create two seven-layer flagship crashes with an audited
   velocity layout.
4. Build the palette assignment only after the three flagship families
   (snare, hi-hat, crashes) have passed their own listening gates.
