Tu travailles sur un **ddrum DDTi ancienne génération**, connecté physiquement en **USB** au PC sur lequel tu as accès au terminal et au système.

Le numéro de série de l'appareil est :

`2016040855`

Il s'agit donc vraisemblablement d'un modèle **2016**, ancienne génération de DDTi. **Ne tente aucune mise à jour de firmware**, en particulier aucun firmware destiné aux modèles 2021+.

# Objectif

Je veux que tu :

1. reverse-engineer le protocole de communication du DDTi 2016 ;
2. identifies précisément ce qui est contrôlable par USB/MIDI/SysEx ;
3. documentes le format des dumps et messages SysEx ;
4. développes une library permettant de lire, modifier, sauvegarder et restaurer la configuration ;
5. exposes cette library via une API propre ;
6. développes une interface graphique permettant de configurer le DDTi depuis le PC ;
7. produises une documentation suffisante pour que le protocole puisse ensuite être utilisé par d'autres logiciels ou par un microcontrôleur.

Le projet doit être conçu comme un vrai outil maintenable, pas comme un script jetable.

---

# Contexte matériel

Le DDTi possède 10 trigger inputs.

Les inputs peuvent avoir différentes zones, notamment Tip/Ring sur les entrées TRS.

Les paramètres connus du DDTi comprennent notamment :

## Paramètres dépendants du kit

* MIDI Note
* MIDI Channel
* Program Change / kit-related MIDI settings
* Hi-hat notes éventuelles :

  * open
  * closed
  * pedal
  * autres états selon ce que supporte réellement cette génération

## Paramètres de trigger

Selon ce qui est réellement exposé par le firmware :

* Gain
* Velocity Curve
* Threshold
* X-Talk
* Retrigger
* Trigger Type
* paramètres liés aux dual-zone pads
* paramètres liés au hi-hat
* paramètres globaux

Ne pars pas du principe que cette liste est exhaustive.

Découvre ce que contient réellement l'appareil.

---

# Contraintes de sécurité

L'appareil est ancien et fonctionne actuellement.

La priorité absolue est de **ne pas le bricker**.

Avant toute écriture :

1. détecter le device ;
2. lire ses USB descriptors ;
3. détecter ses MIDI ports ;
4. capturer et sauvegarder tout ce qui peut être lu ;
5. réaliser plusieurs copies du dump factory/current ;
6. calculer SHA-256 des dumps ;
7. conserver un dump "golden" qui ne devra jamais être modifié.

Ne jamais envoyer de SysEx inconnu ou aléatoire à l'appareil.

Commencer par du **read-only**.

Lorsque des tests d'écriture deviennent nécessaires, utiliser uniquement des modifications connues, minimales et réversibles.

Ne jamais :

* tenter de flasher le firmware ;
* accéder à un bootloader ;
* envoyer des commandes firmware update ;
* envoyer des blocs SysEx aléatoires ;
* faire du fuzzing agressif sur le hardware.

---

# Phase 1 — Identification USB/MIDI

Inspecte le DDTi connecté.

Utilise si nécessaire :

* Windows Device Manager / PowerShell
* `mido`
* `python-rtmidi`
* `pyusb`
* `libusb`
* les APIs MIDI disponibles sous Windows
* toute commande système pertinente

Identifie :

* VID
* PID
* manufacturer
* product name
* serial si exposé
* USB interfaces
* endpoints
* MIDI IN
* MIDI OUT
* éventuelles interfaces supplémentaires
* descriptors

Crée :

`docs/DEVICE_IDENTIFICATION.md`

avec tous les résultats.

---

# Phase 2 — MIDI monitoring

Crée rapidement un utilitaire permettant d'afficher en temps réel tout ce que le DDTi transmet.

Exemple attendu :

```text
timestamp
port
message type
channel
note
velocity
CC
program change
SysEx raw hex
```

Supporter au minimum :

```bash
ddti monitor
```

et éventuellement :

```bash
python -m ddti monitor
```

Enregistrer également les captures dans des fichiers.

---

# Phase 3 — SysEx dump

Cherche à provoquer proprement le dump SysEx documenté du DDTi.

Le DDTi ancienne génération permet normalement de transmettre ses presets/configurations par SysEx.

Si une intervention physique sur le panneau du DDTi est nécessaire, indique-moi exactement :

* quelle combinaison de boutons utiliser ;
* quand la faire ;
* ce que ton programme attend.

Ton programme doit capturer le flux intégral sans perte.

Produis :

```text
captures/
    factory_dump_001.syx
    factory_dump_001.hex
    factory_dump_001.json
```

Le `.syx` doit contenir les bytes bruts.

Le `.hex` doit fournir une représentation lisible.

Le `.json` peut contenir les métadonnées de capture.

---

# Phase 4 — Differential reverse engineering

Une fois le dump obtenu, reverse-engineer son format par comparaison contrôlée.

Procédure générale :

1. dump A ;
2. modifier exactement UN paramètre depuis le panneau du DDTi ;
3. dump B ;
4. binary diff ;
5. identifier les bytes modifiés ;
6. restaurer la valeur initiale ;
7. répéter.

Commencer avec des paramètres particulièrement faciles à interpréter.

Exemples :

```text
Input 1 Tip MIDI Note : 35 -> 36
Input 1 MIDI Channel : 10 -> 11
Input 2 Ring Note : X -> X+1
Gain : N -> N+1
Threshold : N -> N+1
X-Talk : N -> N+1
Retrigger : N -> N+1
Velocity Curve : curve A -> curve B
Trigger Type : type A -> type B
```

Faire ensuite les mêmes changements :

* sur un autre input ;
* sur un autre kit ;

afin de déterminer :

* taille d'une structure Input ;
* taille d'une structure Kit ;
* ordre des champs ;
* paramètres globaux vs paramètres par kit.

Automatise au maximum l'analyse différentielle.

Créer par exemple :

```bash
ddti diff dump_a.syx dump_b.syx
```

avec une sortie du genre :

```text
Offset 0x012A:
    A = 0x23
    B = 0x24
    delta = +1

Possible interpretation:
    Kit 0 / Input 1 / Tip MIDI Note
```

---

# Phase 5 — Reverse engineering du framing SysEx

Documente précisément :

* SysEx start/end ;
* manufacturer ID ;
* device/model ID éventuel ;
* command byte ;
* address ;
* payload ;
* longueur ;
* checksum éventuel ;
* encodage 7-bit éventuel ;
* escaping éventuel ;
* segmentation des dumps ;
* ordre des messages ;
* temporisation nécessaire entre messages.

N'assume rien : valide chaque hypothèse expérimentalement.

Crée :

`docs/SYSEX_PROTOCOL.md`

Je veux une spécification suffisamment claire pour implémenter le protocole dans un autre langage sans lire ton code.

Exemple de niveau de détail attendu :

```text
F0
xx xx xx        Manufacturer
xx              Device/model
xx              Command
aa aa           Address
dd ... dd       Payload
cc              Checksum
F7
```

avec la vraie structure une fois découverte.

---

# Phase 6 — Data model

Construis un modèle Python propre représentant le DDTi.

Par exemple :

```python
DDTiDevice
DDTiConfiguration
DDTiKit
DDTiInput
DDTiZone
DDTiTriggerSettings
DDTiHiHatSettings
```

N'impose pas cette architecture si les données découvertes suggèrent mieux.

Il faut pouvoir faire quelque chose du genre :

```python
config = device.read_configuration()

config.kits[0].inputs[0].tip.note = 36
config.kits[0].inputs[1].tip.note = 38
config.kits[0].inputs[1].ring.note = 40

device.write_configuration(config)
```

Mais l'écriture ne doit être activée que lorsque le protocole est suffisamment compris et validé.

---

# Phase 7 — Library

Créer une vraie package Python, par exemple :

```text
ddti/
    transport/
        midi.py
        sysex.py

    protocol/
        codec.py
        checksum.py
        parser.py

    models/
        device.py
        kit.py
        trigger.py

    device.py
    backup.py
    validation.py
```

API Python souhaitée :

```python
from ddti import DDTi

device = DDTi.connect()

info = device.get_info()

config = device.read_configuration()

device.backup("backup.syx")

config.kits[0].inputs[0].tip.note = 36

device.write_configuration(config)
```

Toutes les écritures doivent être validées avant transmission.

---

# Phase 8 — CLI

Créer une CLI utilisable indépendamment de la GUI.

Exemples :

```bash
ddti devices

ddti info

ddti monitor

ddti dump backup.syx

ddti decode backup.syx

ddti diff dump1.syx dump2.syx

ddti backup backups/

ddti get

ddti get kit 0

ddti get input 2

ddti set kit 0 input 2 tip note 38

ddti restore backup.syx
```

Pour toute opération destructive ou d'écriture, afficher clairement ce qui va être envoyé.

---

# Phase 9 — API locale

Créer une API locale autour de la library.

Utilise de préférence :

**FastAPI**

Endpoints envisagés :

```text
GET  /device
GET  /device/status

GET  /configuration
GET  /kits
GET  /kits/{kit}
GET  /inputs
GET  /inputs/{input}

POST /backup
POST /restore

PATCH /kits/{kit}
PATCH /kits/{kit}/inputs/{input}

GET  /monitor
```

Si approprié, utiliser WebSocket pour :

```text
/ws/midi
```

afin d'afficher en direct les triggers reçus.

Ne duplique pas la logique métier dans FastAPI : l'API doit appeler la library centrale.

---

# Phase 10 — GUI

Créer une GUI desktop.

Technologie préférée :

**PySide6**

Je veux une interface simple et dense, adaptée à la configuration d'un drum trigger interface.

## Page principale

Table de type :

| Input | Zone | Note | Name | Channel | Trigger Type | Gain | Threshold | Curve | X-Talk | Retrigger |
| ----- | ---- | ---- | ---- | ------- | ------------ | ---- | --------- | ----- | ------ | --------- |

Avec édition directe lorsque cela est possible.

## MIDI Learn

Ajouter un mode MIDI monitor / learn permettant de voir :

```text
Input / zone détectée
MIDI note
Velocity
Channel
```

## Kits

Permettre :

* sélection du kit ;
* copie d'un kit ;
* modification ;
* sauvegarde ;
* comparaison entre kits.

## Backup / restore

Boutons explicites :

```text
Read from DDTi
Write to DDTi
Backup
Restore
Save file
Load file
```

Lors d'un `Write to DDTi`, montrer un diff :

```text
Input 2 Tip:
    Note 38 -> 40

Input 4:
    Gain 12 -> 16
```

avant écriture.

---

# Phase 11 — Presets

Préparer l'architecture pour supporter des mappings nommés.

Exemples futurs :

```text
GM
Superior Drummer 3
Superior Drummer 3 - Death & Darkness
Superior Drummer 3 - Modern Metal
ddrum4
Custom
```

Je veux pouvoir stocker ces mappings sous une forme lisible :

```yaml
name: Superior Drummer 3
kit:
  kick:
    note: 36
  snare:
    tip: 38
    ring: 40
```

Ne hardcode pas les presets dans la GUI.

---

# Phase 12 — API pour intégration future

Le projet servira potentiellement plus tard à communiquer avec :

* un Arduino MIDI router ;
* le ddrum4 ;
* Superior Drummer 3 ;
* d'autres logiciels MIDI.

Il faut donc séparer strictement :

```text
DDTi protocol
DDTi data model
DDTi device transport
Mapping/preset layer
GUI
REST API
```

La library centrale ne doit dépendre ni de PySide6 ni de FastAPI.

---

# Phase 13 — Tests

Écrire des tests pour :

* SysEx parser ;
* encode/decode ;
* checksum ;
* round-trip ;
* dumps ;
* comparaison ;
* validation des plages ;
* serialization ;
* presets.

Un test fondamental :

```python
decoded = decode(original_dump)
encoded = encode(decoded)

assert encoded == original_dump
```

avant toute modification.

Ensuite tester :

```python
decode -> modify one parameter -> encode
```

et vérifier que seuls les bytes attendus changent.

---

# Phase 14 — Validation hardware

Ne considère pas un champ comme compris après un seul test.

Pour chaque champ important, idéalement valider :

* au moins 3 valeurs ;
* au moins 2 inputs ;
* lorsque pertinent au moins 2 kits.

Exemple :

```text
35 -> 36
36 -> 37
37 -> 48
```

Cela permettra de différencier :

* valeur MIDI brute ;
* index ;
* table lookup ;
* packed integer ;
* checksum.

---

# Phase 15 — Journal de reverse engineering

Maintenir en permanence :

`docs/REVERSE_ENGINEERING.md`

Avec une table :

| Field           | Offset/address | Encoding | Scope   | Confidence | Validation      |
| --------------- | -------------: | -------- | ------- | ---------- | --------------- |
| Input1 Tip Note |            ... | uint7    | per kit | confirmed  | tested 35/36/48 |
| Input1 Channel  |            ... | ...      | per kit | probable   | ...             |
| Gain            |            ... | ...      | global  | confirmed  | ...             |

Utiliser des niveaux :

```text
UNKNOWN
HYPOTHESIS
PROBABLE
CONFIRMED
```

Ne jamais présenter une hypothèse comme une certitude.

---

# Git / commits

Travaille de manière incrémentale.

Fais des commits explicites aux étapes importantes, par exemple :

```text
chore: identify connected DDTi USB device
feat: add MIDI traffic monitor
feat: capture raw DDTi SysEx dumps
feat: add binary SysEx diff tool
docs: document initial DDTi SysEx framing
feat: decode DDTi kit note mappings
feat: implement DDTi configuration model
feat: add safe configuration writer
feat: add FastAPI service
feat: add PySide6 editor
```

Ne mélange pas reverse engineering expérimental et grosse refactorisation dans le même commit.

---

# Priorité

Ne commence pas par construire la GUI.

L'ordre est impérativement :

```text
1. Detect device
2. Capture
3. Backup
4. Analyze
5. Diff
6. Decode
7. Encode
8. Verify round-trip
9. Controlled write
10. Library
11. CLI
12. API
13. GUI
```

La GUI n'a de valeur que lorsque le protocole est compris.

---

# Comportement attendu pendant le reverse engineering

Tu as accès au DDTi USB mais pas à mes mains.

Quand une intervention sur le panneau du DDTi est indispensable, arrête-toi uniquement à cet endroit et donne-moi une instruction extrêmement précise, par exemple :

> Sur le DDTi, mets Kit 0 / Input 1 Tip sur MIDI Note 35, puis déclenche le SysEx dump. Ne change aucun autre paramètre.

Une fois que je l'ai fait, continue immédiatement l'analyse.

Demande le moins d'interventions manuelles possible.

Automatise chaque étape répétitive.

---

# Livrables finaux

Je veux au minimum :

```text
README.md

docs/
    DEVICE_IDENTIFICATION.md
    SYSEX_PROTOCOL.md
    REVERSE_ENGINEERING.md
    API.md

src/ddti/
    ...

tests/
    ...

captures/
    ...

presets/
    gm.yaml
    sd3.yaml

tools/
    ...

gui/
    ...
```

Avec :

* package Python fonctionnelle ;
* CLI ;
* SysEx parser/encoder ;
* backup/restore ;
* lecture/écriture de configuration si le protocole le permet ;
* FastAPI ;
* GUI PySide6 ;
* documentation du protocole ;
* tests ;
* exemples.

---

# Critère principal de réussite

À terme je veux pouvoir lancer le software, connecter mon **DDTi 2016 en USB**, lire sa configuration et obtenir quelque chose comme :

```text
DDTi 2016 — Connected

Kit: SD3

Input 1 Kick
    Tip note: 36
    Channel: 10

Input 2 Snare
    Tip: 38
    Ring: 40
    Channel: 10

Input 3 Hi-Hat
    Open: 46
    Closed: 42
    Pedal: 44

...
```

modifier ces paramètres depuis le PC, cliquer sur :

```text
Write to DDTi
```

et retrouver immédiatement cette configuration sur le module.

Le software doit également permettre à un autre programme de faire exactement la même chose via la Python API ou la REST API.

Commence maintenant par **identifier le DDTi connecté et ses interfaces USB/MIDI**, puis construis les outils de capture nécessaires. Ne commence pas la GUI tant qu'un premier dump SysEx n'a pas été capturé et analysé.
