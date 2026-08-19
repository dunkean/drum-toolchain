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

The owner then reported that 950 cuts off too early. The cause was threshold
tail trimming: its ten prepared WAVs lasted only 0.13..0.74 seconds. The
preparation policy now supports trimming silence before onset without trimming
the captured decay. `SNRE_949` contains the same five-velocity by two-position
layout with every prepared sample fixed at 1.8 seconds. It encodes to 911
blocks and all 911 messages were sent successfully; the receipt is
`D:\Studio\ddrum4-transfers\snre-949-positional-long-20260819.json`. Hardware
audition remains required before promotion. The owner deleted the obsolete
`SNRE_950` candidate and then measured `MEM.LEFT = 5.97` with `SNRE_949` still
installed. Relative to the verified-core baseline of 6.88, the module therefore
accounts for about 910 blocks for 949, matching the 911-message build closely.
The owner initially confirmed the length of `SNRE_949`, but later analogue
noise analysis showed why its low layers could sound like hiss: every raw take
had an approximately -95 dBFS input noise floor, which normalisation raised to
about -59 dBFS for velocity 24. It was therefore superseded rather than kept.

`SNRE_943` uses the same five-velocity by two-position matrix and the same
1.8-second preparation, captured directly from the WASAPI render endpoint.
All ten source files have exact digital silence before the hit and the final
100 ms of every prepared WAV is also exactly silent. Its 911 packets were
transferred with receipt
`D:\Studio\ddrum4-transfers\snre-943-positional-digital-c1-20260819.json`.
The owner approved its decay, dynamics and positional behavior, then deleted
949. Its measured module cost is exactly 0.91 (`MEM.LEFT` 3.38 to 2.47 on
installation, then back to 3.38 after deleting 949). `SNRE_943` is the
accepted flagship snare.

## Hi-hat source correction

`HHAT_996` is retained only as a protocol candidate. Its nine nominal CC4
openings are nearly identical short closed hits because the capture sent GM
closed-hat note 42. The corrected dense plan uses Toontrack's direct notes for
five-plus tip openness states, edge states, pedal chick, and foot splash; see
`profiles/capture/sd3-djentle-beast-flagship-hihat.json`. Do not build a
flagship sound from the old CC4-fine WAVs.

The corrected session completed on 2026-08-19 through shared WASAPI at 48 kHz
and the physical UMC OUT 3/4 to IN 3/4 loop. It produced 336 stereo takes:
16 articulations by seven velocities by three round robins. Automated review
found zero silent takes below -70 dBFS and zero clipped takes. The neutral
library is
`D:\Studio\sample-library\sd3-modern-metal-djentle-beast\hihat-flagship-c1\library.json`.
The DDrum build stage resamples selected copies to 44.1 kHz; raw captures stay
immutable at 48 kHz.

The physical loop capture was rejected after hardware listening because
normalising its very low input level also raised the analogue noise floor and
made every tail end in loud hiss. The sampler now accepts a versioned
`loopback:` input and records the SD3 output directly from the Windows WASAPI
render endpoint. The selected clean bow/pedal source is
`D:\Studio\sample-library\sd3-modern-metal-djentle-beast\hihat-ddrum-selected-digital-c2`.

`HHAT_947` is the accepted primary hi-hat sound. Its eight Note-P positions
are chick, tight bow, closed bow, loose bow, open 1, open 3, open 5 and foot
splash. Tight and closed each have soft/hard timbres, for ten layers total.
All 902 encoded packets were transferred through the UMC and the owner
confirmed that the positions sound correct, have natural tails and no hiss.
The module reported `MEM.LEFT = 4.18` after installation. That reading also
included the rejected analogue 948 candidate, so it must not be used to claim
an isolated 947 cost. The transfer receipt is
`D:\Studio\ddrum4-transfers\hhat-947-flagship-digital-c2-20260819.json`.

Eight positions cannot also hold a useful edge family without removing bow
openings or pedal articulations. The edge family is therefore a separate
Arduino-selected nested sound rather than a velocity hack. The clean digital
source at
`D:\Studio\sample-library\sd3-modern-metal-djentle-beast\hihat-edge-selected-digital-c1`
contains tight/closed edge at two velocities, loose and open 1..4 edge, plus
the missing open-4 bow transition. `CYMB_946` compiles these as eight Note-P
positions and ten layers. It reports 1,059 encoded blocks and was transferred
successfully with receipt
`D:\Studio\ddrum4-transfers\cymb-946-hihat-edge-digital-c1-20260819.json`.
The owner assigned it to CYMB1 with `Note P = 8` and confirmed that all eight
positions sound correct, without hiss or cut tails. `MEM.LEFT` changed from
4.18 to 3.20, so its authoritative cost is 980 blocks. It is now the accepted
edge companion.

The live palette note ranges were verified directly: CYMB1 `G#5` is MIDI
80..87, CYMB2 `E6` is MIDI 88..95 and HHAT `C7` is MIDI 96..103. These
adjacent eight-note ranges must remain non-overlapping in the generated
Arduino routing contract.

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

## Direct digital flagship crashes

The clean direct-render library is
`D:\Studio\sample-library\sd3-modern-metal-djentle-beast\crashes-selected-digital-c1`.
It contains seven velocities each for notes 49 and 57. Strong-hit material
remains above -90 dBFS for about 5.1 and 5.2 seconds respectively, with exact
digital silence outside the render.

The first `CYMB_945` build used velocity-dependent windows from 0.7 to 5.2
seconds. Hardware listening rejected it because panel and medium hits selected
audibly short layers. It was deleted. The accepted c2 build gives all seven
layers a fixed 6.5-second window and disables tail trimming; silence after the
natural SD3 decay is cheap, clean safety margin rather than analogue noise.
It encodes to 2,283 blocks and was transferred with receipt
`D:\Studio\ddrum4-transfers\cymb-945-crash1-digital-long-c2-20260819.json`.
The owner confirmed that the long crash sounds correct. `MEM.LEFT` is 1.87,
although its isolated cost was not measured because the short 945 was deleted
between readings.

The owner deleted obsolete compact crashes 994 and 995, increasing `MEM.LEFT`
from 1.87 to 2.52. `CYMB_944` c2 uses the identical seven-layer/6.5-second
policy and also encodes to 2,283 blocks. All packets were transferred with
receipt
`D:\Studio\ddrum4-transfers\cymb-944-crash2-digital-long-c2-20260820.json`.
The owner confirmed that it sounds correct. Final `MEM.LEFT` is 245 blocks.

Both flagship crashes are therefore accepted, but the current audition
palette exposes a slot conflict: CYMB1=944 and CYMB2=945 leave the accepted
946 hi-hat-edge sound stored but unassigned. The final nested compile must
repack each crash sound as seven velocity layers on its primary position plus
three single-layer hi-hat-edge positions. Across both CYMB slots this retains
six useful edge openness states while keeping both accepted crash families.
After the two combined replacements pass listening, delete standalone 946;
do not pretend the present palette provides crash 1, crash 2 and hi-hat edge
simultaneously.

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

1. Compile two combined nested crash/hi-hat-edge sounds: seven full crash
   velocity layers plus three edge positions per CYMB slot.
2. Transfer and audition them under unused IDs, then delete 944, 945 and the
   standalone 946 only after the combined pair passes.
3. Finalize the palette and generated Arduino contract with the verified note
   ranges; use the remaining 245-block class of budget only for very short
   electronic sounds or metadata-safe reserve.
