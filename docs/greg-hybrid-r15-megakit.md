# Greg Hybrid r15 — SD3 MegaKit

- Preset: `Greg_Hybrid_r15_MegaKit_v2.sd3p`
- Preset SHA-256: `ad1612b3f093335d188a6857b4efa5e1eeaf2d2551bf203c5505094a4cd7341a`
- Instruments SD3: **42**
Convention de nommage: MIDI 0 = C-1.

Une ligne `variation partagée` ne duplique aucun WAV : elle réutilise exactement la note et le son indiqués par `shared_with`.

| Son logique | Note | Source SD3 réelle | Layers de capture | RR | Kits / palettes | Statut |
| --- | ---: | --- | --- | ---: | --- | --- |
| `kick.acoustic` | 24 (C1) | EZX2_ModernMetal / KD07_01 / kickR | 24, 40, 56, 72, 88, 104, 120 | 4 | deftones, metalcore | capture dédiée |
| `kick.sleep` | 25 (C#1) | SP-DeathAndDarkness / KD03 / kickR | 24, 40, 56, 72, 88, 104, 120 | 3 | sleep_token | capture dédiée |
| `kick.dnb` | 26 (D1) | EZX2_ElectronicEdge / KD1_07 / kick1 | 24, 48, 72, 96, 120 | 2 | dnb | capture dédiée |
| `kick.industrial` | 27 (D#1) | EZX2_ElectronicEdge / KD2_31 / kick2 | 24, 48, 72, 96, 120 | 2 | industrial | capture dédiée |
| `kick.trap` | 28 (E1) | EZX2_ElectronicEdge / KD3_16 / kick3 | 24, 48, 72, 96, 120 | 2 | electro | capture dédiée |
| `snare1.metalcore` | 32 (G#1) | EZX2_ModernMetal / snareR / snareR | 24, 40, 56, 72, 88, 104, 120 | 4 | metalcore | capture dédiée |
| `snare2.metalcore` | 33 (A1) | EZX2_ModernMetal / snareFO / snareFO | 24, 40, 56, 72, 88, 104, 120 | 3 | metalcore (vp2_flex-2) | capture dédiée |
| `rim1.rimshot` | 35 (B1) | EZX2_ModernMetal / snareFX / snareFX | 24, 48, 72, 96, 120 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `rim1.cross` | 36 (C2) | EZX2_ModernMetal / snareSL / snareSL | 40, 64, 88, 112 | 2 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `snare1.deftones` | 37 (C#2) | SP-DeathAndDarkness / SD30 / snareR | 24, 40, 56, 72, 88, 104, 120 | 3 | deftones, metalcore (vp1_snare1-2) | capture dédiée |
| `snare2.deftones` | 38 (D2) | SP-DeathAndDarkness / SD30 / snareFO | 24, 40, 56, 72, 88, 104, 120 | 3 | deftones, metalcore (vp2_flex-3) | capture dédiée |
| `rim2.rimshot` | 40 (E2) | SP-DeathAndDarkness / SD30 / snareFX | 24, 48, 72, 96, 120 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `rim2.cross` | 41 (F2) | SP-DeathAndDarkness / SD30 / snareSL | 40, 64, 88, 112 | 2 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `snare1.sleep` | 42 (F#2) | SL-PROGRESSIVEFOUNDRY / Snare7 / snareR | 24, 40, 56, 72, 88, 104, 120 | 3 | metalcore (vp1_snare1-3), sleep_token | capture dédiée |
| `snare2.sleep` | 43 (G2) | SL-PROGRESSIVEFOUNDRY / Snare7 / snareFO | 24, 40, 56, 72, 88, 104, 120 | 3 | metalcore (vp2_flex-4), sleep_token | capture dédiée |
| `snare1.dnb` | 47 (B2) | EZX2_ElectronicEdge / snare1 / snare1 | 24, 48, 72, 96, 120 | 2 | dnb | capture dédiée |
| `snare1.electro` | 48 (C3) | EZX2_ElectronicEdge / SD2_35 / snare2 | 24, 48, 72, 96, 120 | 2 | electro, metalcore (vp1_snare1-5) | capture dédiée |
| `snare2.electro` | 49 (C#3) | EZX2_ElectronicEdge / SD3_34 / snare3 | 24, 48, 72, 96, 120 | 2 | dnb, electro, industrial, metalcore (vp2_flex-5) | capture dédiée |
| `perc.clap` | 50 (D3) | EZX2_HipHop / Claps19 / claps | 40, 64, 88, 112 | 2 | deftones (vp4_percussion_variant-5), electro, metalcore (vp4_percussion_variant-5), sleep_token (vp4_percussion_variant-5) | capture dédiée |
| `perc.click` | 51 (D#3) | EZX2_HipHop / Sidestick2 / sidestick | 40, 64, 88, 112 | 1 | deftones (vp4_percussion_variant-4), dnb, metalcore (vp4_percussion_variant-4), sleep_token (vp4_percussion_variant-4) | capture dédiée |
| `tom1.electronic` | 52 (E3) | EZX2_ElectronicEdge / tom1 / tom1 | 24, 48, 72, 96, 120 | 2 | dnb, electro, industrial | capture dédiée |
| `tom2.electronic` | 53 (F3) | EZX2_ElectronicEdge / tom2 / tom2 | 24, 48, 72, 96, 120 | 2 | dnb, electro, industrial | capture dédiée |
| `tom3.electronic` | 54 (F#3) | EZX2_ElectronicEdge / TL06 / tom4 | 24, 48, 72, 96, 120 | 2 | dnb, electro, industrial | capture dédiée |
| `snare1.industrial` | 55 (G3) | SL-DFH / SD_ZEPPELIN4 / snareR | 24, 40, 56, 72, 88, 104, 120 | 3 | industrial, metalcore (vp1_snare1-4) | capture dédiée |
| `tom1.acoustic` | 56 (G#3) | EZX2_ModernMetal / TO05_01 / tom1R | 24, 48, 72, 96, 120 | 3 | deftones, metalcore | capture dédiée |
| `tom2.acoustic` | 57 (A3) | EZX2_ModernMetal / TO05_02 / tom2R | 24, 48, 72, 96, 120 | 3 | deftones, metalcore | capture dédiée |
| `tom3.acoustic` | 58 (A#3) | EZX2_ModernMetal / TO05_04 / tom4R | 24, 48, 72, 96, 120 | 3 | deftones, metalcore | capture dédiée |
| `tom4.acoustic` | 59 (B3) | EZX2_ModernMetal / TO05_05 / tom5R | 24, 48, 72, 96, 120 | 3 | metalcore | capture dédiée |
| `tom1.sleep` | 60 (C4) | SL-DEATH / TO03_01 / tom1R | 24, 48, 72, 96, 120 | 2 | sleep_token | capture dédiée |
| `tom2.sleep` | 61 (C#4) | SL-DEATH / TO03_02 / tom2R | 24, 48, 72, 96, 120 | 2 | sleep_token | capture dédiée |
| `tom3.sleep` | 62 (D4) | SL-DEATH / TO03_03 / tom3R | 24, 48, 72, 96, 120 | 2 | sleep_token | capture dédiée |
| `tom4.sleep` | 63 (D#4) | SL-DEATH / TO03_04 / tom4R | 24, 48, 72, 96, 120 | 2 | metalcore (vp2_flex-6), sleep_token (vp2_flex-6) | capture dédiée |
| `hh.bow` | 64 (E4) | EZX2_ModernMetal / HA02_01 / hatsTipTrig | 24, 48, 72, 96, 120 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | captures positionnelles: bow_closed CC4=127 → DG 112; bow_quarter CC4=96 → DG 113; bow_half CC4=64 → DG 114; bow_three_quarter CC4=32 → DG 115; bow_open CC4=0 → DG 116 |
| `hh.edge` | 65 (F4) | EZX2_ModernMetal / HA02_01 / hatsTrig | 24, 48, 72, 96, 120 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | captures positionnelles: edge_closed CC4=127 → DG 117; edge_third CC4=85 → DG 118; edge_two_thirds CC4=42 → DG 119; edge_open CC4=0 → DG 120 |
| `hh.pedal_close` | 66 (F#4) | EZX2_ModernMetal / HA02_01 / hatsPL | 40, 64, 88, 112 | 2 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `hh.pedal_splash` | 67 (G4) | EZX2_ModernMetal / HA02_01 / hatsPLO | 40, 64, 88, 112 | 2 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `hh.electronic_closed` | 68 (G#4) | EZX2_ElectronicEdge / hatsCL / hatsCL | 40, 64, 88, 112 | 2 | dnb, electro | capture dédiée |
| `hh.electronic_open` | 69 (A4) | EZX2_ElectronicEdge / HO15 / hatsO1 | 40, 64, 88, 112 | 2 | dnb, electro, sleep_token | capture dédiée |
| `crash1.bow` | 72 (C5) | EZX2_ModernMetal / CR03_02 / crash2 | 24, 48, 72, 96, 120 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `crash1.edge` | 73 (C#5) | EZX2_ModernMetal / CR03_02 / crash2 | 0 | 0 | deftones, dnb, electro, industrial, metalcore, sleep_token | variation partagée → crash1.bow |
| `crash2.bow` | 74 (D5) | EZX2_ModernMetal / CR02_05 / crash5 | 24, 48, 72, 96, 120 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `crash2.edge` | 75 (D#5) | EZX2_ModernMetal / CR02_05 / crash5 | 0 | 0 | deftones, dnb, electro, industrial, metalcore, sleep_token | variation partagée → crash2.bow |
| `crash3.edge` | 76 (E5) | EZX2_ModernMetal / CR01_04 / crash4 | 24, 48, 72, 96, 120 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `splash1.acoustic` | 77 (F5) | EZX2_ModernMetal / SP02_03 / splash3 | 40, 64, 88, 112 | 2 | deftones, industrial, metalcore, sleep_token | capture dédiée |
| `splash2.acoustic` | 78 (F#5) | SL-DEATH / SP01_04 / splash2 | 40, 64, 88, 112 | 2 | deftones, industrial, metalcore | capture dédiée |
| `china1.edge` | 79 (G5) | EZX2_ModernMetal / CH01_02 / china2 | 40, 64, 88, 112 | 2 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `china1.bell` | 80 (G#5) | EZX2_ModernMetal / CH01_02 / china2 | 0 | 0 | deftones, dnb, electro, industrial, metalcore, sleep_token | variation partagée → china1.edge |
| `china2.edge` | 81 (A5) | EZX2_ModernMetal / CH04_06 / china6 | 40, 64, 88, 112 | 2 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `china2.bell` | 82 (A#5) | EZX2_ModernMetal / CH04_06 / china6 | 0 | 0 | deftones, dnb, electro, industrial, metalcore, sleep_token | variation partagée → china2.edge |
| `ride.bow` | 83 (B5) | EZX2_ModernMetal / RI01_04 / ride4 | 24, 48, 72, 96, 120 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `ride.bell` | 84 (C6) | EZX2_ModernMetal / RI01_04 / ride4BL | 40, 64, 88, 112 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `stack.acoustic` | 85 (C#6) | EZX2_ModernMetal / CR01_03 / crash3 | 40, 64, 88, 112 | 2 | deftones, metalcore, sleep_token | capture dédiée |
| `perc.metallic` | 88 (E6) | EZX2_HipHop / Anvil / opentri | 40, 64, 88, 112 | 1 | industrial | capture dédiée |
| `stack.glitch` | 89 (F6) | EZX2_ElectronicEdge / FX1_42 / FX1 | 40, 64, 88, 112 | 1 | deftones (vp3_percussion_family-3), dnb, metalcore (vp3_percussion_family-3), sleep_token (vp3_percussion_family-3) | capture dédiée |
| `perc.utility` | 92 (G#6) | EZX2_HipHop / Cowbell1 / cowbell | 40, 64, 88, 112 | 1 | deftones, metalcore, sleep_token | capture dédiée |
| `perc.cowbell` | 92 (G#6) | EZX2_HipHop / Cowbell1 / cowbell | 0 | 0 | deftones (vp4_percussion_variant-2), metalcore (vp4_percussion_variant-2), sleep_token (vp4_percussion_variant-2) | variation partagée → perc.utility |
| `perc.woodblock` | 93 (A6) | EZX2_HipHop / Woodblock1 / cowbell | 40, 64, 88, 112 | 1 | deftones (vp4_percussion_variant-3), metalcore (vp4_percussion_variant-3), sleep_token (vp4_percussion_variant-3) | capture dédiée |
| `stack.metallic` | 88 (E6) | EZX2_HipHop / Anvil / opentri | 0 | 0 | deftones (vp3_percussion_family-4), industrial, metalcore (vp3_percussion_family-4), sleep_token (vp3_percussion_family-4) | variation partagée → perc.metallic |
| `stack.clap` | 99 (D#7) | EZX2_HipHop / Claps19 / claps | 0 | 0 | deftones (vp3_percussion_family-5), electro, metalcore (vp3_percussion_family-5), sleep_token (vp3_percussion_family-5) | variation partagée → perc.clap |

## Réserve de position de caisse claire

Ces notes existent réellement dans le preset mais ne sont pas routées avant la mesure du message de position des pads.

| Son réservé | Note | Source SD3 réelle | État |
| --- | ---: | --- | --- |
| `snare1.metalcore_edge` | 34 (A#1) | EZX2_ModernMetal / snareRO / snareRO | not-routed-until-pad-measurement |
| `snare1.deftones_edge` | 39 (D#2) | SP-DeathAndDarkness / SD30 / snareMC | not-routed-until-pad-measurement |
| `snare1.sleep_edge` | 44 (G#2) | SL-PROGRESSIVEFOUNDRY / Snare7 / snareRO | not-routed-until-pad-measurement |

## Contrôle global

- Scene: Program Change sur CH14 ou CH15.
- VP1 Snare 1: CC20; VP2 surface flexible: CC21; VP3 famille Stack: CC22; VP4 variante Perc: CC23.
- Hi-hat SD3: notes 64/65 et ouverture continue CC4 sur le canal 10; pédale 66/67.
- Les modules physiques gardent des notes brutes stables. Le Converter et Arduino appliquent la scène et les palettes.
