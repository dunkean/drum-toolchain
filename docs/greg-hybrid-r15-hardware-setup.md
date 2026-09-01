# Greg Hybrid r15 — configuration matérielle et MIDI

Version : 2026-08-29
Projet source : `profiles/projects/metalcore-r15-chain-simulator.yaml`

Cette fiche est le contrat actuel pour le premier test physique. Elle remplace
les anciens exemples CH10/CH11 présents dans les documents historiques. Les
canaux et notes ci-dessous sont **prescrits par le toolchain et configurés sur
les modules** ; ils ne sont pas découverts avec les pads. Les réglages
électriques et la pédale de hi-hat sont calibrés après connexion des pads.

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
- Avec le câblage actuel, les trois sources arrivent au PC par le même endpoint
  UMC mais restent distinguées par CH12/CH2/CH3. Lors de la promotion live,
  choisir le transport `din` pour les trois. Choisir `usb` pour eDRUMin/DDTi
  seulement lorsqu'ils sont réellement connectés directement au PC.
- Les trois modules gardent des canaux distincts. Les scènes et palettes ne
  changent jamais leurs notes brutes : Arduino et le Converter changent les
  notes rendues.

## 2. Répartition des pads

| Module | Pads / zones |
| --- | --- |
| DDrum4, CH12 | Kick, Snare2 head/rim/cross, Toms 1–3, China 1 edge/bell, China 2 edge/bell, hi-hat auxiliaire utilisé comme percussion |
| eDRUMin, CH3 | Snare1 head/rim/cross + position CC16, hi-hat bow/edge/chick/splash + CC4, Ride bow/bell |
| DDTi, CH2 | Crash1 bow/edge, Crash2 bow/edge, Crash3 edge, Splash1, Splash2, Stack |

## 3. Notes brutes stables

Convention : MIDI 0 = C-1.

### DDrum4 — CH12

| Événement | Note | Nom |
| --- | ---: | --- |
| Kick | 0 | C-1 |
| Snare2 head positionnelle | 8–15 | G#-1–D#0 |
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
| Snare1 head | 0 | C-1 | head + position CC16 |
| Snare1 rimshot | 1 | C#-1 | rimshot |
| Snare1 cross-stick | 2 | D-1 | cross-stick |
| Hi-hat bow | 3 | D#-1 | ouverture CC4 |
| Hi-hat edge | 4 | E-1 | ouverture CC4 |
| Hi-hat chick | 5 | F-1 | pedal close |
| Hi-hat splash | 6 | F#-1 | pedal splash |
| Ride bow | 7 | G-1 | bow |
| Ride bell | 8 | G#-1 | bell |

Le profil à appliquer dans l'éditeur eDRUMin est
`profiles/physical/greg-hybrid-edrumin.yaml`. La position de Snare1 est émise
sur CC16 et transmise telle quelle à SD3 sur CH10. CC4 est déclaré avec
`fermé = 127` et `ouvert = 0`. La Drum Map, le câblage des deux jacks de snare
et la procédure eDRUMin complète sont dans
`docs/greg-hybrid-edrumin-setup.md`. La calibration réelle affine les seuils
sans changer ces adresses.

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

Le layout est `profiles/physical/greg-hybrid-ddti-layout.yaml` et sélectionne
les vingt presets 0–19. La répétition hors ligne depuis le golden complet
SHA-256 `43c64c486f72ec349c5ebee4020ef9e176f5d64033118f95fb25f6f81f84c70f`
produit `build/rig/metalcore-r15/ddti-staged-all-kits-from-golden.syx` ; son
plan canonique comporte 42 paquets, 340 octets modifiés et le SHA-256 candidat
`f49e2eed2b82cd2e03d75540cd2989182cf9f53b744ab5694f37ec2e2f50b877`.
Ce fichier est une répétition, pas le payload live : le payload envoyé doit
être régénéré depuis le dump courant, comparé, confirmé, puis relu dans un
nouveau dump matériel.

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
- DrumGizmo utilise dix positions discrètes, notes 112–121, générées depuis
  la capture SD3 : cinq bow et cinq edge. La note 121 est réservée au
  `edge_half` afin d’éviter les notes SD3 déjà occupées.
- Le package r5 place ces dix positions, les notes de pédale 66/67 et les hats
  électroniques 68/69 dans le groupe de choke `hihat`. Une nouvelle frappe
  étouffe donc la queue précédente au lieu d'empiler les samples ouverts.
- Le moteur Arduino `CC4 → NOTE P` existe déjà avec cinq positions bow et
  quatre positions edge. Le premier flash emploie le contrat eDRUMin normalisé
  `127 = fermé`, `0 = ouvert`; bow `72/73/74/75/76` aux bornes
  `15/47/79/111`, edge `40/41/42/43` aux bornes `31/63/95`.
- Chick et splash restent des Note-On séparés.
- La calibration de pédale après branchement peut ajuster les bornes dans un
  profil suivant ; elle ne change ni CH3, ni CC4, ni les notes de frappe.

## 5.1 Position des snares

- eDRUMin émet la position de la peau sur CC16, CH3.
- Le Converter et le runtime PC transmettent CC16 sans modification à SD3 sur
  CH10. Les six variantes de Snare1 du MegaKit déclarent ce contrôleur.
- Snare2 arrive du DDrum4 sous forme de huit notes positionnelles consécutives,
  8–15 dans le profil de simulation. Le Converter les normalise sur 0–127 et
  émet CC16 avant la note SD3 des quatre variantes de Snare2.
- Pour le retour DDrum4, ces huit positions sont quantifiées en trois zones :
  Center/Mid/Edge sur **8/11/12** dans `SNRE_981`, bornes normalisées 47/95. Tom4 et la snare
  électronique restent volontairement mono-position.
- DrumGizmo quantifie Snare2 avec les mêmes bornes normalisées 47/95 vers les
  captures Center/Mid/Edge : 32/33/34 en Metalcore, 37/38/39 en Deftones et
  42/43/44 en Sleep Token. Les rôles Tom4/électroniques restent mono-position.
- La campagne courante
  `build/measurements/greg-hybrid-r15-v23-r10`; elle contient 75 demandes :
  28 zones Note exactes, un sweep Snare2 `note_range`, les deux expressions
  `cc-004`/`cc-016`, 14 séquences isolées Note-On → Poly Aftertouch pour les
  chokes et les 30 commandes natives Program/Palette. Elle référence le
  SHA-256 source
  `38e902284046d7521d8ef305be0f73eff81013a195d4ef1145c8a442649043ca`.
  Elle devient une campagne de **vérification post-configuration** : ses traces
  peuvent révéler un défaut de câblage ou de configuration, mais ne doivent
  plus réécrire les notes du contrat.
- Les 30 commandes de panneau ne demandent pas 30 lancements manuels. Prévisualiser
  puis enregistrer leur séquence atomique avec :

  ```powershell
  ./scripts/capture-greg-hybrid-native-controls.ps1
  ./scripts/capture-greg-hybrid-native-controls.ps1 `
    -InputPort 'UMC404HD 192k MIDI In' -Capture -ConfirmSequence
  ```

  Une écoute unique est découpée en 30 preuves seulement si type, canal,
  adresse et ordre correspondent exactement ; sinon aucun fichier isolé n'est
  publié.
- Ces deux opérations sont aussi accessibles dans **Control Center → Kit,
  MIDI map, and palettes → Validation & deployment**. Le bouton **Capture all
  Scene/Palette controls (receive-only)…** affiche les 30 gestes avant de
  commencer et n'ouvre aucune sortie. **Probe isolated DDrum4
  echo/soft-through…** est un diagnostic distinct qui émet 300 messages après
  deux confirmations ; ne l'utiliser qu'avec Arduino OUT physiquement
  débranché de DDrum4 IN, conformément au schéma affiché.

## 6. Séquence avant flash

Observation du 31 août 2026 : Windows expose directement `eDrumIn BLACK` et
`TriggerIO`, ainsi que l'UMC et le MIDI4x4. eDRUMin et DDTi peuvent donc être
configurés par leur USB sans faire transiter l'écriture par Arduino.

1. Charger une fois puis calibrer `Greg Hybrid r15 MegaKit v23` dans SD3. Les changements de Scene/Palette suivants sont des commandes MIDI et ne rechargent pas le preset.
2. **Terminé le 29 août 2026** : 939 masters et 42 composites validés, puis
   export DrumGizmo r5 de 77 instruments / 1001 samples validé et empaqueté.
   `dgvalidator --pedantic` et le moteur DrumGizmo 0.9.20 ont chargé ce package
   sous WSL en streaming avec entrée synthétique/sortie factice, sans I/O
   matériel. Le test audio automatisé du même Crash1 bow mesure 0,00 dB
   d'écart avant choke et -23,69 dB dans la queue après Poly Aftertouch 127.
3. Capturer le dump courant DDTi sans émission : lancer
   `scripts/configure-greg-hybrid-ddti.ps1 -CaptureCurrent`, puis presser
   **FUNCTION UP + VALUE UP** sur le DDTi. L'outil vérifie les 42 paquets.
4. Appliquer le profil DDTi avec le même script en mode
   `-Apply -ConfirmWrite`. Ce mode exige son propre dump frais dans la même
   exécution : il refuse donc qu'un ancien fichier de base réécrive des réglages
   électriques plus récents. Presser **FUNCTION UP + VALUE UP** au dump
   pré-écriture, puis une seconde fois au readback demandé après l'envoi.
   Seuls canaux/notes confirmés sont modifiés ; gain, seuils, retrigger et
   trigger type sont conservés.
5. Appliquer `Greg Hybrid Raw Source Map` dans eDRUMin Control selon
   `docs/greg-hybrid-edrumin-setup.md`, attendre l'auto-save puis exporter le
   snapshot `.edp`. Aucun protocole CLI/SysEx de configuration stable n'est
   documenté par eDRUMin ; cette étape est donc manuelle. Créer ensuite le
   receipt lié au contrat avec :

   ```powershell
   ./scripts/confirm-greg-hybrid-edrumin.ps1 `
     -Snapshot '<snapshot .edp exporté>' -ConfirmApplied
   ```

Pour jouer un kit SD3 ordinaire sans ses aliases MegaKit, charger le preset
e-drum `Greg_Hybrid_Standard_SD3_Kits`. Son installation et ses fallbacks sont
documentés dans `docs/greg-hybrid-standard-sd3-map.md`.
Remettre `Kit_Metalcore_MidiMapping_Capture_V1` avant toute calibration ou
capture du MegaKit.
6. Compiler le projet live issu de ces trois preuves de configuration et
   vérifier dans `firmware-project-mapping.json` :
   `status: ready` et `hardware_flash: ready`.
   La capacité n'est plus une inconnue : le mapping de simulation complet a été
   compilé dans l'environnement non téléversable `uno_capacity` avec 339 routes,
   14 routes de pression/choke, 12 224 octets de Flash (37,9 %) et 795 octets
   de RAM (38,8 %). Reproduire ce
   contrôle avec `scripts/build-firmware-capacity.ps1`; cet environnement refuse
   volontairement `upload`.
   La commande `drum-control-center promote-configured` crée ce projet sans
   pads depuis le contrat compilé et les deux receipts. Elle conserve chaque
   canal/note/CC brut à l'identique et ne remplace que les endpoints `SIM_*`.
   Ce premier profil porte `validation_stage: post-flash-validation-pending` :
   il autorise le flash, pas le lancement live. Seule la campagne de traces
   avec pads produit ensuite un profil `hardware-verified` jouable.
7. Seulement alors, passer le shield Arduino en mode programmation et flasher.
   Aucun pad n'est nécessaire pour ce flash. Utiliser exclusivement
   `scripts/flash-ddrum4-bridge.ps1` avec le mapping live et les deux receipts ;
   tous les environnements matériels PlatformIO refusent un upload direct sans
   permis court généré par ce script.
8. Brancher ensuite les pads, calibrer gain/seuil/scan/retrigger/crosstalk,
   CC4 et CC16, puis utiliser les traces receive-only pour vérifier chaque
   zone, choke et commande. Tester enfin THRU, SD3, DDrum4 et DrumGizmo
   séparément avant le jeu complet.

## Test d'écoute sans pads après flash

Le test utilise le soft-thru eDRUMin pour injecter les trois canaux sources
dans Arduino. Chaque numéro doit produire le son résident indiqué. Une LED
DDrum4 sans audio est un échec : le test automatisé interdit désormais toute
note renderer dont la position ne contient aucun layer dans la banque r15.

| # | Entrée simulée | Son DDrum4 attendu | Note renderer |
|---:|---|---|---:|
| 1 | Snare1 head | Snare Metalcore center | 8 |
| 2 | Snare1 rim | Rimshot | 16 |
| 3 | Snare1 cross | Cross-stick | 18 |
| 4 | HH bow | Bow fermé | 72 |
| 5 | HH edge + CC4 | Edge semi-ouvert | 42 |
| 6 | HH pedal close | Fermeture pédale | 44 |
| 7 | HH pedal splash | Foot splash | 45 |
| 8 | Ride bow | Ride bow | 66 |
| 9 | Ride bell | Ride bell | 67 |
| 10–14 | Crash1/2/3 bow/edge | Unique crash résidente | 56 |
| 15–16 | Splash1/2 | Splash | 58 |
| 17 | Stack | HH edge ouvert | 43 |
| 18 | Kick | Kick acoustique | 0 |
| 19–20 | Flex pad, positions centre/bord | Tom4 / Floor Tom 2 | 27 |
| 21 | Snare2 rim | Rimshot | 16 |
| 22 | Snare2 cross | Cross-stick | 18 |
| 23 | Tom1 | Rack Tom 1 | 24 |
| 24 | Tom2 | Tom medium | 25 |
| 25 | Tom3 | Floor Tom 1 | 26 |
| 26–29 | China1/2 edge/bell | Unique china résidente | 59 |
| 30 | Percussion auxiliaire | Cowbell | 54 |

Le DDrum4 compact partage volontairement l'unique crash entre les cinq zones
physiques et l'unique china entre les quatre zones. Les articulations et sons
distincts restent disponibles dans SD3 et DrumGizmo. Le stack DDrum4 utilise
le HH edge ouvert conformément au budget final de la banque.

**Résultat matériel du 31 août 2026 : réussi.** Le firmware corrigé a produit
les 30 sons attendus dans l'ordre du tableau ; l'opérateur a confirmé qu'aucune
LED n'était muette et qu'aucun son n'était incorrect. Le THRU UMC a reçu les
60/60 événements Note On/Off. Ce résultat valide le transport et le renderer
DDrum4 sans pads, mais ne remplace pas la calibration physique des zones,
vélocités, CC4/CC16 et chokes.

Le lancement Windows final écrit un rapport persistant sous `local/reports`.
Avant de considérer une répétition valide, vérifier dans ce JSON que le
preflight est `ready`, que les hashes config/runtime correspondent au profil
promu, que les deux processus sont enregistrés et que le plan d'alimentation
est marqué `restored` après `Stop-Greg-Hybrid-Live.cmd`. Un preflight bloqué ne
lance désormais aucun processus et n'ouvre donc aucun port.

État au 31 août 2026 : DDTi est configuré avec readback identique, la Drum Map
eDRUMin possède un snapshot confirmé, et le firmware corrigé a été écrit puis
relu sur Arduino. Le diagnostic offline passe 5986/5986 et le test audio sans
pads passe 30/30 avec 60/60 événements au THRU. Le profil reste
`post-flash-validation-pending` tant que les pads ne sont pas branchés et
calibrés ; le launcher live le refuse donc encore. La v23 expose deux
caisses claires complètes : `Center`, `Mid`, `Edge`, `Rimshot` et `Side Stick`.
La calibration fermée a validé les 70 articulations sans silence technique ni
écrêtage. Le Center Deftones émet `37+100+101`; le Center Sleep Token émet
`42+103` (la couche 102 reste disponible mais n'est pas jouée par défaut à
cause de l'annulation de phase mesurée). Le mix v23 est approuvé. Le golden
dump et son receipt DDTi sont conservés localement. Les calibrations physiques
CC4/CC16/chokes/dynamique ont lieu après flash, pads branchés.

## Reste avant le statut « prêt à jouer »

Le code, les banques, les trois renderers et le firmware sont préparés. Les
étapes suivantes sont des validations du rig physique et ne peuvent pas être
remplacées par une simulation :

1. brancher les pads et régler gain, seuil, scan, retrigger, crosstalk et
   courbes sur chaque module, sans changer les notes contractuelles ;
2. compléter les 75 preuves receive-only de la campagne r10 : zones réelles,
   sweep Snare2, CC4, CC16, 14 chokes, six Program Change de scènes et 24
   commandes de palettes ; les 30 commandes de panneau utilisent la capture
   groupée atomique ci-dessus ;
3. promouvoir le profil en `hardware-verified`, ce qui déverrouille le
   lanceur live ;
4. valider séparément DDrum4, SD3 et DrumGizmo, puis mesurer les doublons,
   boucles, comportement DUAL/echo guard et latence. Le probe d'écho commence
   toujours en prévisualisation avec `scripts/probe-ddrum4-soft-through.ps1` ;
   son exécution exige de débrancher Arduino OUT, de relier UMC OUT directement
   au DDrum4 IN, puis de confirmer explicitement la topologie isolée ;
5. lancer la session Windows finale et conserver son rapport sous
   `local/reports`.
