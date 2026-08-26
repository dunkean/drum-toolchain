# SD3 MegaKit V1 — Capture List for the 8 MB DDrum4 Bank

This is the minimum V1 addition to the existing Metalcore capture set. It
implements the electronic and percussion side of the architecture without
trying to fit a second complete acoustic kit into DDrum4 Flash.

The notes in the **SD3 note** column are the logical MegaKit namespace. The
**DDrum4 return note** is the note emitted to the DDrum4 Sound block after the
converter/Arduino route. They are intentionally different.

## Decision on the current Metalcore mix

Keep the current Metalcore kit as the V1 source. It is the correct acoustic
baseline for the Metalcore programs and gives the variations a coherent common
character. Do not expect a Variation to turn a Metalcore kick into a real DnB
kick, 808, glitch, or industrial hit: those require separate captured source
sounds.

For capture, create a dedicated **DDrum4 Capture** SD3 preset derived from the
Metalcore kit. Keep the deliberate close-mic/instrument character, but disable
unwanted master limiting, global reverb, and non-essential bleed/room buses.
Record the same SD3 output and gain configuration for every V1 addition. This
keeps the tonal family while avoiding a permanently printed full mix.

## Pre-flight: keep existing captures; do not duplicate them

Do not recapture the approved Metalcore acoustic kick, snare, hi-hat, crash,
ride, and tom material only to populate this list. Confirm that the existing
library has the Metalcore core used by the following logical notes:

| Existing family | Logical SD3 notes |
|---|---:|
| Metalcore acoustic kick | 24 |
| Metalcore snare and rim/cross-stick | 32–36 |
| Metalcore toms | 56–59 |
| Acoustic hi-hat | 64–67 |
| Acoustic cymbals and stack if already captured | 72–85 |

If an item in this table was never captured as a valid raw source, add it to
the campaign before capture; it is a core dependency, not a future variation.

## Required V1 additions

### S01 — electronic kick variants

| Capture ID | SD3 note | DDrum4 return note | DDrum4 destination | V1 purpose |
|---|---:|---:|---|---|
| `kick_dnb` | 26 | 2 | S01 P3 | Short electronic/DnB kick |
| `kick_industrial` | 27 | 3 | S01 P4 | Distorted industrial kick |
| `kick_808` | 28 | 4 | S01 P5 | 808/Trap kick |

Capture each at five velocities (`24, 48, 72, 96, 120`) with two repetitions.
Use controlled tails: a long 808 tail belongs in the source library, but the
DDrum4 selection may be shortened after memory measurement.

### S05 — electronic snare variants

| Capture ID | SD3 note | DDrum4 return note | DDrum4 destination | V1 purpose |
|---|---:|---:|---|---|
| `snare_dnb` | 47 | 38 | S05 P7 | DnB/Electro snare |
| `snare_industrial_trap` | 48 and 49 | 39 | S05 P8 | Industrial/Trap electronic snare |
| `clap_main` | 50 | 49 | S10 L2 / P2 | Clap-as-snare and hybrid accent |
| `electronic_rim_click` | 51 | 52 | S10 L5 / P5 | Electronic rim/click |

`snare_industrial_trap` is deliberately one V1 source routed to both SD3 notes
48 and 49. Split it into separate industrial and trap samples only after the
8 MB bank has been measured and the difference is musically necessary.

Capture the two e-snares at five velocities with two repetitions. Capture clap
and click at four velocities (`40, 64, 88, 112`); use two repetitions for clap
and one for click.

### S10 — Stack and percussion bank

| Capture ID | SD3 note | DDrum4 return note | S10 layer/position | V1 purpose |
|---|---:|---:|---|---|
| `stack_acoustic` | 85 | 48 | L1 / P1 | Metalcore and hybrid Stack |
| `electronic_hat_closed` | 68 | 50 | L3 / P3 | DnB/Trap closed electronic hat |
| `electronic_hat_open` | 69 | 51 | L4 / P4 | DnB/Trap open electronic hat |
| `metallic_hit` | 88 | 53 | L6 / P6 | Industrial hit |
| `glitch_noise_hit` | 89 | 55 | L7 / P8 | DnB/Industrial glitch |
| `low_electronic_tom` | 90 | 54 | L8 / P7 | Low e-tom; also the impact source |
| `cowbell` | 92 | 54 | L9 / P7 variation | Utility and DnB/Dance option |
| `woodblock` | 93 | 55 | L10 / P8 variation | Utility and DnB/Dance option |

Capture Stack, electronic hats, and low e-tom at four velocities with two
repetitions. Capture metallic hit, glitch, cowbell, and woodblock at four
velocities with one repetition unless the SD3 sound has genuine round robins.

P7 and P8 are deliberately shared in DDrum4: a Variation chooses low e-tom
versus cowbell, and glitch versus woodblock. They are separate SD3 notes and
separate raw capture entries, so DrumGizmo can retain the complete kit.

## Explicit V1 deferrals

Do not spend first-bank memory on these unless a rehearsal proves they are
needed:

| Logical SD3 note | Deferred item | V1 fallback |
|---:|---|---|
| 86 | E-China | Existing China/Crash auxiliary route |
| 87 | E-Crash | Existing Crash auxiliary route |
| 91 | High electronic tom | Pitch/route from `low_electronic_tom` |
| 94 | Impact/Boom | Derived from low e-tom or metallic hit |
| 95 | Reverse/transition | DAW/SD3-only effect |
| 96–99 | Shaker, tambourine, noise burst, alternate clap | Future complete DrumGizmo expansion |
| 100–111 | Future electronic reserve | Keep unused |

## V1 simulation checks

Before capture, use these representative logical targets in the complete-chain
simulator after the measured profile is updated:

| Scene | Physical pad | Expected V1 target |
|---|---|---|
| Metalcore | Stack | `stack_acoustic` / SD3 85 / DDrum4 48 |
| DnB | Stack | `glitch_noise_hit` / SD3 89 / DDrum4 55 |
| DnB | Perc | `electronic_rim_click` / SD3 51 / DDrum4 52 |
| Industrial | Stack | `metallic_hit` / SD3 88 / DDrum4 53 |
| Trap | Stack or Perc | `clap_main` / SD3 50 / DDrum4 49 |
| DnB | Kick | `kick_dnb` / SD3 26 / DDrum4 2 |
| Industrial | Snare2/Tom4 | `snare_industrial_trap` / SD3 48 / DDrum4 39 |

After the SD3 campaign is created, enter the rows in the **SD3 capture
campaign** page of Drum Control Center. The campaign saves the complete raw
library; only the later DDrum4 build selects and compresses the 8 MB subset.
