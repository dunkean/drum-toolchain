# Greg Hybrid r15 — configuration matérielle et MIDI

Version : 2026-08-28  
Projet source : `profiles/projects/metalcore-r15-chain-simulator.yaml`

Cette fiche est le contrat actuel pour le premier test physique. Elle remplace
les anciens exemples CH10/CH11 présents dans les documents historiques. Les
adresses ci-dessous sont préparées et testées hors ligne ; les seuils de pads,
la pédale de hi-hat et les noms de ports live restent à mesurer avant flash.

## 1. Câblage

```text
DDrum4 MIDI OUT (CH12) ---+
DDTi MIDI OUT (CH2) ------+--> entrées/merger Arduino --> Arduino MIDI OUT --> DDrum4 MIDI IN
eDRUMin MIDI OUT (CH3) ---+
                                      |
                                      +--> THRU brut --> UMC MIDI IN --> PC

PC / UMC MIDI OUT ---------------------------------------> DDrum4 MIDI IN
                                                         (dumps uniquement,
                                                          à débrancher au jeu)
```

- Une seule source doit alimenter `DDrum4 MIDI IN` à la fois : Arduino pendant
  le jeu, UMC pendant les dumps.
- Le THRU sert à observer le flux brut sur le PC. Il ne doit pas revenir vers
  le merger ou l'une de ses entrées.
- Les trois modules gardent des canaux distincts. Les scènes et palettes ne
  changent jamais leurs notes brutes : Arduino et le Converter changent les
  notes rendues.

## 2. Répartition des pads

| Module | Pads / zones |
| --- | --- |
| DDrum4, CH12 | Kick, Snare2 head/rim/cross, Toms 1–3, China 1 edge/bell, China 2 edge/bell, hi-hat auxiliaire utilisé comme percussion |
| eDRUMin, CH3 | Snare1 head/rim/cross, hi-hat bow/edge/chick/splash + CC4, Ride bow/bell |
| DDTi, CH2 | Crash1 bow/edge, Crash2 bow/edge, Crash3 edge, Splash1, Splash2, Stack |

## 3. Notes brutes stables

Convention : MIDI 0 = C-1.

### DDrum4 — CH12

| Événement | Note | Nom |
| --- | ---: | --- |
| Kick | 0 | C-1 |
| Snare2 head | 8 | G#-1 |
| Snare2 rimshot | 16 | E0 |
| Snare2 cross-stick | 17 | F0 |
| Tom1 | 24 | C1 |
| Tom2 | 32 | G#1 |
| Tom3 | 40 | E2 |
| China1 edge / bell | 56 / 57 | G#3 / A3 |
| China2 edge / bell | 64 / 65 | E4 / F4 |
| Percussion auxiliaire | 72 | C5 |

### eDRUMin — CH3

| Événement | Note | Nom | Réglage |
| --- | ---: | --- | --- |
| Snare1 head | 0 | C-1 | head |
| Snare1 rimshot | 1 | C#-1 | rimshot |
| Snare1 cross-stick | 2 | D-1 | cross-stick |
| Hi-hat bow | 3 | D#-1 | ouverture CC4 |
| Hi-hat edge | 4 | E-1 | ouverture CC4 |
| Hi-hat chick | 5 | F-1 | pedal close |
| Hi-hat splash | 6 | F#-1 | pedal splash |
| Ride bow | 7 | G-1 | bow |
| Ride bell | 8 | G#-1 | bell |

Le profil à appliquer dans l'éditeur eDRUMin est
`profiles/physical/greg-hybrid-edrumin.yaml`. CC4 est déclaré avec
`fermé = 127` et `ouvert = 0`, mais cette polarité et les seuils doivent être
mesurés avec la vraie pédale. Ne pas flasher les valeurs de simulation.

### DDTi — CH2

| Entrée | Zone | Événement | Note | Nom |
| ---: | --- | --- | ---: | --- |
| 1 | Tip | Crash1 bow | 16 | E0 |
| 1 | Ring | Crash1 edge | 17 | F0 |
| 2 | Tip | Crash2 bow | 18 | F#0 |
| 2 | Ring | Crash2 edge | 19 | G0 |
| 3 | Tip | Crash3 edge | 20 | G#0 |
| 4 | Tip | Splash1 | 21 | A0 |
| 5 | Tip | Splash2 | 22 | A#0 |
| 6 | Tip | Stack | 23 | B0 |

Le layout est `profiles/physical/greg-hybrid-ddti-layout.yaml`. La préparation
hors ligne utilise le dump complet SHA-256
`43c64c486f72ec349c5ebee4020ef9e176f5d64033118f95fb25f6f81f84c70f`.
Le staged correspondant est
`build/rig/metalcore-r15/ddti-staged-from-golden.syx`, SHA-256
`1939ab91614e98fe96586406b26e11576e26448b5a285c0485db9682c9367f6b`.
Il ne doit être envoyé qu'après nouveau dump, comparaison, confirmation et
receipt matériel.

## 4. Scènes et palettes

Le contrôle logique PC utilise Program Change sur CH14/CH15 et CC20–23 pour
VP1–VP4. Les commandes natives reçues du panneau DDrum4 sont décodées sans
être renvoyées au module.

| Programme DDrum4 | Scène logique |
| ---: | --- |
| P1 / PC0 | Metalcore |
| P5 / PC4 | Sleep Token |
| P6 / PC5 | Deftones |
| P7 / PC6 | DnB |
| P9 / PC8 | Industrial |
| P11 / PC10 | Electro |

| PC natif | Cible logique |
| ---: | --- |
| 100–104, retour 105 | VP4 variante percussion, valeurs 1–5 / défaut 1 |
| 106–110, retour 111 | VP1 Snare1, valeurs 1–5 / défaut 1 |
| 112–116, retour 117 | VP2 surface flexible, valeurs 1–5 / défaut 1 |
| 118–122, retour 123 | VP3 famille percussion, valeurs 1–5 / défaut 1 |

Ces trente commandes sont visibles et déclenchables dans l'onglet
`Virtual kit & simulator`. Elles sont encore `simulation` tant que leur
round-trip physique n'a pas été capturé.

## 5. Hi-hat

- SD3 reçoit les notes bow/edge et CC4 continu sur CH10.
- DrumGizmo utilisera neuf positions discrètes, notes 112–120, générées depuis
  la capture SD3.
- Le moteur Arduino `CC4 → NOTE P` existe déjà, mais les cinq positions bow et
  quatre positions edge restent désactivées dans le firmware généré tant que
  polarité, endpoints et seuils réels ne sont pas mesurés.
- Chick et splash restent des Note-On séparés.

## 6. Séquence avant flash

1. Charger et calibrer `Greg Hybrid r15 MegaKit v3` dans SD3.
2. Capturer et valider les 746 prises, puis exporter/valider DrumGizmo.
3. Brancher les pads et relever chaque note/zone, CC4, choke et dynamique.
4. Créer un nouveau projet `deployment: live` depuis la campagne de mesure.
5. Compiler et vérifier dans `firmware-project-mapping.json` :
   `status: ready` et `hardware_flash: ready`.
6. Seulement alors, passer le shield Arduino en mode programmation et flasher.
7. Tester d'abord le THRU et les routes sans audio, puis SD3, DDrum4 et
   DrumGizmo séparément avant le jeu complet.

État actuel : aucun flash ni envoi DDTi n'est autorisé. Le blocage immédiat est
la calibration audio de la v3 chargée dans SD3.
