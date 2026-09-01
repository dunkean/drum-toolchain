# Greg Hybrid r15 — SD3 MegaKit

- Preset: `Greg_Hybrid_r15_MegaKit_v23_approved.sd3p`
- Preset SHA-256: `ecc54520557bdbc970051e7a391b6b7da611955bfe62132f00b9ee87c1474a20`
- Instruments SD3: **47**

## Validation de la capture v23 — 29 août 2026

- Masters stéréo 48 kHz : **939/939 acceptés**, 0 rejet, 0 manquant et 0 cellule round-robin dupliquée.
- Centres multicouches simultanés : **42/42 acceptés**, 0 rejet, 0 manquant et 0 cellule round-robin dupliquée.
- DrumGizmo autonome : **77 instruments**, **1001 samples**, **1018 fichiers** validés ; taille **1,747 Gio**.
- Package courant : `Greg-Hybrid-r15-MegaKit-v23-DrumGizmo-r5.zip`, **0,813 Gio**, SHA-256 `d5ce4279fe07c2be873141760584cc0505853b0faa668f039368bbd8262f4088`.
- Bibliothèque immuable : `41a72008e983b94fb0bf168f211e6e62debea938265cc5d5d260dfd95721dd75`.
- Validation interne r5 : `5c53c63e1502062b5586a686ea5a8776a1c8977852a4d0b5d8273c36997c5c7c`.
- Smoke DrumGizmo Linux r5 : `9403b948703a832a0087bd0277da39a7a8d038593e450ac36943b44b6e472034` ; le rapport lie explicitement le répertoire, les SHA du `drumkit.xml` et de la `midimap.xml`, le manifeste validé des 1 018 fichiers et la preuve audio de choke.
- Réconciliation du contrat courant : le plan MegaKit
  `d538c3d2ef3f334532dc64900942cf0dfdfaed9a66beb0724f7a173da9223a3f`
  et la midimap compilée
  `8e677a9c3779ce97006ca9d4c88856c6dbc04f3033b1e44181a8568c478f0940`
  ont été réaudités hors I/O. Les **1017 fichiers audio/instruments/midimap**
  de r5 sont identiques aux captures approuvées ; seul `drumkit.xml` ajoute
  le groupe de choke `hihat` aux 14 articulations de charleston.
- `dgvalidator --pedantic` 0.9.20 accepte les XML et les 1001 WAV. Le moteur
  DrumGizmo 0.9.20 charge ensuite les 2002 canaux en streaming, traite 48 000
  frames avec une entrée synthétique et une sortie factice, puis quitte
  proprement. Le même smoke compare ensuite le même Crash1 bow à vélocité 120,
  avec Poly Aftertouch 0 puis 127 à 250 ms : les attaques sont identiques à
  0,00 dB et la queue choked est atténuée de **23,69 dB**. Ce smoke est
  reproductible avec `scripts/smoke-drumgizmo-wsl.ps1` et n'ouvre aucun
  périphérique MIDI/audio.

Convention de nommage SD3: MIDI 0 = C-2 (MIDI 60 = C3).

Une ligne `variation partagée` ne duplique aucun WAV : elle réutilise exactement la note et le son indiqués par `shared_with`.

| Son logique | Déclenchement SD3 live | Source SD3 réelle | Layers de capture | RR | Kits / palettes | Statut |
| --- | --- | --- | --- | ---: | --- | --- |
| `kick.acoustic` | 24 (C0) | EZX2_ModernMetal / KD07_01 / kickR | 24, 40, 56, 72, 88, 104, 120 | 4 | deftones, metalcore | capture dédiée |
| `kick.sleep` | 25 (C#0) | SL-DEATH / KD02_01 / kickR | 24, 40, 56, 72, 88, 104, 120 | 3 | sleep_token | capture dédiée |
| `kick.dnb` | 26 (D0) | EZX2_ElectronicEdge / KD1_07 / kick1 | 24, 48, 72, 96, 120 | 2 | dnb | capture dédiée |
| `kick.industrial` | 27 (D#0) | EZX2_ElectronicEdge / KD2_31 / kick2 | 24, 48, 72, 96, 120 | 2 | industrial | capture dédiée |
| `kick.trap` | 28 (E0) | EZX2_ElectronicEdge / KD3_16 / kick3 | 24, 48, 72, 96, 120 | 2 | electro | capture dédiée |
| `snare1.metalcore` | 32 (G#0) | EZX2_ModernMetal / SD06_01 / snareR | 24, 40, 56, 72, 88, 104, 120 | 4 | metalcore | capture dédiée |
| `snare2.metalcore` | 33 (A0) | EZX2_ModernMetal / SD06_01 / snareFO | 24, 40, 56, 72, 88, 104, 120 | 3 | metalcore (vp2_flex-2) | capture dédiée |
| `snare1.metalcore_edge` | 34 (A#0) | EZX2_ModernMetal / SD06_01 / snareRO | 24, 40, 56, 72, 88, 104, 120 | 3 | partagé uniquement | capture dédiée |
| `rim1.rimshot` | 35 (B0) | EZX2_ModernMetal / SD06_01 / snareFX | 24, 48, 72, 96, 120 | 3 | dnb, electro, industrial, metalcore | capture dédiée |
| `rim1.cross` | 36 (C1) | EZX2_ModernMetal / SD06_01 / snareSL | 40, 64, 88, 112 | 2 | dnb, electro, industrial, metalcore | capture dédiée |
| `snare1.deftones` | 37 (C#1) + 100 (E6) + 101 (F6) | SL-DEATH / SD11_01 / snareR | 24, 40, 56, 72, 88, 104, 120 | 3 | deftones, metalcore (vp1_snare1-2) | capture dédiée |
| `snare2.deftones` | 38 (D1) | SL-DEATH / SD11_01 / snareFO | 24, 40, 56, 72, 88, 104, 120 | 3 | deftones, metalcore (vp2_flex-3) | capture dédiée |
| `snare1.deftones_edge` | 39 (D#1) | SL-DEATH / SD11_01 / snareRO | 24, 40, 56, 72, 88, 104, 120 | 3 | partagé uniquement | capture dédiée |
| `rim2.rimshot` | 40 (E1) | SL-DEATH / SD11_01 / snareFX | 24, 48, 72, 96, 120 | 3 | deftones, dnb (vp1_snare1-2), dnb (vp2_flex-3), electro (vp1_snare1-2), electro (vp2_flex-3), industrial (vp1_snare1-2), industrial (vp2_flex-3), metalcore (vp1_snare1-2), metalcore (vp2_flex-3) | capture dédiée |
| `rim2.cross` | 41 (F1) | SL-DEATH / SD11_01 / snareSL | 40, 64, 88, 112 | 2 | deftones, dnb (vp1_snare1-2), dnb (vp2_flex-3), electro (vp1_snare1-2), electro (vp2_flex-3), industrial (vp1_snare1-2), industrial (vp2_flex-3), metalcore (vp1_snare1-2), metalcore (vp2_flex-3) | capture dédiée |
| `snare1.sleep` | 42 (F#1) + 103 (G6) | SL-DEATH / SD01_01 / snareR | 24, 40, 56, 72, 88, 104, 120 | 3 | metalcore (vp1_snare1-3), sleep_token | capture dédiée |
| `snare2.sleep` | 43 (G1) | SL-DEATH / SD01_01 / snareFO | 24, 40, 56, 72, 88, 104, 120 | 3 | metalcore (vp2_flex-4), sleep_token | capture dédiée |
| `snare1.sleep_edge` | 44 (G#1) | SL-DEATH / SD01_01 / snareRO | 24, 40, 56, 72, 88, 104, 120 | 3 | partagé uniquement | capture dédiée |
| `rim_sleep.rimshot` | 45 (A1) | SL-DEATH / SD01_01 / snareFX | 24, 48, 72, 96, 120 | 3 | dnb (vp1_snare1-3), dnb (vp2_flex-4), electro (vp1_snare1-3), electro (vp2_flex-4), industrial (vp1_snare1-3), industrial (vp2_flex-4), metalcore (vp1_snare1-3), metalcore (vp2_flex-4), sleep_token | capture dédiée |
| `rim_sleep.cross` | 46 (A#1) | SL-DEATH / SD01_01 / snareSL | 40, 64, 88, 112 | 2 | dnb (vp1_snare1-3), dnb (vp2_flex-4), electro (vp1_snare1-3), electro (vp2_flex-4), industrial (vp1_snare1-3), industrial (vp2_flex-4), metalcore (vp1_snare1-3), metalcore (vp2_flex-4), sleep_token | capture dédiée |
| `snare1.dnb` | 47 (B1) | EZX2_ElectronicEdge / SD1_34 / snare1 | 24, 48, 72, 96, 120 | 2 | dnb | capture dédiée |
| `snare1.electro` | 48 (C2) | EZX2_ElectronicEdge / SD2_35 / snare2 | 24, 48, 72, 96, 120 | 2 | electro, metalcore (vp1_snare1-5) | capture dédiée |
| `snare2.electro` | 49 (C#2) | EZX2_ElectronicEdge / SD3_34 / snare3 | 24, 48, 72, 96, 120 | 2 | dnb, electro, industrial, metalcore (vp2_flex-5) | capture dédiée |
| `perc.clap` | 50 (D2) | EZX2_HipHop / Claps19 / claps | 40, 64, 88, 112 | 2 | deftones (vp4_percussion_variant-5), electro, metalcore (vp4_percussion_variant-5), sleep_token (vp4_percussion_variant-5) | capture dédiée |
| `perc.click` | 51 (D#2) | EZX2_HipHop / Sidestick2 / sidestick | 40, 64, 88, 112 | 1 | deftones (vp4_percussion_variant-4), dnb, metalcore (vp4_percussion_variant-4), sleep_token (vp4_percussion_variant-4) | capture dédiée |
| `tom1.electronic` | 52 (E2) | EZX2_ElectronicEdge / TH06 / tom1 | 24, 48, 72, 96, 120 | 2 | dnb, electro, industrial | capture dédiée |
| `tom2.electronic` | 53 (F2) | EZX2_ElectronicEdge / TL06 / tom4 | 24, 48, 72, 96, 120 | 2 | dnb, electro, industrial | capture dédiée |
| `tom3.electronic` | 54 (F#2) | EZX2_ElectronicEdge / TL06 / tom4 | 24, 48, 72, 96, 120 | 2 | dnb, electro, industrial | capture dédiée |
| `snare1.industrial` | 55 (G2) | SL-DFH / SD_ZEPPELIN4 / snareR | 24, 40, 56, 72, 88, 104, 120 | 3 | industrial, metalcore (vp1_snare1-4) | capture dédiée |
| `tom1.acoustic` | 56 (G#2) | EZX2_ModernMetal / TO05_01 / tom1R | 24, 48, 72, 96, 120 | 3 | deftones, metalcore | capture dédiée |
| `tom2.acoustic` | 57 (A2) | EZX2_ModernMetal / TO05_02 / tom2R | 24, 48, 72, 96, 120 | 3 | deftones, metalcore | capture dédiée |
| `tom3.acoustic` | 58 (A#2) | EZX2_ModernMetal / TO05_04 / tom4R | 24, 48, 72, 96, 120 | 3 | deftones, metalcore | capture dédiée |
| `tom4.acoustic` | 59 (B2) | EZX2_ModernMetal / TO05_05 / tom5R | 24, 48, 72, 96, 120 | 3 | metalcore | capture dédiée |
| `tom1.sleep` | 60 (C3) | SL-DEATH / TO03_01 / tom1R | 24, 48, 72, 96, 120 | 2 | sleep_token | capture dédiée |
| `tom2.sleep` | 61 (C#3) | SL-DEATH / TO03_02 / tom2R | 24, 48, 72, 96, 120 | 2 | sleep_token | capture dédiée |
| `tom3.sleep` | 62 (D3) | SL-DEATH / TO03_03 / tom3R | 24, 48, 72, 96, 120 | 2 | sleep_token | capture dédiée |
| `tom4.sleep` | 63 (D#3) | SL-DEATH / TO03_04 / tom4R | 24, 48, 72, 96, 120 | 2 | metalcore (vp2_flex-6), sleep_token (vp2_flex-6) | capture dédiée |
| `hh.bow` | 64 (E3) | EZX2_ModernMetal / HA02_01 / hatsTipTrig | 24, 48, 72, 96, 120 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | captures positionnelles: bow_closed CC4=127 → DG 112; bow_quarter CC4=96 → DG 113; bow_half CC4=64 → DG 114; bow_three_quarter CC4=32 → DG 115; bow_open CC4=0 → DG 116 |
| `hh.edge` | 65 (F3) | EZX2_ModernMetal / HA02_01 / hatsTrig | 24, 48, 72, 96, 120 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | captures positionnelles: edge_closed CC4=127 → DG 117; edge_third CC4=85 → DG 118; edge_half CC4=64 → DG 121; edge_two_thirds CC4=42 → DG 119; edge_open CC4=0 → DG 120 |
| `hh.pedal_close` | 66 (F#3) | EZX2_ModernMetal / HA02_01 / hatsPL | 40, 64, 88, 112 | 2 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `hh.pedal_splash` | 67 (G3) | EZX2_ModernMetal / HA02_01 / hatsPLO | 40, 64, 88, 112 | 2 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `hh.electronic_closed` | 68 (G#3) | EZX2_ElectronicEdge / HC1_03 / hatsCL | 40, 64, 88, 112 | 2 | dnb, electro | capture dédiée |
| `hh.electronic_open` | 69 (A3) | EZX2_ElectronicEdge / HO15 / hatsO1 | 40, 64, 88, 112 | 2 | dnb, electro, sleep_token | capture dédiée |
| `crash1.bow` | 72 (C4) | EZX2_ModernMetal / CR03_02 / crash2 | 24, 48, 72, 96, 120 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `crash1.edge` | 73 (C#4) | EZX2_ModernMetal / CR03_02 / crash2 | 0 | 0 | deftones, dnb, electro, industrial, metalcore, sleep_token | variation partagée → crash1.bow |
| `crash2.bow` | 74 (D4) | EZX2_ModernMetal / CR02_05 / crash5 | 24, 48, 72, 96, 120 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `crash2.edge` | 75 (D#4) | EZX2_ModernMetal / CR02_05 / crash5 | 0 | 0 | deftones, dnb, electro, industrial, metalcore, sleep_token | variation partagée → crash2.bow |
| `crash3.edge` | 76 (E4) | EZX2_ModernMetal / CR01_04 / crash4 | 24, 48, 72, 96, 120 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `splash1.acoustic` | 77 (F4) | EZX2_ModernMetal / SP02_03 / splash3 | 40, 64, 88, 112 | 2 | deftones, industrial, metalcore, sleep_token | capture dédiée |
| `splash2.acoustic` | 78 (F#4) | SL-DEATH / SP01_04 / splash2 | 40, 64, 88, 112 | 2 | deftones, industrial, metalcore | capture dédiée |
| `china1.edge` | 79 (G4) | EZX2_ModernMetal / CH01_02 / china2 | 40, 64, 88, 112 | 2 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `china1.bell` | 80 (G#4) | EZX2_ModernMetal / CH01_02 / china2 | 0 | 0 | deftones, dnb, electro, industrial, metalcore, sleep_token | variation partagée → china1.edge |
| `china2.edge` | 81 (A4) | EZX2_ModernMetal / CH04_06 / china6 | 40, 64, 88, 112 | 2 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `china2.bell` | 82 (A#4) | EZX2_ModernMetal / CH04_06 / china6 | 0 | 0 | deftones, dnb, electro, industrial, metalcore, sleep_token | variation partagée → china2.edge |
| `ride.bow` | 83 (B4) | EZX2_ModernMetal / RI01_04 / ride4 | 24, 48, 72, 96, 120 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `ride.bell` | 84 (C5) | EZX2_ModernMetal / RI01_04 / ride4BL | 40, 64, 88, 112 | 3 | deftones, dnb, electro, industrial, metalcore, sleep_token | capture dédiée |
| `stack.acoustic` | 85 (C#5) | EZX2_ModernMetal / CR01_03 / crash3 | 40, 64, 88, 112 | 2 | deftones, metalcore, sleep_token | capture dédiée |
| `stack.progressive_custom` | 86 (D5) | SL-PROGRESSIVEFOUNDRY / Crash4-5 / spock5 | 40, 64, 88, 112 | 2 | deftones (vp3_percussion_family-6), dnb (vp3_percussion_family-6), electro (vp3_percussion_family-6), industrial (vp3_percussion_family-6), metalcore (vp3_percussion_family-6), sleep_token (vp3_percussion_family-6) | capture dédiée |
| `perc.metallic` | 88 (E5) | EZX2_HipHop / Anvil / opentri | 40, 64, 88, 112 | 1 | industrial | capture dédiée |
| `stack.glitch` | 89 (F5) | EZX2_ElectronicEdge / FX1_42 / FX1 | 40, 64, 88, 112 | 1 | deftones (vp3_percussion_family-3), dnb, metalcore (vp3_percussion_family-3), sleep_token (vp3_percussion_family-3) | capture dédiée |
| `perc.utility` | 92 (G#5) | EZX2_HipHop / Cowbell1 / cowbell | 40, 64, 88, 112 | 1 | deftones, metalcore, sleep_token | capture dédiée |
| `perc.cowbell` | 92 (G#5) | EZX2_HipHop / Cowbell1 / cowbell | 0 | 0 | deftones (vp4_percussion_variant-2), metalcore (vp4_percussion_variant-2), sleep_token (vp4_percussion_variant-2) | variation partagée → perc.utility |
| `perc.woodblock` | 93 (A5) | EZX2_HipHop / Woodblock1 / cowbell | 40, 64, 88, 112 | 1 | deftones (vp4_percussion_variant-3), metalcore (vp4_percussion_variant-3), sleep_token (vp4_percussion_variant-3) | capture dédiée |
| `stack.metallic` | 88 (E5) | EZX2_HipHop / Anvil / opentri | 0 | 0 | deftones (vp3_percussion_family-4), industrial, metalcore (vp3_percussion_family-4), sleep_token (vp3_percussion_family-4) | variation partagée → perc.metallic |
| `stack.clap` | 99 (D#6) | EZX2_HipHop / Claps19 / claps | 0 | 0 | deftones (vp3_percussion_family-5), electro, metalcore (vp3_percussion_family-5), sleep_token (vp3_percussion_family-5) | variation partagée → perc.clap |
| `snare_layer.deftones_sd02` | 100 (E6) | SP-DeathAndDarkness / SD02 / Snare | 24, 40, 56, 72, 88, 104, 120 | 3 | partagé uniquement | capture dédiée |
| `snare_layer.deftones_sd30` | 101 (F6) | SP-DeathAndDarkness / SD30 / Snare | 24, 40, 56, 72, 88, 104, 120 | 3 | partagé uniquement | capture dédiée |
| `snare_layer.sleep_snare8` | 102 (F#6) | SL-PROGRESSIVEFOUNDRY / Snare8 / snareR | 24, 40, 56, 72, 88, 104, 120 | 3 | partagé uniquement | capture dédiée |
| `snare_layer.sleep_snare7` | 103 (G6) | SL-PROGRESSIVEFOUNDRY / Snare7 / snareR | 24, 40, 56, 72, 88, 104, 120 | 3 | partagé uniquement | capture dédiée |

## Position de caisse claire

Le profil eDRUMin v23 émet Snare1 head sur sa note brute et sa position sur
CC16. Le Converter transmet CC16 sans modification à SD3 sur CH10 pour les
variantes Metalcore, Deftones, Sleep Token, Industrial, DnB et Electro.
Snare2 reçoit sa position depuis le bloc NOTE P=8 du DDrum4 : les notes brutes
8–15 deviennent CC16 0–127 avant les notes SD3 33/38/43/49. Pour le renderer
DDrum4, les variantes acoustiques sont quantifiées Center/Mid/Edge sur
33/34/35 ; les rôles Tom4/électroniques restent mono-position. DrumGizmo
quantifie également Snare2 sur les captures Center/Mid/Edge 32–34, 37–39 ou
42–44 selon la scène. Seule la position CC16 de Snare1 attend encore ses
seuils physiques.

| Son réservé | Note | Source SD3 réelle | État |
| --- | ---: | --- | --- |

## Contrôle global

- Scene: Program Change sur CH14 ou CH15.
- VP1 Snare 1: CC20; VP2 surface flexible: CC21; VP3 famille Stack: CC22; VP4 variante Perc: CC23.
- Hi-hat SD3: notes 64/65 et ouverture continue CC4 sur le canal 10; pédale 66/67.
- Hi-hat DrumGizmo : notes discrètes 112–121 ; ses dix positions acoustiques,
  les deux pédales et les deux hats électroniques appartiennent au groupe
  `hihat`, donc toute nouvelle frappe étouffe la queue précédente.
- Chokes DrumGizmo : le Converter recible le Poly Aftertouch sur la note
  réellement active ; le moteur 0.9.20 et le package r5 ont passé la preuve
  audio automatisée.
- Les modules physiques gardent des notes brutes stables. Le Converter et Arduino appliquent la scène et les palettes.
