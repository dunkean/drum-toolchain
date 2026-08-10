# Metalcore standalone bank v1

Status: build specification. It replaces the compact transport candidates as
the audio-quality target; it does not approve any existing candidate by name.

## Objective

Build one playable metalcore kit first, using the measured 8,120 DDrum4-block
capacity. Keep 1,120 blocks unallocated for later Deftones/Sleep Token/DnB and
small electronic options. The initial bank budget is therefore 7,000 blocks.

## Quality allocation

| Logical family | Target blocks | Required initial behavior |
| --- | ---: | --- |
| Main snare (head, rim, position) | 1,200 | flagship velocity response; position where it is audibly useful |
| ZEITGEIST hi-hat | 1,150 | bow/edge, 4–5 openness states, chick, splash; CC4 plan documented |
| Crash 1 + crash 2 | 1,300 | long clean tails, four useful dynamics each; choke uses control data, not duplicate audio |
| Ride | 700 | bow, bell, edge; reduced dynamics acceptable |
| Kick | 250 | seven velocity layers, tight metalcore attack |
| Four tom identities | 600 | four short-to-medium velocity-layered toms; optional pitch variant before new audio |
| Splash/china/stack/perc | 400 | one clean articulation each, shared nested CYMB2 branches where needed |
| Electronics and alternate drums | 300 | short clap/click/impact; no duplicated acoustic cymbals |
| Reserve | 1,100 | protected until the main kit passes listening tests |

## Mandatory audio gates

The current `CYMB_995` POC sound exposed the failure mode this build prevents:
late attack, too-short tail, and an unusable low-velocity range. Every new
crash/ride candidate must pass before transfer:

1. Capture enough raw tail: 8–12 seconds for crash/ride, 3–4 seconds for
   splash/china, without a gate truncating the source.
2. Locate onset from measured waveform, retain a 2–5 ms pre-onset safety
   margin, and reject attack fade-ins.
3. Retain an audible crash tail for at least 4 seconds at the intended DDrum4
   quality setting; test it in headphones after transfer.
4. Test each selected velocity at 24, 56, 88, 110, and 127. No selected layer
   may be silent at its assigned input range.
5. Record actual encoded blocks and module listening result. A candidate that
   merely fits memory is not accepted.

## Build order

1. Rebuild and audition one long crash using a fresh tail-safe capture
   selection. This validates the full audio preparation chain before bulk
   import.
2. Build main snare and kick from the dense source library; load them beside
   the crash and listen on the DDrum4.
3. Build hi-hat after a dedicated CC4 behavior pass.
4. Add ride, toms, and auxiliary cymbals under the remaining measured budget.
5. Add alternate snare/electronic sounds only after the metalcore kit passes.

## Later options, not v1 blockers

- Deftones-style snare: derive from main snare using DDrum4 pitch/decay/mix
  first, then add audio only if required.
- Sleep Token: reuse cymbals; alter drum choices and routing/profile.
- DnB/trap/chillout/synthwave: occupy the protected electronic/alternate
  budget and use modernizer scene mapping later.

The palette/kit selection concept remains a later control layer. It must not
delay the playable metalcore bank or cause duplicated samples.
