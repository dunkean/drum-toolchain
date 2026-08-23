Oui. Le bon modèle n’est pas un « control center » avec quinze modules indépendants. C’est avant tout un **éditeur/compiler de kits**, organisé autour d’un espace canonique de **128 notes MIDI**.

Toute l’application repose sur cette chaîne :

```text
Pad physique + zone/expression
            ↓
Événement d’entrée stable
            ↓
Program / Palette active
            ↓
Note logique 0–127 + expressions
            ↓
SD3 / DDrum4 / Arduino / Software Converter
```

Le logiciel n’a donc besoin que de **cinq écrans principaux** :

```text
128 NOTES | PADS & INPUTS | PROGRAMS & PALETTES | DDRUM4 | SYNC & DUMPS
```

Pas de gros dashboard, pas de graphe de routing généraliste, pas d’éditeur SD3 séparé : le mapping SD3 est directement intégré aux 128 notes.

---

# 1. Les objets de base

## `Note Kit`

Un `Note Kit` est exactement une liste de **128 emplacements**, de la note 0 à la note 127.

Chaque note représente un son ou une articulation logique :

| Champ          | Exemple                         |
| -------------- | ------------------------------- |
| Note           | 38                              |
| Nom            | Snare Metalcore Center          |
| Famille        | Snare                           |
| Articulation   | Center                          |
| Source SD3     | Modern Metal / Snare A / Center |
| Expressions    | Velocity, Position              |
| Capture DDrum4 | 8 layers automatiques           |
| Tags           | Metalcore, Tight, Main          |
| Utilisation    | P01 Palette 1, DDrum4 Sound 02  |

Un projet peut contenir plusieurs `Note Kits` :

```text
Modern Hybrid 128
Electronic DnB 128
Acoustic / Deftones 128
Experimental / FX 128
```

Un `Note Kit` peut être créé de trois manières :

* import du kit actuellement chargé dans SD3 ;
* chargement d’un preset ou d’instruments SD3 définis dans une recette ;
* construction manuelle, note par note.

L’idée importante est que **la note n’est pas simplement un numéro MIDI**. C’est un emplacement logique contenant :

```text
numéro + nom + rôle + articulation + source SD3 + expressions attendues
```

Le canal MIDI n’est pas défini ici. Il est choisi plus tard par le compiler selon la destination.

---

## `Rig`

Le `Rig` décrit le hardware physique, indépendamment des kits :

```text
DDrum4
DDTi
eDRUMin
Arduino MIDI Converter
Software Converter
Pads et cymbales
```

Il contient les connexions réelles :

```text
Snare Main
  Device : eDRUMin
  Input : 3
  Type : Dual-zone piezo/switch
  Expressions :
    - Head
    - Rim
    - Rimshot
    - Positional sensing
    - Velocity
```

```text
Ride
  Device : DDTi
  Inputs : 8 + 9
  Type : Three-zone ride
  Expressions :
    - Bow
    - Edge
    - Bell
    - Choke
```

```text
Hi-Hat
  Device : eDRUMin
  Inputs : 1 + Pedal
  Expressions :
    - Tip
    - Edge
    - Openness
    - Pedal
    - Foot splash
```

Le `Rig` ne connaît pas encore les sons Metalcore, Deftones ou DnB. Il connaît uniquement les **événements physiques disponibles**.

---

## `Program`

Un `Program` est une configuration complète utilisable en jeu.

Il sélectionne :

```text
- un Note Kit de 128 notes ;
- un mapping de base Pads → Notes ;
- un profil SD3 ;
- un Program/Kit DDrum4 ;
- un profil Arduino ;
- un profil Software Converter ;
- une Palette active par défaut.
```

Exemple :

```text
Program P01 — Modern Hybrid
  Note Kit : Modern Hybrid 128
  SD3 Profile : Modern Metal Custom
  DDrum4 Program : P01
  Default Palette : Metalcore
```

```text
Program P02 — Electronic DnB
  Note Kit : Electronic DnB 128
  SD3 Profile : Electronic DnB
  DDrum4 Program : P02
  Default Palette : Main
```

---

## `Palette`

Une `Palette` est une variante d’un `Program`.

Elle ne recopie pas nécessairement tout le mapping. Elle contient seulement les différences par rapport au mapping de base.

Une Palette peut modifier :

* une seule caisse claire ;
* toutes les cymbales ;
* les kicks et snares ;
* l’ensemble du kit ;
* le DDrum4 Program associé ;
* le profil SD3 associé ;
* les tables Arduino et Software Converter.

Exemple :

```text
Program P01 — Modern Hybrid

Palette 1 — Metalcore
  Snare Head → Note 38 — Snare Metalcore Center
  Snare Rim  → Note 40 — Snare Metalcore Rim
  Snare Shot → Note 41 — Snare Metalcore Rimshot

Palette 2 — Deftones
  Snare Head → Note 50 — Snare Deftones Center
  Snare Rim  → Note 51 — Snare Deftones Rim
  Snare Shot → Note 52 — Snare Deftones Rimshot
```

Toutes les autres zones héritent du Program P01.

Une Palette entièrement électronique peut remplacer toutes les lignes. Techniquement, cela reste le même système : une liste d’overrides plus longue.

---

## `DDrum4 Build`

Un `DDrum4 Build` représente la matrice :

```text
10 Sounds × 8 Layers
```

Il est associé à un Program ou à une Palette.

Chaque cellule de la matrice pointe vers une note du `Note Kit`, avec une vélocité de capture.

```text
                   L1   L2   L3   L4   L5   L6   L7   L8
Sound 01 Kick      N36  N36  N36  N36  N36  N36  N36  N36
Sound 02 Snare     N38  N38  N38  N38  N38  N38  N38  N38
Sound 03 Rim       N40  N40  N40  N40  N40  N40  N40  N40
Sound 04 Tom 1     N43  N43  N43  N43  N43  N43  N43  N43
...
```

Dans cet exemple, les huit cellules utilisent la même articulation SD3, mais avec huit vélocités de capture différentes.

Une cellule peut aussi utiliser une note différente :

```text
Sound 02 Snare

L1 : N38 Snare Center, velocity 18
L2 : N38 Snare Center, velocity 32
L3 : N38 Snare Center, velocity 48
L4 : N38 Snare Center, velocity 64
L5 : N38 Snare Center, velocity 82
L6 : N38 Snare Center, velocity 100
L7 : N41 Snare Rimshot, velocity 112
L8 : N60 Snare Electronic Layer, velocity 127
```

Cela permet de construire des sons hybrides ou complètement non linéaires.

---

# 2. Structure générale de l’application

```text
┌───────────────────────────────────────────────────────────────────────────┐
│ Project: Hybrid Drum        Program: P01        Palette: 2 — Deftones    │
│ Mode: Hybrid     DDrum4 ●  DDTi ●  eDRUMin ●  Arduino ●  SD3 ●  [SYNC]   │
├────────────────────┬──────────────────────────────────────┬───────────────┤
│ PROJECT TREE       │ EDITOR                               │ INSPECTOR     │
│                    │                                      │               │
│ Note Kits          │  128 NOTES                           │ Élément       │
│  Modern Hybrid     │  PADS & INPUTS                       │ sélectionné   │
│  Electronic DnB    │  PROGRAMS & PALETTES                 │               │
│                    │  DDRUM4                              │ Propriétés    │
│ Programs           │  SYNC & DUMPS                        │ contextuelles │
│  P01 Modern        │                                      │               │
│  P02 DnB           │                                      │               │
│                    │                                      │               │
│ DDrum4 Builds      │                                      │               │
│ Hardware           │                                      │               │
│ Dumps              │                                      │               │
├────────────────────┴──────────────────────────────────────┴───────────────┤
│ 3 modifications non compilées | DDrum4: 6.7 MB / 8 MB | 1 warning       │
└───────────────────────────────────────────────────────────────────────────┘
```

La barre supérieure sert aussi de contrôleur live :

```text
Program P01 | Palette 1 | Palette 2 | Palette 3
```

Le changement peut venir :

* d’un clic dans l’application ;
* d’un MIDI Program Change ;
* d’un bouton Arduino ;
* d’un pad réservé ;
* d’un footswitch.

---

# 3. Écran `128 NOTES`

C’est l’écran principal de définition des sons.

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Note Kit: Modern Hybrid 128                                              │
│ [Import current SD3 kit] [Load SD3 recipe] [Duplicate] [Apply to SD3]   │
├──────┬──────────────────────┬──────────┬────────────┬─────────────────────┤
│ Note │ Name                 │ Family   │ Artic.     │ SD3 Source          │
├──────┼──────────────────────┼──────────┼────────────┼─────────────────────┤
│ 36   │ Kick Main            │ Kick     │ Center     │ Modern Metal / Kick │
│ 37   │ Kick Electronic      │ Kick     │ Center     │ Custom / Electro    │
│ 38   │ Snare MC Center      │ Snare    │ Center     │ Modern Metal / A    │
│ 39   │ Snare MC Edge        │ Snare    │ Edge       │ Modern Metal / A    │
│ 40   │ Snare MC Rim         │ Snare    │ Rim        │ Modern Metal / A    │
│ 41   │ Snare MC Rimshot     │ Snare    │ Rimshot    │ Modern Metal / A    │
│ 50   │ Snare Deftones       │ Snare    │ Center     │ Custom Kit / B      │
│ ...  │                      │          │            │                     │
├──────┴──────────────────────┴──────────┴────────────┴─────────────────────┤
│ Expressions | Used by | DDrum4 capture status | Preview                  │
└──────────────────────────────────────────────────────────────────────────┘
```

Les actions principales sont :

* glisser une articulation SD3 sur une note ;
* importer automatiquement le mapping du kit chargé ;
* écouter la note ;
* envoyer une vélocité de test ;
* filtrer par famille ;
* voir dans quels Programs, Palettes ou DDrum4 Builds la note est utilisée ;
* déplacer ou dupliquer une note en mettant à jour les références.

L’inspecteur de droite montre :

```text
Name
Family
Articulation
SD3 instrument
SD3 articulation
Default preview velocity
Expression profile
DDrum4 capture defaults
Tags
```

## Expressions attachées aux notes

Les expressions continues ne prennent pas d’emplacement supplémentaire dans les 128 notes. Elles sont décrites comme des capacités de la note.

Exemple :

```text
N38 Snare Center
  accepts:
    Velocity
    Position

N42 Hi-Hat Bow
  accepts:
    Velocity
    Openness

N49 Crash Bow
  accepts:
    Velocity
    Choke
```

La colonne `Expressions` affiche simplement des badges :

```text
VEL | POS
VEL | HH
VEL | CHOKE
```

---

# 4. Écran `PADS & INPUTS`

Cet écran décrit les 18–20 pads et leurs connexions physiques.

Ce n’est pas un dessin réaliste de batterie. C’est une liste structurée et facilement éditable.

```text
┌───────────────────────────────────────────────────────────────────────────┐
│ [Learn input] [Add pad] [Import module configuration] [Open eDRUMin]     │
├──────────────────┬───────────┬─────────┬─────────────────────┬─────────────┤
│ Pad              │ Device    │ Input   │ Template            │ Status      │
├──────────────────┼───────────┼─────────┼─────────────────────┼─────────────┤
│ Snare Main       │ eDRUMin   │ 3       │ Snare dual-zone     │ Connected   │
│ Snare Alt        │ DDrum4    │ Snare 2 │ Snare positional    │ Connected   │
│ Kick             │ DDrum4    │ Kick    │ Kick mono           │ Connected   │
│ Hi-Hat           │ eDRUMin   │ 1+Pedal │ VH-style continuous │ Connected   │
│ Ride             │ DDTi      │ 8+9     │ Ride three-zone     │ Connected   │
│ Crash 1          │ eDRUMin   │ 4       │ Crash + choke       │ Connected   │
│ ...              │           │         │                     │             │
└──────────────────┴───────────┴─────────┴─────────────────────┴─────────────┘
```

Une ligne dépliée montre les événements du pad :

```text
Snare Main
  Head           Trigger
  Rim            Trigger
  Rimshot        Composite trigger
  Position       Continuous expression
  Velocity       Continuous expression
```

Chaque événement reçoit un identifiant interne stable :

```text
SNARE_MAIN.HEAD
SNARE_MAIN.RIM
SNARE_MAIN.RIMSHOT
SNARE_MAIN.POSITION
```

Ces identifiants restent fixes, même quand le Program ou la Palette change.

## Configuration du module

L’inspecteur contient les paramètres propres au module :

```text
Device input
Pad type
Piezo / switch configuration
Threshold
Gain
Scan time
Mask time
Velocity curve
Positional sensing
Choke mode
Output channel
Raw note
```

Les paramètres avancés qui restent mieux gérés dans l’application native ne nécessitent pas de recréer toute l’interface.

Pour eDRUMin :

```text
[Open eDRUMin]
[Read current mapping]
[Export expected notes]
[Mark configuration as synchronized]
```

L’application conserve néanmoins la configuration attendue dans le projet.

---

# 5. Écran `PROGRAMS & PALETTES`

C’est le cœur du fonctionnement live.

La partie centrale est une matrice :

```text
Program P01 — Modern Hybrid
Note Kit: Modern Hybrid 128
```

| Pad / Expression     | Base                 | Palette 1 Metalcore | Palette 2 Deftones     | Palette 3 Electro |
| -------------------- | -------------------- | ------------------- | ---------------------- | ----------------- |
| Kick / Hit           | N36 Kick Main        | inherit             | inherit                | N37 Kick Electro  |
| Snare Main / Head    | N38 Snare MC Center  | inherit             | N50 Snare Deftones     | N70 DnB Snare     |
| Snare Main / Rim     | N40 Snare MC Rim     | inherit             | N51 Snare Deftones Rim | N71 DnB Rim       |
| Snare Main / Rimshot | N41 Snare MC Rimshot | inherit             | N52 Deftones Shot      | N72 DnB Clap      |
| Tom 1 / Head         | N43 Tom 1            | inherit             | inherit                | N73 Electro Tom   |
| Ride / Bell          | N53 Ride Bell        | inherit             | inherit                | N80 Bell FX       |
| Hi-Hat / Bow         | N42 HH Bow           | inherit             | inherit                | N81 DnB HH        |
| Hi-Hat / Openness    | HH Openness          | inherit             | inherit                | DnB HH Openness   |

Les cellules sont remplies par drag-and-drop depuis la liste des 128 notes.

Une cellule non définie affiche `inherit`. La Palette ne stocke que les changements.

En cliquant sur une Palette, le panneau de droite affiche ses liaisons :

```text
Palette 2 — Deftones

Virtual index             Palette 2
MIDI Program Change       PC 2
Arduino profile           P01-PAL02
Software Converter map    P01-PAL02
DDrum4 selection          P01 / Palette 2
SD3 profile               Modern Hybrid / Deftones variant
Switch behavior           Immediate
```

## Full Program contre Palette

Un `Program` sert à changer complètement de contexte :

```text
P01 Modern Hybrid
P02 Electronic DnB
P03 Acoustic
```

Une `Palette` sert à faire une variation dans un Program :

```text
P01 / Palette 1 Metalcore
P01 / Palette 2 Deftones
P01 / Palette 3 Industrial
```

Mais techniquement une Palette peut remplacer tout le mapping. Le logiciel ne l’interdit pas.

---

# 6. Écran `DDRUM4`

Cet écran est centré sur la matrice demandée : **10 Sounds × 8 Layers**.

```text
DDrum4 Build: P01 / Palette 1 — Metalcore
Source: Modern Hybrid 128
```

```text
┌─────────────┬────┬────┬────┬────┬────┬────┬────┬────┐
│ DDrum4      │ L1 │ L2 │ L3 │ L4 │ L5 │ L6 │ L7 │ L8 │
├─────────────┼────┼────┼────┼────┼────┼────┼────┼────┤
│ Sound 01    │    │    │    │    │    │    │    │    │
│ Kick        │N36 │N36 │N36 │N36 │N36 │N36 │N36 │N36 │
├─────────────┼────┼────┼────┼────┼────┼────┼────┼────┤
│ Sound 02    │    │    │    │    │    │    │    │    │
│ Snare       │N38 │N38 │N38 │N38 │N38 │N38 │N38 │N38 │
├─────────────┼────┼────┼────┼────┼────┼────┼────┼────┤
│ Sound 03    │N40 │N40 │N40 │N40 │N40 │N40 │N40 │N40 │
│ ...         │    │    │    │    │    │    │    │    │
└─────────────┴────┴────┴────┴────┴────┴────┴────┴────┘
```

À gauche se trouve la liste filtrable des 128 notes.

Deux types de drag-and-drop :

### Drop sur une ligne

Déposer `N38 Snare Metalcore Center` sur le titre `Sound 02` :

* remplit automatiquement les huit layers ;
* calcule huit vélocités ;
* prépare huit captures SD3.

### Drop sur une cellule

Déposer une note directement sur `L7` :

* remplace uniquement cette layer ;
* permet de créer des sons hybrides ou des accents.

Chaque cellule contient :

```text
Source note
Capture velocity
Audio output
Tail duration
Trim
Gain
Pitch
Normalize
Fade
Rendered status
```

L’inspecteur permet de choisir les vélocités :

```text
Auto:
18, 32, 48, 64, 82, 100, 116, 127
```

ou de les saisir manuellement.

## Barre de construction

```text
[Preview]
[Capture selected]
[Capture all]
[Process]
[Build DDrum4 bank]
[Upload]
```

Un indicateur reste toujours visible :

```text
Estimated memory: 6.4 MB / 8 MB
Rendered layers: 63 / 80
Missing layers: 4
```

## Variantes DDrum4

Lorsqu’une Palette modifie seulement la caisse claire, son DDrum4 Build peut hériter de celui du Program :

```text
P01 Base
  Sound 01 Kick
  Sound 02 Metalcore Snare
  Sound 03 Rim
  ...

P01 Palette 2 Deftones
  inherit Sound 01
  override Sound 02 → Deftones Snare
  override Sound 03 → Deftones Rim
  inherit Sound 04–10
```

Le compiler développe ensuite cette version héritée en un fichier DDrum4 complet.

---

# 7. Écran `SYNC & DUMPS`

Cet écran ne sert qu’à compiler, comparer et déployer.

```text
┌────────────────────┬──────────────┬──────────────┬───────────────────────┐
│ Target             │ Project      │ Device       │ Action                │
├────────────────────┼──────────────┼──────────────┼───────────────────────┤
│ DDTi notes         │ Modified     │ Older config │ [Diff] [Push] [Dump]  │
│ eDRUMin notes      │ In sync      │ In sync      │ [Open eDRUMin]        │
│ DDrum4 trigger map │ Modified     │ Older config │ [Diff] [Push] [Dump]  │
│ DDrum4 sound bank  │ Build ready  │ P01 loaded   │ [Upload]              │
│ Arduino tables     │ Modified     │ Older build  │ [Flash] [Export]      │
│ Software Converter │ Modified     │ Running old  │ [Apply] [Restart]     │
│ SD3 mapping        │ Modified     │ Unknown       │ [Apply] [Export]      │
└────────────────────┴──────────────┴──────────────┴───────────────────────┘
```

Actions globales :

```text
[Compile all]
[Backup devices]
[Apply complete setup]
[Dump complete setup]
[Restore previous setup]
```

Avant toute écriture :

1. lecture ou dump de l’état actuel ;
2. sauvegarde automatique ;
3. affichage du diff ;
4. écriture ;
5. vérification ;
6. stockage du checksum dans le projet.

---

# 8. Deux modes de compilation des notes

Le logiciel doit supporter deux stratégies.

## Mode recommandé : notes physiques stables

Chaque expression physique reçoit une note ou un événement brut unique et stable.

```text
SNARE_MAIN.HEAD → Raw 10
SNARE_MAIN.RIM  → Raw 11
RIDE.BELL       → Raw 20
```

DDTi, eDRUMin et DDrum4 ne changent pas à chaque Palette.

Arduino ou le Software Converter transforme ensuite :

```text
Raw 10 + Palette Metalcore → N38
Raw 10 + Palette Deftones  → N50
Raw 10 + Program DnB       → N70
```

Avantages :

* changement instantané ;
* pas besoin de réécrire les modules en live ;
* aucune interruption ;
* un seul mapping physique à maintenir ;
* Arduino et Software Converter utilisent exactement la même table compilée.

## Mode direct / standalone

Pour un setup sans converter ou sans ordinateur, l’application peut « aplatir » un Program ou une Palette :

```text
P01 Palette 2
    ↓
Configuration directe DDTi
Configuration directe eDRUMin
Configuration directe DDrum4
```

Les modules envoient alors directement les notes finales.

Ce mode est utile comme export autonome, mais il ne doit pas être le fonctionnement principal des changements live.

---

# 9. Gestion des expressions

Le mapping ne doit pas se limiter à `note in → note out`.

Une route contient :

```text
Trigger note
Velocity curve
Input channel
Output channel
Position mapping
Hi-hat openness mapping
Choke conversion
Rimshot reconstruction
Note-off behavior
```

Exemple de route de caisse claire :

```text
Input:
  SNARE_MAIN.HEAD
  SNARE_MAIN.RIM
  SNARE_MAIN.POSITION

Program mapping:
  Head → N38
  Rim → N40
  Head + Rim → N41

Expressions:
  Velocity → passthrough
  Position → SD3 positional input
```

Exemple de hi-hat :

```text
Input:
  HH.TIP
  HH.EDGE
  HH.PEDAL
  HH.OPENNESS

Mapping:
  TIP → N42
  EDGE → N44
  PEDAL → N46

Expression:
  OPENNESS → SD3 hi-hat controller
```

Pour une destination qui ne supporte pas une expression continue, le compiler applique une conversion définie :

```text
Continuous openness
  0–20   → Closed
  21–50  → Tight
  51–85  → Half-open
  86–127 → Open
```

---

# 10. Changement live de Program ou Palette

Le Program et la Palette forment l’état global actif :

```text
Active State
  Program = P01
  Palette = 2
  Mode = Hybrid
```

Un changement de Palette doit déclencher atomiquement :

```text
1. changement de table Arduino ;
2. changement de table Software Converter ;
3. sélection DDrum4 correspondante ;
4. sélection du profil SD3 si nécessaire ;
5. mise à jour de l’interface ;
6. confirmation que tous les targets sont synchronisés.
```

Les tables doivent être précompilées. Le changement live ne reconstruit aucun mapping.

Exemple :

```text
Bouton Arduino 1
  → Program P01 / Palette 1 Metalcore

Bouton Arduino 2
  → Program P01 / Palette 2 Deftones

Bouton Arduino 3
  → Program P02 / Palette 1 DnB
```

---

# 11. Arborescence du projet

```text
Hybrid Drum Project
│
├── Rig
│   ├── Devices
│   ├── Pads
│   └── Raw Events
│
├── Note Kits
│   ├── Modern Hybrid 128
│   ├── Electronic DnB 128
│   └── Acoustic 128
│
├── Programs
│   ├── P01 Modern Hybrid
│   │   ├── Palette 1 Metalcore
│   │   ├── Palette 2 Deftones
│   │   └── Palette 3 Industrial
│   │
│   └── P02 Electronic DnB
│       ├── Palette 1 Main
│       └── Palette 2 Aggressive
│
├── DDrum4 Builds
│   ├── P01-PAL01
│   ├── P01-PAL02
│   └── P02-PAL01
│
├── Generated
│   ├── DDTi configs
│   ├── eDRUMin configs
│   ├── DDrum4 banks
│   ├── Arduino tables
│   ├── Software Converter tables
│   └── SD3 mappings
│
└── Dumps & Backups
```

---

# 12. Exemple complet

## Note Kit `Modern Hybrid 128`

```text
N36 Kick Metalcore
N37 Kick Electronic
N38 Snare Metalcore Center
N40 Snare Metalcore Rim
N41 Snare Metalcore Rimshot
N50 Snare Deftones Center
N51 Snare Deftones Rim
N52 Snare Deftones Rimshot
N70 Snare DnB
N71 DnB Rim
N72 DnB Clap
...
```

## Rig

```text
SNARE_MAIN.HEAD
SNARE_MAIN.RIM
SNARE_MAIN.RIMSHOT
```

## Program P01 / Palette 1

```text
HEAD    → N38
RIM     → N40
RIMSHOT → N41

DDrum4 → P01 Metalcore
SD3 → Modern Metal profile
```

## Program P01 / Palette 2

```text
HEAD    → N50
RIM     → N51
RIMSHOT → N52

DDrum4 → P02 Deftones
SD3 → Deftones profile
```

## Program P02 / Palette 1

```text
HEAD    → N70
RIM     → N71
RIMSHOT → N72

DDrum4 → P03 Electronic DnB
SD3 → Electronic DnB profile
```

La même sélection `P02 / Palette 1` commande donc simultanément :

```text
DDrum4 Program
Arduino mapping
Software Converter mapping
SD3 configuration
```

---

# 13. Ce que l’application ne doit pas devenir

Pour garder le produit simple :

* pas de dashboard séparé ;
* pas de graphe géant montrant tous les câbles ;
* pas de mapping différent édité manuellement pour chaque module ;
* pas d’éditeur SD3 complet ;
* pas de clone complet de l’application eDRUMin ;
* pas de page « Instruments », « Layers », « Routing » et « Diagnostics » séparée ;
* pas de duplication des 128 notes entre SD3, Arduino et DDrum4.

Les diagnostics sont intégrés directement dans les écrans :

```text
Note inutilisée
Pad non mappé
Expression incompatible
Conflit de note
Capture manquante
Mémoire DDrum4 dépassée
Target non synchronisé
```

---

# 14. Résumé de l’interface finale

```text
128 NOTES
Définir les sons et articulations SD3 disponibles.

PADS & INPUTS
Décrire le hardware, les zones et les expressions physiques.

PROGRAMS & PALETTES
Décider quelle note chaque pad déclenche selon le contexte.

DDRUM4
Transformer les notes sélectionnées en matrice 10 × 8 layers,
capturer SD3, construire les banques et Programs.

SYNC & DUMPS
Compiler, comparer, sauvegarder et envoyer toutes les configurations.
```

La logique centrale tient donc en une phrase :

> **Les pads produisent des événements stables ; les Programs et Palettes les convertissent vers un Kit de 128 notes ; SD3 et DDrum4 sont deux rendus différents de ces mêmes notes.**

La future image devra représenter essentiellement les cinq écrans, avec comme vue principale la matrice `Programs & Palettes`, et non un dashboard généraliste.
