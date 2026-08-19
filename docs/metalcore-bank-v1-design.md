# Metalcore standalone bank v1

Status: build specification. It replaces the compact transport candidates as
the audio-quality target; it does not approve any existing candidate by name.

## Objective

Build one flagship metalcore kit first, using about 80% of the measured 8,120
DDrum4-block capacity. The final target is 6,500 used blocks and 1,620 reserve
blocks. The reserve is for later Deftones/Sleep Token/DnB replacements and
small electronic options, not for multiple lower-quality acoustic kits.

## Quality allocation

| Logical family | Target blocks | Required initial behavior |
| --- | ---: | --- |
| Main snare head | 1,000 | ten samples: five velocity bands by two head positions |
| Rim/cross-stick | 500 | ten samples: six rimshot dynamics and four cross-stick dynamics |
| ZEITGEIST hi-hat | 1,400 | five bow openings, two edge states, chick and foot-splash branch |
| Crash 1 + crash 2 | 1,400 | three dynamics each; low/medium tails may be shorter, hard tails remain natural |
| Ride | 650 | bow, bell and edge; reduced dynamics acceptable |
| Kick | 300 | seven velocity layers, tight metalcore attack |
| Four tom identities | 700 | four velocity-layered toms; pitch variants do not duplicate audio |
| Splash/china/stack/foot-splash | 350 | one clean articulation each, shared nested branches where needed |
| Electronics | 200 | short clap, click, DnB snare/kick and one FX where space permits |
| Reserve | 1,620 | protected for listening-driven replacements and later alternate scenes |

## Flagship sample layouts

The main snare uses all ten available DDrum4 layers as a `5 velocity x 2
position` grid. This is preferable to eleven center-only velocity captures:
five crossfaded dynamics retain musical velocity response while the two
position families preserve the eDRUMin positional signal. The separate rim
sound uses six rimshot layers and four cross-stick layers. Arduino routing may
select the appropriate DDrum Note-P/variation branch, but must not synthesize
or smooth trigger dynamics.

The original CC4 capture is not a valid source for the flagship hi-hat. It sent
CC4 followed by GM closed-hat note 42, but the resulting nine WAV families are
nearly identical short closed hits. The local Toontrack note map instead
exposes discrete articulations: open levels on notes 24, 25, 26 and 60; tight
and closed tip on 63 and 61; tight and closed edge on 62 and 64; pedal chick
on 44; and open-pedal/foot-splash on 23. The reproducible dense capture grid is
`profiles/capture/sd3-djentle-beast-flagship-hihat.json`.

The DDrum4 hi-hat input has only eight Note-P positions, despite a sound having
ten layers. The first bench candidate will therefore use five bow openness
states, two edge states, and a pedal branch across those eight positions. The
two remaining layers can add a second velocity timbre to the most important
closed state and distinguish chick from foot splash with an Arduino-selected
velocity window. This exact layout remains a bench hypothesis until all ten
direct notes have been captured, heard, and replayed through the module. The
firmware must only select the declared note/velocity branch; it must not add
trigger cleanup or dynamics processing.

The two main crashes use three useful dynamics apiece. Their low and medium
samples may use shorter captured tails, while the hard layer retains the full
auditioned decay. This spends memory on audible dynamics without multiplying
six identical 6.5-second noise floors.

New flagship sounds use free IDs below the compact `987..999` range. The
compact core remains installed until each replacement has been transferred,
auditioned and assigned. Only then is its old counterpart deleted.

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
