# Sound bank Metalcore r15 — contenu, configuration DDrum4 et test global

> **Archive du transfert audio r15.** Les tailles et Sounds DDrum4 restent une
> référence de la banque installée, mais les exemples MIDI CH10/CH11 et le
> firmware de diagnostic décrits ici ne sont plus le contrat du rig global.
> Utiliser [Greg Hybrid r15 — configuration matérielle et MIDI](greg-hybrid-r15-hardware-setup.md)
> pour les canaux CH12/CH2/CH3, les notes, CC4/CC16, Programs/Palettes et le gate de
> flash actuels.

Version du document : 2026-08-26
Banque décrite : `kit-metalcore-4-hd-c4-r15-tom-rr-final`
Manifeste : `encoded-kit-v12-restored-cymbals/kit-build.json`
SHA-256 du manifeste : `A344AE43C938E4A8850C7525ED4E1DE8B706F0641F8F96C84B1B1BCC47BE19F8`
## 1. État réel et objectif

La banque audio r15 est installée sur le DDrum4. Elle contient dix Sounds,
8 037 blocs occupés et laisse 83 blocs libres. L'affichage attendu sur le
module est donc environ `MEM.LEFT 0.08`. Les deux derniers Sounds remplacés
après suppression manuelle sont `TOM_981` et `CYMB_982`; leurs reçus de
transfert se trouvent dans le sous-dossier `hardware-transfer` du package.

Le test de la banque et le test du système MIDI complet sont deux validations
différentes :

| Élément | État au 2026-08-26 |
| --- | --- |
| Audio encodé r15 | prêt et transféré |
| Dix Sounds visibles dans le DDrum4 | attendu |
| Palette/kit DDrum4 décrit ci-dessous | à configurer sur le module |
| Merger → Arduino → DDrum4 | architecture validée, câblage final à réaliser |
| Mapping Arduino global | **non prêt** : le firmware courant ne contient que deux routes de diagnostic C12/17–18 |
| DDTi | canal et notes cibles définis ci-dessous; configuration réelle à relever/appliquer |
| eDRUMin | canal et notes cibles définis ci-dessous; configuration réelle à relever/appliquer |
| Hi-hat continu CC4 → positions DDrum4 | moteur implémenté, activation bloquée jusqu'aux mesures physiques |

Il ne faut donc pas flasher le `generated_mapping.h` actuel pour un essai
global : il ne jouerait pas le kit. Il sert uniquement au précédent diagnostic
de transport.

## 2. Architecture du workflow standalone final

```text
DDTi DIN OUT (canal 10) --------------------+
eDRUMin DIN OUT (canal 11) -----------------+--> MIDI merger
DDrum4 MIDI OUT (canal 12, Local OFF) ------+        |
                                                      v
                                              Arduino MIDI IN
                                                      |
                                           traduction vers les notes
                                            imbriquées du DDrum4
                                                      |
                                              Arduino MIDI OUT
                                                      |
                                              DDrum4 MIDI IN
                                               canal 12, audio
```

Le merger doit être un vrai merger MIDI actif, pas un câble passif en Y. Les
trois sources doivent conserver des canaux différents afin que l'Arduino puisse
distinguer deux notes identiques provenant de deux appareils différents.

Sur le shield Arduino, le connecteur THRU peut continuer vers l'entrée MIDI de
l'UMC404HD pour observer le flux brut fusionné sur le PC. Il ne doit pas être
rebouclé vers le merger.

## 3. Vocabulaire de la banque

- **Sound** : conteneur DDrum4 chargé en mémoire, par exemple `TOM_981`.
- **Note P** : position interne P1 à P8 d'un Sound. Avec `NOTE P = 8`, le
  module adresse ces positions par huit notes MIDI consécutives à partir de
  `NOTE #`.
- **Layer** : couche de vélocité ou échantillon appartenant à une position.
- **Variation** : masque de layers choisi dans le menu SOUND du module. Une
  variation ne duplique pas nécessairement l'audio.
- **RR** : round robin. `séquence` signifie que le DDrum4 alterne les samples
  d'une même position; sinon l'Arduino doit alterner entre deux Note P.
- **Vélocité cible** : vélocité MIDI à laquelle le layer a été capturé et
  prévu. Le DDrum4 interpole/sélectionne les layers d'une même Note P selon la
  vélocité reçue.

## 4. Occupation mémoire et affectation des dix canaux

Le fichier machine lisible qui reprend exactement cette banque installée est
[`profiles/banks/metalcore-r15-installed.yaml`](../profiles/banks/metalcore-r15-installed.yaml).
Il décrit les Sound IDs, `NOTE #`, `NOTE P`, layers, vélocités, variations,
round robins, pitchs partagés et occupation mémoire; il ne contient aucun dump
ni mécanisme d'écriture vers le module.

La mesure à retenir est le nombre de blocs DDrum4. La taille des fichiers MIDI
de transfert sur le PC inclut le protocole SysEx et ne représente pas la mémoire
audio affichée par le module.

| Canal physique DDrum4 | Sound à affecter | `NOTE #` | `NOTE P` | Plage reçue | Blocs |
| --- | --- | ---: | ---: | ---: | ---: |
| KICK | `KICK_981` | 0 | 8 | 0–7 | 605 |
| SNARE | `SNRE_981` | 8 | 8 | 8–15 | 911 |
| RIM | `RIM_981` | 16 | 8 | 16–23 | 365 |
| TOM HIGH | `TOM_981` | 24 | 8 | 24–31 | 1 057 |
| TOM MID | `PERC_981` | 32 | 8 | 32–39 | 353 |
| TOM LOW | `CYMB_981` | 40 | 8 | 40–47 | 1 401 |
| PERC | `PERC_982` | 48 | 8 | 48–55 | 303 |
| CYMBAL 1 | `CYMB_982` | 56 | 8 | 56–63 | 1 038 |
| CYMBAL 2 | `CYMB_983` | 64 | 8 | 64–71 | 1 271 |
| HI-HAT | `HHAT_981` | 72 | 8 | 72–79 | 733 |
| **Total** | **10 Sounds** |  |  |  | **8 037** |

L'affectation apparemment étrange de `PERC_981` à TOM MID ou de `CYMB_981` à
TOM LOW est volontaire. Le nom du canal physique ne limite pas la catégorie du
Sound : le canal sert ici de conteneur MIDI de huit positions.

## 5. Carte MIDI de sortie — notes réellement jouables

Les numéros ci-dessous sont les notes que l'Arduino doit envoyer au DDrum4 sur
le canal 12. Les positions absentes sont réservées et silencieuses.

| Note | Sound / position | Résultat |
| ---: | --- | --- |
| 0 | `KICK_981` P1 | kick acoustique, layers 84/124 |
| 1 | `KICK_981` P2 | kick acoustique RR2, forte vélocité |
| 4 | `KICK_981` P5 | electronic tom low, seulement en variation 3 |
| 8 | `SNRE_981` P1 | snare center, layers 20/68/124 |
| 9 | `SNRE_981` P2 | snare center RR2, forte vélocité |
| 10 | `SNRE_981` P3 | snare center RR3, forte vélocité |
| 11 | `SNRE_981` P4 | snare mid, layers 20/68/124 |
| 12 | `SNRE_981` P5 | snare edge, layers 20/124 |
| 16 | `RIM_981` P1 | rimshot, layers 20/124 |
| 17 | `RIM_981` P2 | rimshot RR2, forte vélocité |
| 18 | `RIM_981` P3 | cross-stick, vélocité source 124 |
| 19–21 | `RIM_981` P4–P6 | seconde série rimshot/RR2/cross-stick sans nouvel audio |
| 24 | `TOM_981` P1 | rack tom 1 = tom medium pitché +4, layers 68/124 |
| 25 | `TOM_981` P2 | tom medium, layers 68/124, RR automatique à 124 |
| 26 | `TOM_981` P3 | floor tom 1 = floor 2 pitché +4, layers 68/124 |
| 27 | `TOM_981` P4 | floor tom 2, layers 68/124, RR automatique à 124 |
| 38 | `PERC_981` P7 | snare électronique DnB, variation 1 |
| 39 | `PERC_981` P8 | snare électronique Industrial/Trap, variation 2 |
| 40 | `CYMB_981` P1 | hi-hat edge closed, layers 68/124 |
| 41 | `CYMB_981` P2 | hi-hat edge quarter-open, layers 68/124 |
| 42 | `CYMB_981` P3 | hi-hat edge half-open, layers 68/124 |
| 43 | `CYMB_981` P4 | hi-hat edge open, layers 68/124 |
| 44 | `CYMB_981` P5 | hi-hat pedal close, vélocité source 104 |
| 45 | `CYMB_981` P6 | hi-hat foot splash, vélocité source 104 |
| 54 | `PERC_982` P7 | cowbell, vélocité source 104 |
| 55 | `PERC_982` P8 | woodblock, vélocité source 104 |
| 56 | `CYMB_982` P1 | crash; pitch dépend de V1/V2/V3 |
| 58 | `CYMB_982` P3 | splash, layers 68/124 |
| 59 | `CYMB_982` P4 | china, layers 68/124 |
| 66 | `CYMB_983` P3 | ride bow, layers 68/124 |
| 67 | `CYMB_983` P4 | ride bell, layers 68/124 |
| 72 | `HHAT_981` P1 | hi-hat bow closed, layers 68/124 |
| 73 | `HHAT_981` P2 | hi-hat bow loose, layers 68/124 |
| 74 | `HHAT_981` P3 | hi-hat bow quarter-open, layers 68/124 |
| 75 | `HHAT_981` P4 | hi-hat bow half-open, un layer 68 |
| 76 | `HHAT_981` P5 | hi-hat bow open, un layer 68 |

## 6. Contenu détaillé des Sounds

Dans les tableaux suivants, `toutes` signifie que le layer est activé dans
toutes les variations déclarées du Sound. Un même numéro de sample indique que
l'audio est partagé : le layer supplémentaire ne consomme pas une nouvelle
copie du WAV.

### 6.1 `KICK_981` — 605 blocs, 4 samples résidents

| Layer | P | Instrument | Vélocité | RR | Pitch | Variations | Sample |
| ---: | ---: | --- | ---: | ---: | ---: | --- | ---: |
| 1 | 1 | kick metalcore head | 84 | 1 | 0 | V1, V2 | 1 |
| 2 | 1 | kick metalcore head | 124 | 1 | 0 | V1, V2 | 2 |
| 3 | 2 | kick metalcore head | 124 | 2 | 0 | V1, V2 | 3 |
| 4 | 5 | electronic tom low | 104 | 1 | 0 | V3 | 4 |

- V1 `Metalcore` : layers 1–3.
- V2 `Sleep Token` : layers 1–3. Le manifeste recommande pitch `-0,5` et
  decay `120`, mais ces deux valeurs ne sont pas contenues dans le masque de
  variation; elles doivent être réglées sur le canal/kit si désirées.
- V3 `Electronic Tom` : layer 4 seulement.

Le RR du kick n'est pas séquencé : pour l'entendre, le bridge doit alterner la
note 0 et la note 1 sur les frappes fortes.

### 6.2 `SNRE_981` — 911 blocs, 10 samples résidents

| Layer | P | Zone | Vélocité | RR | Variations | Sample |
| ---: | ---: | --- | ---: | ---: | --- | ---: |
| 1 | 1 | center | 20 | 1 | toutes | 1 |
| 2 | 1 | center | 68 | 1 | toutes | 2 |
| 3 | 1 | center | 124 | 1 | toutes | 3 |
| 4 | 2 | center | 124 | 2 | toutes | 4 |
| 5 | 3 | center | 124 | 3 | toutes | 5 |
| 6 | 4 | mid | 20 | 1 | toutes | 6 |
| 7 | 4 | mid | 68 | 1 | toutes | 7 |
| 8 | 4 | mid | 124 | 1 | toutes | 8 |
| 9 | 5 | edge | 20 | 1 | toutes | 9 |
| 10 | 5 | edge | 124 | 1 | toutes | 10 |

- V1 `Metalcore`, V2 `Deftones-like` et V3 `Sleep Token` activent les dix
  mêmes layers.
- Le manifeste recommande pour V2 pitch `-1,25`, decay `130`; pour V3 pitch
  `-0,75`, decay `200`. Ce sont des réglages de kit recommandés, pas trois
  copies audio ni trois traitements déjà gravés dans le Sound.
- Les RR2/RR3 center sont sur les notes 9 et 10 : leur alternance doit être
  produite par l'Arduino à forte vélocité.

### 6.3 `RIM_981` — 365 blocs, 4 samples résidents

| Layer | P | Articulation | Vélocité | RR | Variations | Sample |
| ---: | ---: | --- | ---: | ---: | --- | ---: |
| 1 | 1 | rimshot | 20 | 1 | toutes | 1 |
| 2 | 1 | rimshot | 124 | 1 | toutes | 2 |
| 3 | 2 | rimshot | 124 | 2 | toutes | 3 |
| 4 | 3 | cross-stick | 124 | 1 | toutes | 4 |
| 5 | 4 | rimshot | 20 | 1 | toutes | 1 partagé |
| 6 | 4 | rimshot | 124 | 1 | toutes | 2 partagé |
| 7 | 5 | rimshot | 124 | 2 | toutes | 3 partagé |
| 8 | 6 | cross-stick | 124 | 1 | toutes | 4 partagé |

Les variations V1 `Metalcore / Metalcore`, V2 `Metalcore / Deftones-like` et
V3 `Metalcore / Sleep-like` utilisent le même audio. Les positions P4–P6 sont
des routes alternatives à coût audio nul.

### 6.4 `TOM_981` — 1 057 blocs, 6 samples résidents

| Layer | P | Résultat | Vélocité | RR | Séquence | Pitch | Sample |
| ---: | ---: | --- | ---: | ---: | --- | ---: | ---: |
| 1 | 1 | rack tom 1, source tom 2 | 68 | 1 | non | +4 | 1 |
| 2 | 1 | rack tom 1, source tom 2 | 124 | 1 | non | +4 | 2 |
| 3 | 2 | tom medium | 68 | 1 | non | 0 | 1 partagé |
| 4 | 2 | tom medium | 124 | 1 | oui | 0 | 2 partagé |
| 5 | 3 | floor tom 1, source tom 4 | 68 | 1 | non | +4 | 3 |
| 6 | 3 | floor tom 1, source tom 4 | 124 | 1 | non | +4 | 4 |
| 7 | 4 | floor tom 2 | 68 | 1 | non | 0 | 3 partagé |
| 8 | 4 | floor tom 2 | 124 | 1 | oui | 0 | 4 partagé |
| 9 | 2 | tom medium | 124 | 2 | oui | 0 | 5 |
| 10 | 4 | floor tom 2 | 124 | 2 | oui | 0 | 6 |

Les variations V1 `Metalcore`, V2 `Sleep` et V3 `Deftones` activent toutes les
couches. V2/V3 ne modifient donc pas le timbre tant qu'aucun réglage Pitch ou
Decay distinct n'est mémorisé dans le kit.

### 6.5 `PERC_981` — 353 blocs, 2 samples résidents

| Layer | P | Résultat | Vélocité | Variation | Sample |
| ---: | ---: | --- | ---: | --- | ---: |
| 1 | 7 | snare low trap / DnB | 104 | V1 | 1 |
| 2 | 8 | snare trap / Industrial | 104 | V2 | 2 |

V1 et V2 sont mutuellement exclusives. On ne peut donc pas jouer les deux
snares électroniques simultanément avec un seul canal de kit DDrum4.

### 6.6 `HHAT_981` — 733 blocs, 8 samples résidents

| Layer | P | Articulation bow | Vélocité | Sample |
| ---: | ---: | --- | ---: | ---: |
| 1–2 | 1 | closed | 68 / 124 | 1–2 |
| 3–4 | 2 | loose | 68 / 124 | 3–4 |
| 5–6 | 3 | quarter-open | 68 / 124 | 5–6 |
| 7 | 4 | half-open | 68 | 7 |
| 8 | 5 | open | 68 | 8 |

Une seule variation V1 `Bow / pedal` active les huit layers. Le bow très ouvert
n'a volontairement qu'un layer, conformément à la réduction mémoire demandée.

### 6.7 `CYMB_981` — 1 401 blocs, 10 samples résidents

| Layer | P | Articulation edge/pédale | Vélocité | Sample |
| ---: | ---: | --- | ---: | ---: |
| 1–2 | 1 | edge closed | 68 / 124 | 1–2 |
| 3–4 | 2 | edge quarter-open | 68 / 124 | 3–4 |
| 5–6 | 3 | edge half-open | 68 / 124 | 5–6 |
| 7–8 | 4 | edge open | 68 / 124 | 7–8 |
| 9 | 5 | pedal close | 104 | 9 |
| 10 | 6 | foot splash | 104 | 10 |

Une seule variation V1 `Edge / pedal` active les dix layers.

### 6.8 `CYMB_982` — 1 038 blocs, 6 samples résidents

| Layers | P | Résultat | Vélocité | Pitch | Variations | Samples |
| ---: | ---: | --- | --- | ---: | --- | --- |
| 1–2 | 1 | crash normale | 68 / 124 | 0 | V1 | 1–2 |
| 3–4 | 1 | même crash haute | 68 / 124 | +3 | V2 | 1–2 partagés |
| 5–6 | 1 | même crash basse | 68 / 124 | -3 | V3 | 1–2 partagés |
| 7–8 | 3 | splash | 68 / 124 | 0 | V1, V2, V3 | 3–4 |
| 9–10 | 4 | china | 68 / 124 | 0 | V1, V2, V3 | 5–6 |

Les crashs pitchées ne prennent pas trois fois la place : les six layers de
crash référencent seulement deux samples résidents. V1 `Crash`, V2 `Crash
High` et V3 `Crash Low` choisissent respectivement les layers à 0, +3 et -3
demi-tons. Splash et china restent disponibles dans les trois variations.

### 6.9 `CYMB_983` — 1 271 blocs, 4 samples résidents

| Layers | P | Articulation | Vélocité | Sample |
| ---: | ---: | --- | --- | --- |
| 1–2 | 3 | ride bow | 68 / 124 | 1–2 |
| 3–4 | 4 | ride bell | 68 / 124 | 3–4 |

Une seule variation V1 `Metalcore`. Le ride edge/crash-ride a été retiré.

### 6.10 `PERC_982` — 303 blocs, 2 samples résidents

| Layer | P | Articulation | Vélocité | Sample |
| ---: | ---: | --- | ---: | ---: |
| 1 | 7 | cowbell | 104 | 1 |
| 2 | 8 | woodblock | 104 | 2 |

Une seule variation V1 `Compact`. Le metallic hit a été retiré.

## 7. Configuration exacte à faire sur le DDrum4

### 7.1 Précautions et kit de test

1. Sauvegarder les réglages du module avant de remplacer un kit utilisateur.
2. Choisir un kit utilisateur `P.1` à `P.26` réellement libre. Dans la suite,
   ce kit est nommé **KIT-R15**; ne pas écraser arbitrairement un kit existant.
3. Ne supprimer aucun des dix Sounds r15 listés dans le tableau de la section 4.

### 7.2 Réglages SYSTEM globaux pour le mode standalone

| Paramètre | Valeur | Pourquoi |
| --- | --- | --- |
| MIDI channel | `C12` | canal unique de réception et d'émission DDrum4 |
| Local | `L.OF` | les pads natifs partent vers l'Arduino avant de revenir au module |
| Local pads | ne pas utiliser `L.PD` | `L.PD` désactive les pads au lieu de faire un vrai Local OFF |
| Program Change | `P.OF` pendant les tests | évite un changement de kit accidentel |
| Aftertouch | `A.ON` | conserve pression/choke quand le mapping la supporte |
| Volume MIDI | 127 ou valeur de scène connue | évite un test faussé par CC7 |

### 7.3 Affectation des Sounds et des notes

Pour chacun des dix canaux, sélectionner le canal avec le bouton correspondant,
ouvrir SOUND et choisir le Sound de la section 4. Puis, dans SYSTEM, régler son
`NOTE #` et `NOTE P = 8` selon le même tableau.

Configuration de départ recommandée pour **KIT-R15** :

| Sound | Variation | Pitch | Decay | Usage de départ |
| --- | ---: | ---: | ---: | --- |
| `KICK_981` | V1 | 0 | 100 | acoustique Metalcore |
| `SNRE_981` | V1 | 0 | 100 | snare Metalcore |
| `RIM_981` | V1 | 0 | 100 | rim/cross-stick |
| `TOM_981` | V1 | 0 | 100 | quatre toms |
| `PERC_981` | V1 | 0 | 100 | snare électronique DnB |
| `CYMB_981` | V1 | 0 | 100 | hi-hat edge/pédale |
| `PERC_982` | V1 | 0 | 100 | cowbell/woodblock |
| `CYMB_982` | V1 | 0 | 100 | crash normale + splash + china |
| `CYMB_983` | V1 | 0 | 100 | ride bow/bell |
| `HHAT_981` | V1 | 0 | 100 | hi-hat bow |

Après réglage, mémoriser explicitement le kit utilisateur avec la procédure
STORE du DDrum4 (`SHIFT` + `KIT`, puis confirmation). Les changements de
Palette sont sauvegardés différemment; pour un test reproductible, utiliser un
kit utilisateur mémorisé.

### 7.4 Variantes à tester séparément

Une Variation est un réglage de canal, pas une commande sélectionnable note par
note. Les combinaisons suivantes exigent donc un second kit utilisateur ou une
modification manuelle avant le test :

| Test | Changement |
| --- | --- |
| kick Sleep | `KICK_981` V2, puis Pitch -0,5 et Decay 120 si souhaités |
| electronic tom low | `KICK_981` V3; envoyer la note 4 |
| snare Deftones-like | `SNRE_981` V2; Pitch -1,25 et Decay 130 recommandés |
| snare Sleep Token | `SNRE_981` V3; Pitch -0,75 et Decay 200 recommandés |
| snare électronique Industrial/Trap | `PERC_981` V2; envoyer la note 39 |
| crash haute | `CYMB_982` V2; envoyer la note 56 |
| crash basse | `CYMB_982` V3; envoyer la note 56 |

Attention : la plage Decay du panneau documenté va de 0 à 100. Les valeurs
`120`, `130` et `200` sont des objectifs du modèle de construction, pas des
valeurs directement saisissables si le firmware du DDrum4 limite bien le
paramètre à 100. Dans ce cas, utiliser 100 sur le module; ne pas interpréter
`200` comme une preuve que le Sound a deux fois plus de queue.

## 8. Contrat de configuration DDTi et eDRUMin

Les notes suivantes forment le contrat d'entrée proposé pour le bridge. Elles
sont intentionnelles et déterministes, mais **elles ne sont pas encore une
lecture vérifiée des deux appareils** : aucun dump DDTi final ni export eDRUMin
final n'est présent dans le dépôt.

### 8.1 DDTi

- MIDI OUT : canal 10 pour toutes les entrées du preset standalone.
- Courbe et gain : calibrer pour produire toute la dynamique 1–127 sans hits
  fantômes; ne pas utiliser la vélocité pour choisir une articulation.
- Désactiver toute seconde note non utilisée qui pourrait doubler une frappe.
- Affecter les notes ci-dessous aux pads correspondants.

| Pad/zone DDTi | Note source proposée | Cible Arduino |
| --- | ---: | --- |
| kick | 36 | note DDrum4 0/1 selon RR et vélocité |
| snare secondaire head | 38 | note 38 en V1 ou 39 en V2 de `PERC_981` |
| tom 1 | 48 | note 24 |
| tom 2 | 45 | note 25 |
| tom 3 | 43 | note 26 |
| tom 4 / pad auxiliaire | 41 | note 27 |
| splash | 56 | note 58 |
| china | 60 | note 59 |
| cowbell | 54 | note 54 |
| woodblock | 55 | note 55 |

Le logiciel du dépôt ne doit écrire le DDTi qu'après capture d'un dump depuis
le panneau, comparaison du diff et confirmation. À défaut, appliquer ces notes
manuellement depuis le module.

### 8.2 eDRUMin

- DIN MIDI OUT : canal 11.
- Les notes de zone ci-dessous sont les valeurs d'entrée attendues par le futur
  mapping Arduino.
- Conserver CC4 sur le canal 11, polarité `0 = fermé`, `127 = ouvert`, seulement
  après vérification dans le moniteur MIDI; inverser la plage si l'appareil
  observé émet l'inverse.

| Zone eDRUMin | Note source proposée | Cible Arduino initiale |
| --- | ---: | --- |
| snare head | 38 | notes 8/9/10, RR à forte vélocité |
| snare rim | 40 | note 16/17; cross-stick séparé vers 18 si la zone le permet |
| ride bow | 51 | note 66 |
| ride bell | 53 | note 67 |
| ride edge | 59 | repli vers 66; aucun sample ride edge dans r15 |
| crash bow | 49 | note 56 |
| crash edge | 57 | repli vers 56; aucun sample crash edge distinct |
| hi-hat bow | 42 | notes 72–76 selon CC4 |
| hi-hat edge | 46 | notes 40–43 selon CC4 |
| hi-hat chick | 44 | note 44 |
| hi-hat foot splash | 21 | note 45 |

Le contrat global récent reçoit la position Snare1 sur CC16 et la transmet à
SD3. Le firmware DDrum4 de cette archive ne choisit pas encore center/mid/edge :
la conversion vers 8/11/12 dépend toujours de seuils physiques à mesurer.

## 9. Contrat du bridge Arduino

### 9.1 Mode et sortie

- Sortie Arduino : canal 12.
- Mode runtime : `NESTED`.
- Commande de mode réservée : canal 16, CC119, valeur 0–41 pour `NESTED`.
- Les Note On conservent la vélocité d'entrée.
- En cible DDrum4 standalone, les Note Off sont supprimées car les Sounds sont
  one-shot et l'implémentation MIDI du module ne les exploite pas comme un
  sampler général.

### 9.2 Règles dynamiques à compiler

| Entrée logique | Règle |
| --- | --- |
| kick acoustique | vélocité < 100 → note 0; vélocité ≥ 100 → alterner 0/1 |
| snare center | vélocité < 100 → note 8; vélocité ≥ 100 → tourner 8/9/10 |
| rimshot | vélocité < 100 → note 16; vélocité ≥ 100 → alterner 16/17 |
| tom medium | note 25; RR haute vélocité déjà séquencé dans le Sound |
| floor tom 2 | note 27; RR haute vélocité déjà séquencé dans le Sound |
| hi-hat bow | quantifier CC4 vers 72 fermé, 73 loose, 74 quarter, 75 half, 76 open |
| hi-hat edge | quantifier CC4 vers 40 fermé, 41 quarter, 42 half, 43 open |
| chick / splash | notes fixes 44 / 45 |

Le header actuellement présent dans
`firmware/ddrum4-midi-bridge/include/generated_mapping.h` ne satisfait pas ce
contrat. Il contient uniquement : C12 note 17 → 18 et C12 note 18 → 18. De plus,
`HIHAT_NOTE_P_SUPPORTED` et `HIHAT_THREE_ZONE_SUPPORTED` y valent `false`.

Conséquence : le test global complet doit être précédé par une capture des
événements réels DDTi/eDRUMin, la création d'un profil de projet sans
`MEASURE_ME_*`, la génération du mapping, les tests natifs PlatformIO, puis le
flash de l'Arduino. Ce document ne prétend pas que ces étapes sont déjà faites.

## 10. Procédure de test par étapes

### Gate A — inventaire du module

1. Vérifier que les dix IDs de la section 4 sont visibles dans la liste SOUND.
2. Vérifier `MEM.LEFT` proche de `0.08`.
3. Si un Sound manque, arrêter : ne pas compenser en changeant les `NOTE #`.

### Gate B — audition MIDI directe de la banque

Avant le merger, connecter une sortie MIDI fiable directement au DDrum4 MIDI
IN, régler C12 et envoyer les notes de la section 5. Tester au minimum les
vélocités 20, 68, 100 et 124 quand plusieurs layers existent.

Critères : attaque intacte, absence de crack, queue non coupée, changement de
layer audible, pitch V1/V2/V3 de crash audible, splash/china toujours audibles
dans les trois variations.

### Gate C — une source à la fois

1. DDTi seul → Arduino → DDrum4 : kick, quatre toms, splash, china, percussions.
2. eDRUMin seul → Arduino → DDrum4 : snare, crash, ride, hi-hat fixe.
3. DDrum4 Local OFF seul → Arduino → DDrum4 : vérifier chaque pad natif et
   exactement un son par frappe.

Enregistrer le canal, la note, la vélocité, CC4, poly-aftertouch et les chokes.
Toute divergence par rapport aux tables doit être corrigée dans le profil de
source, pas masquée au hasard dans la banque.

### Gate D — merger complet

1. Brancher les trois DIN OUT au merger puis le merger à l'Arduino.
2. Envoyer canal 16 / CC119 / valeur 0 pour sélectionner `NESTED`.
3. Jouer une source à la fois, puis des frappes simultanées entre sources.
4. Vérifier qu'il n'existe ni note doublée, ni boucle, ni perte de vélocité.
5. Tester des roulements snare/toms, kick rapide, crash + choke, ride bell,
   chick/splash et transitions de hi-hat.
6. Jouer au moins 30 minutes avant de considérer le package stable.

### Matrice d'acceptation minimale

| Fonction | Résultat attendu |
| --- | --- |
| 10 Sounds / mémoire | tous présents, `MEM.LEFT ≈ 0.08` |
| Kick | 2 layers audibles + RR forte vélocité; V3 testée séparément |
| Snare | center/mid/edge audibles; RR center sans répétition évidente |
| Toms | quatre hauteurs, deux layers, RR automatique sur tom 2 et floor 2 |
| Hi-hat | bow/edge fermé à ouvert, chick, splash; pas de saut incohérent |
| Crash | V1 0, V2 +3, V3 -3; splash et china conservées |
| Ride | bow et bell; edge replié explicitement |
| Percussions | deux e-snares alternatives, cowbell, woodblock |
| Transport | une frappe = un son, vélocité conservée, aucune boucle |

## 11. Points non couverts par r15

- Pas de ride edge distinct.
- Pas de crash edge distinct : bow et edge du pad peuvent être rabattus sur la
  même crash; le choke demande encore une route de pression validée.
- Pas de stack, clap, hi-hat électronique, glitch, metallic hit ni electronic
  rim.
- Une seule splash et une seule china résidentes.
- Le kick électronique est l'ancien electronic tom low, disponible seulement
  en V3 de `KICK_981`.
- Les variations nommées Sleep/Deftones des fûts ne changent pas toutes l'audio
  à elles seules; plusieurs sont des presets de réglage à mémoriser dans des
  kits utilisateurs distincts.
- Le moteur hi-hat continu est compilé mais reste non flashable avant mesure.
  Le positional sensing CC16 est opérationnel vers SD3 seulement ; sa
  quantification DDrum4/DrumGizmo reste volontairement désactivée.

## 12. Références

- DDrum4 SE, manuel utilisateur :
  <https://images.thomann.de/pics/atg/atgdata/document/manual/123249_manual.pdf>
- Architecture Local OFF : `docs/ddrum4-local-off-central-routing.md`
- Modes et câblage permanent : `docs/midi-operating-modes.md`
- Shield MIDI Arduino : `docs/hardware/arduino-midi-breakout-shield.md`
- Protocole de test du dépôt : `docs/COMPLETE_TEST_PROTOCOL.md`
- État du DDTi : `docs/DEVICE_IDENTIFICATION.md`
