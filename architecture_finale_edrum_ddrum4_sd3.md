---
title: "Architecture finale — eDrum multi-style DDrum4 + Arduino + SD3/DrumGizmo"
author: "Document d'architecture"
date: "21 août 2026"
lang: fr-FR
version: "2.0"
---

# 1. Objet du document

Ce document décrit l'architecture complète du système eDrum, depuis les pads physiques jusqu'aux trois renderers possibles :

- **DDrum4** comme renderer hardware autonome, compact et fiable ;
- **Superior Drummer 3 (SD3)** comme renderer software haute qualité, avec un **unique mega-kit** contenant toutes les variations de sons.
- **DrumGizmo** comme renderer software Linux optionnel, construit depuis la bibliothèque de captures et un seul kit logique chargé.

L'objectif est que les renderers représentent **le même kit logique** et le même état de jeu : Modern Metalcore, Sleep Token, Deftones, Drum'n'Bass, Industrial, Trap, etc. Les différences sont uniquement dues aux capacités des moteurs : environ 8 MB et 10 channels actifs côté DDrum4, un kit SD3 riche sous Windows, ou un kit DrumGizmo exporté sous Linux.

Le système doit fonctionner dans quatre contextes :

1. **répétition sans PC audio** : DDrum4 seul comme renderer ;
2. **répétition/live avec SD3 ou DrumGizmo** : un renderer software comme principal, DDrum4 disponible simultanément ;
3. **fallback live** : bascule rapide vers l'audio DDrum4 si le PC/software renderer n'est plus utilisable ;
4. **enregistrement** : conservation du jeu MIDI brut, de l'état des Programs/Virtual Palettes et rendu software reconfigurable après la prise.

Le design doit également rester extensible : ajout de pads, de Sounds DDrum4, d'instruments SD3, de nouvelles scènes ou d'un contrôleur MIDI externe sans changer l'architecture fondamentale.

---

# 2. Principe central : un état logique, trois renderers

La notion la plus importante est la séparation entre :

- **l'événement physique** : « Stack frappé à velocity 104 », « Snare1 edge », « China2 bell », etc. ;
- **l'état logique du kit** : Program/Scene + choix des snares + layout des percussions ;
- **le son logique demandé** : Acoustic Stack, Glitch, Deftones Rimshot, Industrial Hit, etc. ;
- **le renderer** : traduction de ce son logique vers DDrum4, SD3 ou DrumGizmo.

La chaîne conceptuelle est :

```text
RAW MIDI EVENT
    ↓
SOURCE PROFILE
    ↓
PHYSICAL EVENT
    ↓
LOGICAL STATE
Program + VP1 + VP2 + VP3 + VP4
    ↓
LOGICAL SOUND / ARTICULATION
    ├─────────────────────────────┐
    ↓                             ↓
DDrum4 Renderer              SD3 Renderer
    ↓                             ↓
Sound/Variation/NOTE P        Note/CC du mega-kit
    ↓                             ↓
DDrum4 audio                  SD3 audio
```

Exemple : le pad **Stack** produit toujours le même événement physique. Selon la scène :

| État | Événement physique | Son logique |
|---|---|---|
| Metalcore | `stack.hit` | Acoustic Stack |
| Sleep Hybrid | `stack.hit` | Acoustic Stack ou Impact |
| DnB | `stack.hit` | Glitch |
| Industrial | `stack.hit` | Metallic Hit |
| Trap | `stack.hit` | Clap ou Acoustic Stack |

Arduino et le `Midi Converter` doivent donc partager **la même définition de l'état logique**, mais chacun possède son propre renderer.

---

# 3. Point critique DDrum4 : `Local = Off`

Le DDrum4 est configuré avec **MIDI Local Control = Off (`L.Of`)**.

Cela signifie :

- les pads branchés au DDrum4 **n'activent pas directement les sons internes** ;
- ils émettent leurs événements par `MIDI OUT` ;
- ces événements passent par le Merger et Arduino ;
- Arduino les interprète en fonction du Program courant ;
- Arduino renvoie ensuite au `MIDI IN` du DDrum4 **la note correspondant au son réellement demandé** ;
- c'est cette note de retour qui produit l'audio.

Exemple :

```text
Pad Stack physique
    ↓
DDrum4 MIDI OUT : raw note 85   (exemple)
    ↓
Arduino : Program = DnB
    ↓
stack.hit → logical sound = Glitch
    ↓
DDrum4 Renderer → note 86       (exemple)
    ↓
Arduino MIDI OUT
    ↓
DDrum4 MIDI IN
    ↓
Glitch audio
```

En Metalcore, le même raw hit serait transformé vers la note DDrum4 de `Acoustic Stack`.

**Conséquence majeure : toutes les notes de batterie doivent être interprétées par Arduino, y compris celles provenant des pads branchés directement au DDrum4.**

---

# 4. Inventaire des pads physiques

| Pad | Articulations / expressions utiles |
|---|---|
| Kick | Hit |
| Tom 1 | Hit |
| Tom 2 | Hit |
| Tom 3 | Hit |
| **Tom 4 / Snare 2** | Tom hit ou Snare Center/Mid/Edge positionnelle |
| **Rim 2** | Rimshot + Cross-stick/Rim de la Snare2 |
| **Snare 1** | Center/Mid/Edge ; trois positions suffisent |
| **Rim 1** | Rimshot + Cross-stick/Rim |
| Hi-Hat + pedal | Bow, Edge, CC d'ouverture continu, Pedal Close, Pedal Splash |
| Splash 1 | Hit + choke |
| Splash 2 | Hit + choke |
| Ride | Bow, Bell, choke |
| Crash 1 | Bow, Edge, choke |
| Crash 2 | Bow, Edge, choke |
| Crash 3 | Edge, choke |
| China 1 | Edge, Bell, choke |
| China 2 | Edge, Bell, choke |
| Perc | Hit |
| **Stack** | Hit ; Acoustic Stack par défaut en Metalcore |

Deux surfaces sont volontairement très flexibles :

- **Tom4/Snare2** : quatrième tom, seconde snare acoustique, e-snare DnB/Industrial/Trap ;
- **Stack** : Stack acoustique ou surface supplémentaire de percussion/FX selon la scène.

---

# 5. Topologie matérielle actuelle

## 5.1 MIDI

```text
                  USB ─────────────────────────► PC / Midi Converter
                 /
eDRUMin ─────────┤
                 \ MIDI [CH_EDRUM] ────┐
                                        │
                  USB ──────────────────┼──────► PC / Midi Converter
                 /                      │
DDTi ────────────┤                      │
                 \ MIDI [CH_DDTI] ─────┤
                                        │
DDrum4 MIDI OUT [CH_DDRUM] ────────────┤
                                        ▼
                                  DRUM MIDI MERGER
                                        │
                                        ▼
                                     ARDUINO
                                   /         \
                                  /           \
                        MIDI OUT               HARDWARE THRU
                           │                        │
                           ▼                        ▼
                     DDrum4 MIDI IN          UMC404HD MIDI IN
                           │                        │
                           ▼                        ▼
                      DDrum4 audio             PC / Converter
```

Le `hardware THRU` est un **vrai THRU matériel** : il reproduit le bus reçu **avant toute transformation Arduino**.

Il ne faut donc jamais considérer le THRU comme « la sortie MIDI transformée ». Sa fonction est au contraire de fournir au PC le jeu brut et les messages d'état originaux.

## 5.2 Entrées PC recommandées

Le PC reçoit actuellement :

- eDRUMin directement en USB ;
- DDTi directement en USB ;
- le bus MIDI brut via `UMC404HD MIDI IN` ;
- le contrôleur externe via l'interface MIDI externe/MIDI4x4 lorsque nécessaire.

En utilisation normale, le `Midi Converter` choisit une seule source primaire pour chaque device afin d'éviter les doublons :

| Device | Source PC primaire recommandée | Copie à ignorer |
|---|---|---|
| eDRUMin | USB direct | CH_EDRUM présent dans le THRU/UMC |
| DDTi | USB direct | CH_DDTI présent dans le THRU/UMC |
| DDrum4 pads | UMC MIDI IN / CH_DDRUM | aucune autre source directe |
| DDrum4 state SysEx/Program | UMC MIDI IN | — |
| External controller | MIDI4x4/direct actuellement | selon architecture future |

Un mode `DIN_ONLY` peut exister en fallback : le Converter ignore alors les USB eDRUMin/DDTi et accepte leurs channels dans le bus UMC.

---

# 6. Topologie cible avec un deuxième MIDI Merger

L'évolution recommandée ajoute un **Master Merger** en amont d'Arduino.

```text
 eDRUMin MIDI ──┐
 DDTi MIDI ─────┼──► DRUM MERGER ──────┐
 DDrum4 OUT ────┘                       │
                                         │
 UMC404HD MIDI OUT ──────────────────────┼──► MASTER MERGER ─► ARDUINO
                                         │
 External MIDI controller ────────────────┘                       │
                                                                  ├─ MIDI OUT → DDrum4 IN
                                                                  │
                                                                  └─ HW THRU → UMC MIDI IN
```

Cette architecture crée un **bus de contrôle bidirectionnel** :

- les pads et le DDrum4 peuvent générer des événements vers Arduino et le PC ;
- le PC peut demander un changement de scène via `UMC MIDI OUT` ;
- un contrôleur externe peut faire la même chose ;
- Arduino traduit les commandes logiques vers le protocole natif du DDrum4 ;
- le THRU rend les mêmes commandes visibles au `Midi Converter`, qui met à jour son état ;
- lorsqu'un Program/Palette est changé depuis le panneau DDrum4, le message repart dans le bus et met à jour Arduino **et** le Converter.

Le système n'a donc pas de « maître fixe ». L'état est **synchronisé bidirectionnellement**.

### 6.1 Limite de la topologie actuelle

Tant que le Master Merger n'est pas installé, un changement initié uniquement depuis le PC ou le contrôleur externe peut mettre à jour SD3 sans forcément atteindre Arduino/DDrum4. Pour les répétitions/live où les deux renderers doivent rester strictement synchronisés, utiliser temporairement le DDrum4 comme point de changement de Scene, ou effectuer le changement des deux côtés.

Dès que `UMC MIDI OUT` et l'External Controller entrent dans le Master Merger, cette limitation disparaît : le Converter peut émettre une commande logique, Arduino la reçoit, configure le DDrum4, et le bus de retour confirme le nouvel état.

---

# 7. Topologie audio et contrat de stems

Il existe un renderer hardware et un renderer software choisi par session. SD3 et DrumGizmo ne sont pas sommés ni pilotés simultanément par le Converter.

## 7.1 DDrum4

```text
DDrum4 audio OUT × 4
    ↓
Entrées mixer B1 / B2 / B3 / B4
```

`B1…B4` sont ici les labels de destination du système live ; le routage physique exact du DDrum4 vers ses quatre sorties utilisées reste à câbler selon le module.

## 7.2 SD3

```text
SD3
 ↓
UMC404HD Audio Output 1 / 2 / 3 / 4
 ↓
4 entrées dédiées du mixer
```

## 7.3 DrumGizmo

```text
Converter MIDI (port virtuel ALSA) -> a2jmidid -> JACK MIDI -> DrumGizmo (jackmidi)
                                                        -> JACK audio -> mixer/monitoring
```

Le kit DrumGizmo est exporté depuis la bibliothèque de captures, avec une note
par paire `instrument/articulation` du contrat `rig-project/v1`. Les Scenes et
VP sont résolus en amont par le Converter, qui choisit la note du Logical
Sound. DrumGizmo ne change pas de kit à chaque Scene.

La première cible validable est note-only : note-on/off et vélocité. Le CC4
continu, la position de snare et les chokes ne sont pas émis vers DrumGizmo
tant qu'un kit/backend n'a pas prouvé une convention MIDI stable pour eux.

Quand le kit DrumGizmo contient des articulations de charleston discrètes
validées, le profil peut toutefois déclarer `quantized_note` pour sa cible
DrumGizmo : le Converter mémorise le CC4 brut de l'eDRUMin puis choisit la
note bow/edge de la zone déclarée à la frappe suivante. Cette quantification
est propre au renderer DrumGizmo (notes et seuils explicitement mesurés) ;
elle ne réutilise ni les notes sources, ni les seuils `NOTE P` du DDrum4.
Elle reste `planned` tant que les captures et le kit exporté ne l'ont pas
validée.

## 7.4 Contrat commun recommandé

Pour faciliter les répétitions, le live et le fallback, les deux renderers doivent idéalement respecter les mêmes quatre familles de stems :

| Stem logique | Contenu |
|---|---|
| **DRUM-1 KICK** | Kick acoustique/electronic/808 |
| **DRUM-2 SNARES** | Snare1, Snare2, clap si utilisé comme snare |
| **DRUM-3 TOMS** | Toms acoustiques + e-toms/impacts de type tom |
| **DRUM-4 CYM/PERC** | HH, crashes, ride, chinas, stack, cowbell, woodblock, click, glitch, metallic hits |

Ce contrat n'est pas obligatoire pour le son, mais il rend la bascule DDrum4 ↔ renderer software beaucoup plus simple au mixer.

En live avec PC, les deux renderers peuvent rester actifs en parallèle. On utilise alors le mixer pour choisir :

- SD3 ou DrumGizmo audible, DDrum4 muté = fonctionnement principal ;
- DDrum4 audible, renderer software muté = fallback immédiat ;
- les deux peuvent être enregistrés simultanément si utile, mais ne doivent normalement pas être sommés en façade.

---

# 8. Modèle d'événement canonique

Les numéros MIDI sont des adresses de transport. La logique interne doit travailler avec des événements sémantiques.

Un événement canonique contient au minimum :

```text
source_device
physical_pad
articulation
velocity
position              # si disponible
hihat_opening         # CC continu si disponible
choke                  # bool/event
pedal_expression       # si nécessaire
timestamp
```

Exemples :

```text
{ source=eDRUMin, pad=snare1, articulation=head, position=0.18, velocity=112 }
{ source=DDTi,    pad=china2, articulation=edge, velocity=97, choke=false }
{ source=DDrum4,  pad=stack,  articulation=hit, velocity=106 }
```

Le `Source Profile` de chaque module réalise :

```text
raw channel + note + CC + aftertouch
                     ↓
              physical event
```

Cette étape **ne dépend jamais du Program courant**.

---

# 9. Channels MIDI et classes de messages

Allocation recommandée, modifiable si nécessaire :

| Channel | Usage |
|---:|---|
| **CH1** | `CH_DDRUM` — événements pads DDrum4 + Program Change natif |
| **CH2** | `CH_DDTI` — événements DDTi |
| **CH3** | `CH_EDRUM` — événements eDRUMin |
| **CH14** | `CH_EXT_CTRL` — commandes logiques d'un contrôleur externe |
| **CH15** | `CH_PC_CTRL` — commandes logiques émises par le Midi Converter/PC |
| **CH16** | réservé système/debug/futur |

Les SysEx DDrum4 sont **channel-less** : ils doivent être reconnus par leur contenu/protocole et non par un channel MIDI.

Il faut distinguer quatre classes :

1. **HIT** : Note On/Off, velocity ;
2. **EXPRESSION** : CC4 HH, position, Aftertouch/choke, etc. ;
3. **LOGICAL CONTROL** : Scene/VP1/VP2/VP3/VP4 ;
4. **NATIVE DDRUM STATE/CONTROL** : Program Change, Palette, SysEx DDrum4.

---
# 10. État logique global : Scene + Virtual Palettes

Pour éviter l'ambiguïté entre les Programs natifs du DDrum4 et les Programs du système complet, le document utilise :

- **Scene** ou **Logical Program** = état de style global partagé par Arduino et le Converter ;
- **DDrum4 Program/Palette** = mécanisme natif du module utilisé uniquement par le renderer hardware.

L'état minimal recommandé est :

```text
scene_id
vp1_snare1
vp2_flex_snare2_tom4
vp3_percussion_family
vp4_percussion_variant
```

On peut y ajouter ensuite :

```text
click_state
renderer_mode
song_id
subscene_id
```

sans changer le principe.

## 10.1 Rôle de chaque variable

| Variable | Rôle |
|---|---|
| `scene_id` | style global : Metalcore, Sleep, DnB, Industrial, Trap… |
| `VP1` | identité/configuration de Snare1 |
| `VP2` | rôle du pad Tom4/Snare2 et identité de Snare2 |
| `VP3` | famille générale de remapping des percussions/cymbales auxiliaires |
| `VP4` | variante 1–5 à l'intérieur de la famille VP3 |

La Scene fournit des **valeurs par défaut**. Les VP sont des overrides rapides.

Exemple :

```text
Scene = Metalcore
VP1 = Metalcore Premium
VP2 = Deftones Side Snare
VP3 = Acoustic
VP4 = Cowbell
```

Le résultat logique est un kit Metalcore avec Snare1 Metalcore, Snare2 Deftones, Stack acoustique et pad Perc = Cowbell.

---

# 11. Synchronisation bidirectionnelle de l'état

## 11.1 Changement depuis le DDrum4

Quand l'utilisateur change un Program/Palette sur le panneau DDrum4 :

```text
DDrum4
  ↓ native Program/Palette/SysEx
Merger
  ├─► Arduino → decode NativeControlMap → update Logical State
  │
  └─► Hardware THRU → PC → Midi Converter → même update
```

Arduino peut ensuite réappliquer la configuration renderer complète si le changement natif ne correspond qu'à une partie de l'état logique.

Exemple : un bouton de Palette DDrum4 peut être utilisé comme **contrôle physique VP3**, même si VP3 n'est pas équivalent à la Palette native DDrum4.

## 11.2 Changement depuis le PC — architecture cible

La méthode recommandée n'est pas que le Converter connaisse tous les détails du protocole DDrum4.

Il envoie plutôt une commande logique :

```text
CH_PC_CTRL : SET_SCENE / SET_VP1 / SET_VP2 / SET_VP3 / SET_VP4
          ↓
UMC MIDI OUT
          ↓
Master Merger
          ↓
Arduino
          ↓
update state + traduction vers DDrum4 Program/Palette/SysEx
```

Le hardware THRU rend la commande visible au Converter, mais elle doit être traitée de façon **idempotente** : recevoir l'écho de sa propre commande ne doit pas provoquer un nouveau broadcast.

Le Converter peut également envoyer directement un SysEx DDrum4 si nécessaire, mais ce mode doit rester une option de compatibilité plutôt que l'API logique principale.

## 11.3 Changement depuis un contrôleur externe

Même principe :

```text
External Controller
     ↓ CH_EXT_CTRL
Master Merger
     ├─► Arduino → update + DDrum4 renderer state
     └─► HW THRU → Midi Converter → update SD3 renderer state
```

Le contrôleur externe ne doit pas avoir besoin de connaître le protocole DDrum4.

## 11.4 Protocole logique recommandé

Une proposition simple :

| Message | Signification |
|---|---|
| Program Change sur CH14/CH15 | `scene_id` |
| CC20 | VP1, valeurs 0–4 |
| CC21 | VP2, valeurs 0–4 |
| CC22 | VP3, valeurs 0–4 |
| CC23 | VP4, valeurs 0–4 |
| CC24 | Click on/off ou action PC dédiée |
| CC25–31 | réservés |

Les numéros peuvent être changés. Le point important est d'avoir un **protocole logique stable**, indépendant du DDrum4 et de SD3.

---

# 12. Gestion des boucles et doublons

Le système contient volontairement plusieurs boucles physiques. Elles doivent être gérées explicitement.

## 12.1 Boucle DDrum4 ↔ Arduino

Avec `L.Of` :

```text
DDrum4 raw hit → Arduino → converted hit → DDrum4 IN
```

Si le DDrum4 réémet au MIDI OUT une note reçue au MIDI IN, elle revient au Merger puis à Arduino.

Arduino doit utiliser son mécanisme existant de **echo suppression / loop guard** pour ne pas la renvoyer une seconde fois.

La règle est :

- une vraie frappe DDrum4 doit toujours être traitée ;
- une note qui correspond au retour récent d'une note produite par Arduino doit être absorbée ;
- les messages d'état peuvent être acceptés plusieurs fois si la mise à jour est idempotente.

## 12.2 Le hardware THRU ne peut pas supprimer cette boucle

Le THRU est matériel. Si le DDrum4 réémet une note de retour, le PC peut donc aussi la voir.

Le `Midi Converter` doit posséder **son propre loop/echo guard** sur CH_DDRUM.

Approche robuste : lorsque le Converter reçoit une vraie frappe physique DDrum4, il calcule en parallèle la note que le renderer DDrum4 est censé produire et place cette note dans une courte table `expected_ddrum_echo`. Si la même note revient immédiatement depuis CH_DDRUM, elle est ignorée comme echo.

Ce mécanisme peut être désactivé si les tests montrent que le DDrum4 ne retransmet pas les notes reçues dans la configuration utilisée.

## 12.3 DDTi/eDRUMin reçus deux fois par le PC

En mode recommandé :

```text
eDRUMin USB  → ACCEPT
DDTi USB     → ACCEPT
UMC CH_EDRUM → IGNORE
UMC CH_DDTI  → IGNORE
UMC CH_DDRUM → ACCEPT
```

En mode `DIN_ONLY` :

```text
eDRUMin USB  → IGNORE
DDTi USB     → IGNORE
UMC CH_EDRUM → ACCEPT
UMC CH_DDTI  → ACCEPT
UMC CH_DDRUM → ACCEPT
```

## 12.4 Echo des commandes PC dans l'architecture future

Avec `UMC MIDI OUT → Master Merger → Arduino → HW THRU → UMC MIDI IN`, le PC reçoit ses propres commandes logiques.

Le Converter doit donc :

- soit ignorer un message identique qu'il vient d'émettre dans une courte fenêtre ;
- soit simplement traiter `SET_STATE(x)` comme idempotent sans le retransmettre.

---

# 13. Responsabilités exactes d'Arduino

Arduino est le **renderer DDrum4 + gestionnaire d'état hardware**.

Il doit :

1. lire tous les événements du bus MIDI ;
2. identifier la source par channel/protocole ;
3. convertir les événements HIT/EXPRESSION en événements physiques ;
4. maintenir `Scene + VP1..VP4` ;
5. décoder les changements DDrum4 natifs ;
6. décoder les commandes logiques PC/externe ;
7. convertir chaque événement physique en son logique selon l'état ;
8. utiliser le `DDrum4 Renderer Map` pour produire `note + velocity + CC/Aftertouch` ;
9. préserver la velocity 1–127 ;
10. convertir les positions/articulations en `NOTE P` ;
11. quantifier le CC d'ouverture du HH uniquement pour le renderer DDrum4 ;
12. envoyer au DDrum4 les Program/Palette/SysEx nécessaires à l'état ;
13. empêcher les boucles de notes retournées ;
14. ne jamais modifier le contenu du hardware THRU.

Pseudo-pipeline :

```text
on_midi(event):
    if is_recent_ddrum_echo(event):
        return

    if is_logical_control(event):
        update_state(event)
        apply_ddrum_state()
        return

    if is_ddrum_native_state(event):
        update_state_from_native(event)
        reconcile_ddrum_state_if_needed()
        return

    physical = source_profile[event.source].decode(event)
    logical  = scene_router.resolve(physical, current_state)
    rendered = ddrum_renderer.render(logical, physical.expression)
    midi_out.send(rendered)
```

---

# 14. Responsabilités exactes du `Midi Converter`

Le `Midi Converter` est le **renderer SD3 + UI/state manager côté PC**.

Il doit :

1. ouvrir les entrées USB eDRUMin et DDTi ;
2. ouvrir le bus UMC MIDI IN ;
3. ouvrir éventuellement l'entrée du contrôleur externe ;
4. appliquer la politique de sources primaires/duplicates ;
5. décoder les mêmes événements physiques qu'Arduino ;
6. maintenir le même `Scene + VP1..VP4` ;
7. décoder les messages natifs DDrum4 de Program/Palette/SysEx ;
8. afficher clairement l'état courant ;
9. permettre de modifier la Scene/VP depuis l'UI ;
10. émettre les commandes logiques vers `UMC MIDI OUT` lorsque le Master Merger sera installé ;
11. appliquer son propre echo guard ;
12. résoudre `physical event + state → logical sound` ;
13. utiliser le `SD3 Renderer Map` ;
14. préserver les informations haute résolution disponibles uniquement côté PC, notamment le **CC4 continu du Hi-Hat** et la position de snare si elle est disponible ;
15. produire un unique flux MIDI propre vers SD3.

Le Converter ne doit pas raisonner à partir du Sound DDrum4 actuellement assigné. Le bus qu'il reçoit via le hardware THRU est **le bus brut**.

Exemple :

```text
UMC reçoit CH_DDRUM note 40
source profile : "le trigger DDrum4 TOM-LOW est physiquement Tom3"
→ physical event = tom3.hit
→ Scene Sleep
→ logical sound = Sleep Tom3
→ SD3 note 62
```

Le fait que la note 40 puisse aussi être la note renderer d'un autre Sound DDrum4 est sans importance : **source raw map et renderer map sont deux tables distinctes**.

---

# 15. Superior Drummer 3 : un seul mega-kit

SD3 contient en permanence **toutes les destinations** nécessaires :

- kicks Metalcore, Sleep, DnB, Industrial, 808/Trap ;
- snares Metalcore, Deftones, Sleep Token ;
- snares électroniques DnB/Industrial/Trap ;
- quatre toms et leurs variantes nécessaires ;
- HH acoustique expressif + e-HH ;
- crash1/2, crash3, splashes, chinas, ride, stack ;
- Clap, Click, Metallic Hit, Glitch, e-toms, Cowbell, Woodblock, Impact, etc.

Tous les instruments sont **déjà mixés** dans ce même kit.

Un changement de Scene ne charge donc rien dans SD3. Il modifie uniquement les tables de routing :

```text
physical event + state
        ↓
logical sound
        ↓
custom SD3 MIDI note / CC
```

Cela permet :

- des changements instantanés ;
- aucun temps de chargement entre styles ;
- une seule configuration audio 4-stems ;
- l'enregistrement du MIDI brut avant toute décision sonore ;
- le changement de Scene après la prise.

---

# 16. DDrum4 : principes du renderer hardware

## 16.1 `NOTE P` comme mécanisme principal

Les 10 channels DDrum4 reçoivent des blocs de notes contiguës. `NOTE P` permet 1, 2, 4 ou 8 notes consécutives. Dans cette architecture on réserve **8 numéros par channel**, même si tous ne sont pas utilisés immédiatement.

La velocity n'est **jamais** découpée pour sélectionner une articulation.

```text
velocity 1–127 = dynamique uniquement
note offset    = position/articulation
```

## 16.2 Sounds, Layers, Variations

Le design utilise les capacités suivantes de `ddrum4UI`/format Sound :

- jusqu'à 10 samples ;
- jusqu'à 10 layers ;
- jusqu'à 10 Variations ;
- réponse velocity et position par layer ;
- layers involved/sequenced selon la programmation ;
- pitch/decay/filter pour construire plusieurs caractères à partir d'une même source.

Les Variations servent surtout à changer **le caractère d'un Sound résident** sans recopier les samples.

## 16.3 Round robin

La priorité est :

1. vrais velocity layers ;
2. vrais alternates là où le machine-gun est le plus audible ;
3. filtres dynamiques/random pour les micro-variations ;
4. RR concentré sur Center hard / rimshot hard plutôt que partout.

---
# 17. Les 10 Sounds du core DDrum4

## 17.1 Vue d'ensemble

| # | Sound résident | Fonction | Priorité |
|---|---|---|---:|
| **S01** | `KICK_MASTER` | Kick acoustique + kicks électroniques | Haute |
| **S02** | `SNARE_PREMIUM_HEAD` | Snare acoustique premium multi-style | **Maximale** |
| **S03** | `RIM_PAIR_PREMIUM` | Deux jeux Rimshot/Cross-stick simultanés | **Très haute** |
| **S04** | `TOMS_123` | Toms 1–3 | Haute |
| **S05** | `TOM4_SNARE2_FLEX` | Tom4 + snare compacte + e-snares | Très haute |
| **S06** | `HH_BOW` | Hi-Hat bow multi-ouvertures | **Maximale** |
| **S07** | `HH_EDGE_PEDAL` | Hi-Hat edge + pedal | **Maximale** |
| **S08** | `CRASH1_AUX` | Crash1 HQ + cymbales auxiliaires | **Maximale** |
| **S09** | `CRASH2_RIDE` | Crash2 HQ + Ride | **Maximale** |
| **S10** | `PERC10_STACK` | Stack + percussions courtes | Flexible |

Important : `S01…S10` sont des **fichiers Sound résidents**, pas dix pads physiques. Un Program DDrum4 assigne ces fichiers aux dix channels actifs.

## 17.2 Affectation des dix channels dans le Program core

| Channel DDrum4 | Base NOTE P proposée | Sound core | Rôle renderer |
|---|---:|---|---|
| **KICK** | 0 | S01 | Kick |
| **SNARE** | 8 | S02 | Snare1 premium |
| **RIM** | 16 | S03 | Rim pair A/B |
| **TOM HIGH** | 24 | S04 | Toms 1–3 multiplexés |
| **TOM MID** | 32 | S05 | Tom4 / Snare2 / e-snare |
| **TOM LOW** | 40 | S07 | HH Edge/Pedal renderer secondaire |
| **PERC** | 48 | S10 | Stack/percussion bank |
| **CYMBAL 1** | 56 | S08 | Crash1/Aux |
| **CYMBAL 2** | 64 | S09 | Crash2/Ride |
| **HI-HAT** | 72 | S06 | HH Bow principal |

On réserve donc dix blocs de huit notes :

```text
0–7    KICK
8–15   SNARE
16–23  RIM
24–31  TOM HIGH
32–39  TOM MID / FLEX
40–47  TOM LOW / HH EDGE
48–55  PERC
56–63  CYMBAL 1
64–71  CYMBAL 2
72–79  HI-HAT
80–127 réservés à l'évolution / tests
```

Cette table est le **namespace renderer DDrum4**.

Le DDrum4 utilise le même `NOTE #` pour émettre et répondre sur chaque channel. Avec `Local Off`, les notes émises par les pads physiques restent cependant interprétées via la **Raw Source Map** avant d'être éventuellement renvoyées vers un autre bloc renderer.

---

# 18. S01 — `KICK_MASTER`

| Position | Layers | Contenu |
|---|---:|---|
| P1 | L1–L5 | Kick acoustique principal, 5 velocity layers |
| P2 | L6 | Hard alternate acoustique |
| P3 | L7 | Kick DnB/electronic court |
| P4 | L8 | Kick Industrial/distorted |
| P5 | L9 | 808/Trap kick |
| P6 | L10 | Sub/body reinforcement optionnel |

Variations :

| Variation | Style | Direction |
|---|---|---|
| **V1 Metalcore** | tight | attaque nette, decay contrôlé |
| **V2 Sleep Token** | profond | plus de body/sub, légèrement plus long |
| **V3 DnB** | electronic | L7 principal |
| **V4 Industrial** | distorted | L8 principal |
| **V5 Trap** | 808 | L9 principal |

Le kick acoustique reçoit moins de RR que la snare : la mémoire est mieux investie dans plusieurs niveaux de velocity et dans la Snare/HH/Crashes.

---

# 19. S02 — `SNARE_PREMIUM_HEAD`

S02 est le Sound le plus important du module. Sa source doit être suffisamment riche pour accepter plusieurs Variations crédibles.

## 19.1 Layers

| Position | Layers | Fonction |
|---|---:|---|
| **P1** | L1–L3 | Center Soft / Medium / Hard A |
| **P2** | L4 | Center Hard B |
| **P3** | L5 | Center Hard C |
| **P4** | L6–L8 | Mid Soft / Medium / Hard |
| **P5** | L9–L10 | Edge Soft/Medium / Hard |

Le vrai RR est concentré sur le **Center hard**.

## 19.2 Variations premium

| Variation | Identité | Tuning indicatif | Decay | Direction de timbre |
|---|---|---|---|---|
| **V1 Metalcore** | tight / moderne | réf. | court | attaque nette, body propre |
| **V2 Deftones-like** | organique / plus bas | ~ -1 à -1.5 st | +20–35 % | plus de mids/body, moins clinique, plus de ring |
| **V3 Sleep-like** | profond / massif | ~ -0.5 à -1 st | +10–25 % | crack conservé, low body renforcé |
| V4 | low/loose | libre | long | réserve |
| V5 | tight alt | libre | court | réserve |

Ces paramètres sont des directions de programmation. Ils doivent être ajustés au sample source réellement choisi.

## 19.3 Deux Variations de S02 simultanément

Le même fichier Sound peut être assigné à deux channels actifs différents avec deux Variations différentes.

Exemple :

```text
SNARE channel  → S02 V1 Metalcore
TOM MID channel → S02 V2 Deftones-like
```

Cela produit deux snares haut de gamme en parallèle sans dupliquer les samples dans la Flash.

---

# 20. S03 — `RIM_PAIR_PREMIUM`

S03 contient **deux ensembles de rims simultanés**, A et B, afin que deux snares premium puissent coexister sans sacrifier le channel PERC/Stack.

| Position | Layers | Fonction |
|---|---:|---|
| **P1** | L1–L2 | Rimshot A Soft / Hard A |
| **P2** | L3 | Rimshot A Hard B |
| **P3** | L4–L5 | Cross-stick/Rim A Soft / Hard |
| **P4** | L6–L7 | Rimshot B Soft / Hard A |
| **P5** | L8 | Rimshot B Hard B |
| **P6** | L9–L10 | Cross-stick/Rim B Soft / Hard |

Variations de paire :

| Variation | Rim A | Rim B |
|---|---|---|
| **V1** | Metalcore | Metalcore |
| **V2** | Metalcore | Deftones-like |
| **V3** | Metalcore | Sleep-like |
| **V4** | Deftones-like | Sleep-like |
| **V5** | Deftones-like | Deftones-like |
| **V6** | Sleep-like | Sleep-like |

Arduino peut inverser les pads Rim1/Rim2 vers les slots A/B : l'ordre physique n'est pas un problème.

---

# 21. S04 — `TOMS_123`

| Position | Layers | Contenu |
|---|---:|---|
| **P1** | L1–L3 | Tom1 Soft / Medium / Hard |
| **P2** | L4–L6 | Tom2 Soft / Medium / Hard |
| **P3** | L7–L9 | Tom3 Soft / Medium / Hard A |
| **P4** | L10 | Tom3 Hard B |

Variations :

- **V1 Metalcore** : tight, decay contrôlé ;
- **V2 Sleep** : plus bas, plus long, plus massif ;
- **V3 Deftones** : plus ouvert/organique si nécessaire.

Les pads Tom peuvent être reroutés vers des percussions/e-toms dans les scènes électroniques sans modifier les samples acoustiques.

---

# 22. S05 — `TOM4_SNARE2_FLEX`

S05 est le slot pivot : Tom4, seconde snare compacte et snares électroniques.

## 22.1 Layers révisés

| Position | Layers | Contenu |
|---|---:|---|
| **P1** | L1–L2 | Tom4 Soft / Hard |
| **P2** | L3–L4 | Snare2 Center Soft / Hard |
| **P3** | L5 | Snare2 Mid |
| **P4** | L6 | Snare2 Edge |
| **P5** | L7 | Snare2 Rimshot |
| **P6** | L8 | Snare2 Cross-stick/Rim |
| **P7** | L9 | E-Snare DnB/Electro source |
| **P8** | L10 | E-Snare Industrial/Trap source |

Cette répartition donne moins de détail à la snare compacte qu'à S02/S11/S12, mais elle préserve :

- position Center/Mid/Edge ;
- Rimshot ;
- Cross-stick ;
- deux vraies sources de snare électronique.

## 22.2 Variations

| Variation | Fonction |
|---|---|
| **V1** | Tom4 + Snare2 Metalcore compacte |
| **V2** | Snare2 Deftones compacte |
| **V3** | Snare2 Sleep compacte |
| **V4** | DnB e-snare |
| **V5** | Industrial e-snare |
| **V6** | Trap/Electro snare |

---

# 23. S06/S07 — Hi-Hat premium

Le Hi-Hat est avec la snare l'élément le plus joué. Deux Sounds complets lui sont réservés.

## 23.1 S06 — `HH_BOW`

| Position | Layers | Ouverture |
|---|---:|---|
| P1 | L1–L2 | Tight Closed Soft/Hard |
| P2 | L3–L4 | Barely Open Soft/Hard |
| P3 | L5–L6 | 1/4 Open Soft/Hard |
| P4 | L7–L8 | 1/2 Open Soft/Hard |
| P5 | L9–L10 | Open Soft/Hard |

## 23.2 S07 — `HH_EDGE_PEDAL`

| Position | Layers | Fonction |
|---|---:|---|
| P1 | L1–L2 | Edge Closed Soft/Hard |
| P2 | L3–L4 | Edge 1/4 Open Soft/Hard |
| P3 | L5–L6 | Edge 1/2 Open Soft/Hard |
| P4 | L7–L8 | Edge Open Soft/Hard |
| P5 | L9 | Pedal Close/Chick |
| P6 | L10 | Pedal Splash |

### Règle de conversion

- côté DDrum4 : Arduino quantifie le CC d'ouverture vers les slots NOTE P ;
- côté SD3 : le Converter conserve **le CC4 continu original** et ne passe jamais par cette quantification.

---

# 24. S08 — `CRASH1_AUX`

| Position | Layers | Contenu |
|---|---:|---|
| **P1** | L1–L3 | Crash1 Bow Soft/Medium/Hard |
| **P2** | L4–L6 | Crash1 Edge Soft/Medium/Hard |
| **P3** | L7 | Splash partagé |
| **P4** | L8 | China Edge partagé |
| **P5** | L9 | China Bell partagé |
| **P6** | L10 | Crash3 Edge |

Splash1/Splash2 peuvent partager le sample ; China1/China2 peuvent partager leurs samples. Les pads restent indépendants dans la couche logique et peuvent être remappés différemment selon la Scene.

---

# 25. S09 — `CRASH2_RIDE`

| Position | Layers | Contenu |
|---|---:|---|
| **P1** | L1–L3 | Crash2 Bow Soft/Medium/Hard |
| **P2** | L4–L6 | Crash2 Edge Soft/Medium/Hard |
| **P3** | L7–L8 | Ride Bow Soft/Hard |
| **P4** | L9–L10 | Ride Bell Soft/Hard |

Crash1 et Crash2 sont volontairement les cymbales les plus détaillées.

---

# 26. S10 — `PERC10_STACK`

S10 est une banque de percussions pure. Les kicks électroniques sont dans S01 et les snares électroniques dans S05.

## 26.1 Samples résidents

| Layer | Son | Utilité |
|---:|---|---|
| **L1** | **Acoustic Stack** | Metalcore / hybrid |
| **L2** | Clap | Trap / DnB / hybrid |
| **L3** | Electronic HH Closed | DnB / Trap |
| **L4** | Electronic HH Open | DnB / Trap |
| **L5** | Click / Electronic Rim | DnB / Trap / utility |
| **L6** | Metallic Hit | Industrial |
| **L7** | Glitch / Noise Hit | DnB / Industrial |
| **L8** | Low Electronic Tom | DnB / Sleep / Industrial |
| **L9** | **Cowbell** | acoustic / DnB / Dance / utility |
| **L10** | **Woodblock** | acoustic / DnB / Dance / utility |

Cowbell et Woodblock sont conservés en permanence : ce sont des samples très courts et très utiles comme options futures.

Le Low e-tom peut être transformé par Variation/pitch en High e-tom ou Impact/boom si nécessaire.

## 26.2 NOTE P

| Position | Son par défaut | Alternative selon Variation |
|---|---|---|
| P1 | Acoustic Stack | — |
| P2 | Clap | — |
| P3 | E-HH Closed | — |
| P4 | E-HH Open | — |
| P5 | Click/Rim | — |
| P6 | Metallic Hit | — |
| P7 | Low E-Tom | Cowbell |
| P8 | Glitch/Noise | Woodblock |

## 26.3 Variations

| Variation | P7 | P8 | Usage |
|---|---|---|---|
| **V1 Acoustic** | Cowbell | Woodblock | Metalcore / utility |
| **V2 Hybrid** | Low E-Tom | Woodblock | Sleep / Modern Metal |
| **V3 DnB** | Low E-Tom | Glitch | DnB |
| **V4 Industrial** | Low E-Tom | Glitch | Industrial |
| **V5 Trap** | Cowbell ou E-Tom | Woodblock ou Glitch | Trap |
| V6 | Cowbell | Glitch | breakbeat / experimental |
| V7 | Low E-Tom | Woodblock | Dance / chill |

---
# 27. Sounds supplémentaires si la Flash le permet

Les Variations premium de S02 restent utiles même si des snares dédiées sont chargées. Les deux approches coexistent.

## 27.1 Gabarit `SNARE_*_FULL`

Une snare FULL tient Head + Rimshot + Cross-stick dans **un seul Sound/channel**.

| Position | Layers | Fonction |
|---|---:|---|
| **P1** | L1–L2 | Center Soft / Hard A |
| **P2** | L3 | Center Hard B |
| **P3** | L4–L5 | Mid Soft / Hard |
| **P4** | L6 | Edge |
| **P5** | L7–L8 | Rimshot Soft / Hard A |
| **P6** | L9 | Rimshot Hard B |
| **P7** | L10 | Cross-stick/Rim |

## 27.2 S11 — `SNARE_DEFTONES_FULL`

Caractère :

- accordage plus bas ;
- davantage de bas-médiums ;
- plus de ring ;
- transient moins clinique ;
- rimshot large et organique.

Variations possibles : `Default`, `Lower/Looser`, `Tighter`, `Darker`.

## 27.3 S12 — `SNARE_SLEEP_FULL`

Caractère :

- gros body ;
- crack conservé ;
- profondeur ;
- rimshot massif ;
- decay suffisamment long pour paraître grand sans gaspiller la Flash.

Variations possibles : `Default`, `Huge`, `Tight Modern`, `Dark`.

## 27.4 S13 — réserve

Uniquement si la mesure réelle de `MEM.LEFT` le permet : future snare acoustique, snare très basse ou banque spéciale.

---

# 28. Stratégies de double snare high-end

Le pad Tom4/Snare2 peut devenir une vraie seconde snare sans perdre S10/Stack.

## 28.1 Metalcore premium + Deftones FULL

```text
SNARE channel   → S02 V1 Metalcore
RIM channel     → S03 Rim A Metalcore
TOM MID channel → S11 Deftones FULL

Rim2 physical → positions Rimshot/Cross-stick directement dans S11
```

## 28.2 Metalcore premium + Sleep FULL

```text
SNARE channel   → S02 V1
RIM channel     → S03 Rim A
TOM MID channel → S12 Sleep FULL
```

## 28.3 Metalcore premium + Deftones premium-Variation

```text
SNARE channel   → S02 V1 Metalcore
TOM MID channel → S02 V2 Deftones-like
RIM channel     → S03 V2 = MC + Deftones rims
```

Coût Flash supplémentaire quasi nul.

## 28.4 Metalcore premium + Sleep premium-Variation

```text
SNARE channel   → S02 V1
TOM MID channel → S02 V3
RIM channel     → S03 V3 = MC + Sleep rims
```

## 28.5 Deftones + Sleep premium-Variations

```text
SNARE channel   → S02 V2
TOM MID channel → S02 V3
RIM channel     → S03 V4 = Deftones + Sleep rims
```

## 28.6 Deftones FULL + Sleep FULL

```text
SNARE channel   → S11 FULL
TOM MID channel → S12 FULL
```

Les rims sont contenus dans les deux Sounds FULL. Le channel RIM devient alors disponible pour une utilisation future ou peut rester inutilisé.

## 28.7 Fallback compact

Si aucune snare supplémentaire ne tient en Flash ou si un channel premium n'est pas disponible :

```text
SNARE channel   → S02 premium
TOM MID channel → S05 V2/V3 compact
```

---

# 29. Budget mémoire DDrum4

Les valeurs suivantes sont des **budgets de design**, pas des tailles garanties. La décision finale se prend après conversion réelle et mesure de `MEM.LEFT`.

| Sound | Cible indicative |
|---|---:|
| S01 Kick | ~320 blocks |
| S02 Snare Premium Head | ~900 |
| S03 Rim Pair Premium | ~400 |
| S04 Toms 1–3 | ~550 |
| S05 Tom4/Snare2 Flex | ~450 |
| S06 HH Bow | ~950 |
| S07 HH Edge/Pedal | ~700 |
| S08 Crash1/Aux | ~650 |
| S09 Crash2/Ride | ~700 |
| S10 Perc10/Stack | ~130 |
| **Core cible** | **~5750 blocks** |
| S11 Deftones FULL | ~600–700 |
| S12 Sleep FULL | ~600–700 |
| **Core + S11 + S12** | **~6950–7150** |

Objectif : conserver si possible **800–1000 blocks de marge**.

## 29.1 Ordre de réduction

1. ne pas charger S13 ;
2. raccourcir les tails Crash3/Splash/China ;
3. réduire les tails Crash1/2 avant de retirer leurs velocity layers ;
4. réduire légèrement S07 avant S06 ;
5. réduire S05 avant S02 ;
6. supprimer S12 ou S11 et utiliser S02 V3/V2 ;
7. conserver S10 : ses samples courts coûtent peu et le pad Stack doit rester fonctionnel ;
8. préserver au maximum S02, S06, Crash1 et Crash2.

---

# 30. Scenes / Logical Programs

Une Scene définit le style global et les valeurs par défaut de VP1–VP4. Elle n'a pas besoin de correspondre 1:1 à un Program DDrum4 natif.

| Scene | Base logique |
|---|---|
| **P01 Metalcore Core** | 4 toms, Snare1 MC premium, cymbales full acoustic, Stack acoustic |
| **P02 Metalcore Dual** | Snare1 MC + Snare2 MC/alt |
| **P03 Metalcore + Deftones** | Snare1 MC + Snare2 Deftones |
| **P04 Metalcore + Sleep** | Snare1 MC + Snare2 Sleep |
| **P05 Sleep Token** | Kick/toms plus profonds, snare Sleep, hybrid percs |
| **P06 Deftones** | snare Deftones, kit plus ouvert/organique |
| **P07 DnB Classic** | kick DnB, e-snare, e-HH, Glitch/Click |
| **P08 DnB Hybrid** | électronique + cymbales/toms acoustiques conservés |
| **P09 Industrial Metal** | acoustique lourd + e-snare/metallic percs |
| **P10 Industrial Electronic** | remaps métalliques/glitch plus importants |
| **P11 Trap** | 808, e-HH, Clap/Rim |
| **P12 Dance/Chill** | e-kick, hats, Cowbell/Woodblock/Clap |
| **P13 Utility Acoustic** | acoustique + accès Cowbell/Woodblock |

Il peut exister beaucoup plus de Scenes dans Arduino/Converter que de Programs DDrum4 réellement nécessaires. Le DDrum4 renderer peut réutiliser un même Program natif et ne changer que des Variations/Sounds/Palettes.

---

# 31. Virtual Palettes : Snare et slot Flex

## 31.1 VP1 — Snare1

| Valeur | Identité logique |
|---:|---|
| **1** | Metalcore premium |
| **2** | Deftones premium/FULL |
| **3** | Sleep premium/FULL |
| **4** | Industrial |
| **5** | Electro/DnB |

## 31.2 VP2 — Tom4/Snare2

| Valeur | Identité logique |
|---:|---|
| **1** | Tom4 |
| **2** | Snare2 Metalcore |
| **3** | Snare2 Deftones |
| **4** | Snare2 Sleep |
| **5** | Snare2 electronic selon Scene |

`VP1 × VP2` produit donc **25 combinaisons**.

Le `Snare Resolver` d'Arduino choisit automatiquement la meilleure implémentation :

1. Sound FULL résident si demandé et disponible ;
2. S02 premium Variation sur un channel libre ;
3. S05 compact/electronic en fallback.

Le SD3 Renderer n'a pas cette contrainte : il route simplement vers la vraie destination du mega-kit.

---

# 32. Virtual Palettes : percussions et surfaces

## 32.1 VP3 — famille

| VP3 | Famille |
|---:|---|
| **1** | Acoustic |
| **2** | Hybrid / Sleep / Modern Metal |
| **3** | Drum'n'Bass |
| **4** | Industrial |
| **5** | Trap / Electro |

## 32.2 VP4 — variante dans la famille

VP4 vaut 1–5 à l'intérieur de VP3, soit **25 layouts de surfaces** au lieu de 5 + 5 choix indépendants.

### VP3 = 1 — Acoustic

| VP4 | Layout | Stack | Perc | Cymbales auxiliaires |
|---:|---|---|---|---|
| **1** | Full Acoustic | **Stack** | libre/none | toutes acoustiques |
| **2** | Cowbell | **Stack** | **Cowbell** | toutes acoustiques |
| **3** | Woodblock | **Stack** | **Woodblock** | toutes acoustiques |
| **4** | Click Utility | **Stack** | Click/Rim | toutes acoustiques |
| **5** | Acoustic + Clap | **Stack** | Clap | toutes acoustiques |

### VP3 = 2 — Hybrid / Sleep / Modern Metal

| VP4 | Layout | Stack | Perc | Remaps secondaires |
|---:|---|---|---|---|
| 1 | Sleep Subtle | Stack | Low e-tom | presque tout acoustique |
| 2 | Sleep Heavy | Impact dérivé e-tom | Clap | China2/Crash3 peuvent devenir FX |
| 3 | Modern Hybrid | Stack | Clap | Splash2 → Click |
| 4 | Breakdown FX | Impact | Glitch | Splash/China/Crash3 → FX |
| 5 | Hybrid Hats | Stack | Click | Splash1/2 → e-HH Closed/Open |

### VP3 = 3 — Drum'n'Bass

| VP4 | Layout | Stack | Perc | Remaps secondaires |
|---:|---|---|---|---|
| 1 | Classic DnB | Glitch | Click | Splash1/2 → e-HH ; China1 → e-tom |
| 2 | Neuro | Metallic | Glitch | plus de pads → Noise/Metal |
| 3 | Liquid | Stack | Cowbell | davantage de cymbales acoustiques |
| 4 | Halftime | Low e-tom/Impact | Clap | moins de hats remappés |
| 5 | Dense Electronic | Glitch | Woodblock/Click | presque toutes les secondaires → percs |

### VP3 = 4 — Industrial

| VP4 | Layout | Stack | Perc | Remaps secondaires |
|---:|---|---|---|---|
| 1 | Metallic | Metallic Hit | Glitch | Chinas → Metal/e-tom |
| 2 | Mechanical | Click/Metal | Woodblock | Splashes → Click/Noise |
| 3 | Heavy Breakdown | Low e-tom/Impact | Metallic | China2/Crash3 → Impact/Metal |
| 4 | Industrial Metal | Stack | Metallic | Crash1/2/Ride acoustiques |
| 5 | Maximum Industrial | Glitch | Low e-tom | nombreux pads → FX |

### VP3 = 5 — Trap / Electro

| VP4 | Layout | Stack | Perc | Remaps secondaires |
|---:|---|---|---|---|
| 1 | Basic Trap | Clap | Click/Rim | Splash1/2 → e-HH |
| 2 | Hat Roll | E-HH Closed | Click | plusieurs pads doublent Closed HH |
| 3 | Open Hat / Clap | Clap | E-HH Open | Chinas → Cowbell/Woodblock |
| 4 | 808 Breakdown | Low e-tom/Impact | Clap | cymbales acoustiques minimales |
| 5 | Metal-Trap | Stack | Clap | Crash1/2 + Stack acoustiques |

---

# 33. Vue synthétique du remapping des surfaces

| Pad | Acoustic/Metalcore | Hybrid/Sleep | DnB | Industrial | Trap |
|---|---|---|---|---|---|
| Crash1 | Crash HQ | Crash HQ | Crash HQ | Crash HQ | Crash/Accent |
| Crash2 | Crash HQ | Crash HQ | Crash/FX | Crash HQ | Crash/FX |
| Crash3 | Crash | Crash/FX | Glitch/Stack | Trash/Metal | Impact/Stack |
| Splash1 | Splash | Click/e-HH | E-HH Closed | Glitch | E-HH Closed |
| Splash2 | Splash | E-HH/FX | E-HH Open | Click/Metal | E-HH Open |
| China1 | China | China/Impact | Low e-tom | Metallic | Cowbell/Clap |
| China2 | China | China/FX | Glitch/Woodblock | Industrial Hit | Woodblock/Rim |
| Ride | Ride | Ride | Ride/Click | Ride/Metal | Click/FX |
| **Stack** | **Acoustic Stack** | Stack/Impact | Glitch/e-tom/Stack | Metallic/Impact/Stack | Clap/HH/Stack |
| **Perc** | Utility/Cowbell/Woodblock | Low e-tom/Clap | Click/Clap | Metal/Glitch | Rim/Click/Clap |

Crash1 et Crash2 restent les deux surfaces acoustiques les plus protégées.

---
# 34. MIDI Map A — namespace des événements physiques

La table la plus stable n'est pas une table de notes : c'est une liste d'**IDs physiques**.

| Physical ID | Signification |
|---|---|
| `kick.hit` | Kick |
| `tom1.hit` | Tom1 |
| `tom2.hit` | Tom2 |
| `tom3.hit` | Tom3 |
| `snare2.head` | Tom4/Snare2 head avec position |
| `snare2.rimshot` | Rim2 rimshot |
| `snare2.cross` | Rim2 cross-stick/rim |
| `snare1.head` | Snare1 head avec position |
| `snare1.rimshot` | Rim1 rimshot |
| `snare1.cross` | Rim1 cross-stick/rim |
| `hh.bow` | HH bow + opening |
| `hh.edge` | HH edge + opening |
| `hh.pedal_close` | Chick |
| `hh.pedal_splash` | Pedal splash |
| `splash1.hit` | Splash1 |
| `splash2.hit` | Splash2 |
| `ride.bow` | Ride bow |
| `ride.bell` | Ride bell |
| `crash1.bow` | Crash1 bow |
| `crash1.edge` | Crash1 edge |
| `crash2.bow` | Crash2 bow |
| `crash2.edge` | Crash2 edge |
| `crash3.edge` | Crash3 |
| `china1.edge` | China1 edge |
| `china1.bell` | China1 bell |
| `china2.edge` | China2 edge |
| `china2.bell` | China2 bell |
| `perc.hit` | Perc pad |
| `stack.hit` | Stack pad |

Les chokes sont attachés à l'ID de cymbale correspondant.

---

# 35. MIDI Map B — avant Arduino : `Raw Source Maps`

Chaque device possède sa propre table `raw MIDI → Physical ID`.

**Cette table ne change pas avec les Scenes.** Si un pad change de rôle musical, seule la couche `Scene Router` change.

## 35.1 eDRUMin

Le eDRUMin doit conserver le maximum d'expression. Les notes exactes peuvent être remappées ; une proposition de namespace simple est :

| Raw event CH_EDRUM | Physical ID | Information conservée |
|---|---|---|
| Note 0 | `snare1.head` | velocity + position continue/metadata |
| Note 1 | `snare1.rimshot` / `snare1.cross` | zone selon configuration |
| Note 2 | `hh.bow` | velocity + CC4 |
| Note 3 | `hh.edge` | velocity + CC4 |
| Note 4 | `hh.pedal_close` | velocity |
| Note 5 | `hh.pedal_splash` | velocity |
| **CC4** | `hh.opening` | **0–127 continu** |

Si eDRUMin encode la position de snare avec un autre message/CC ou plusieurs notes, le `Source Profile` traduit ce format vers `position=0..1`. Arduino peut ensuite quantifier en Center/Mid/Edge pour DDrum4, alors que le Converter peut garder une résolution supérieure pour SD3.

## 35.2 DDTi

Le DDTi peut être entièrement remappé. Pour simplifier le debug, on recommande une plage compacte et explicite sur `CH_DDTI`.

Exemple de mapping à adapter aux pads réellement branchés au DDTi :

| Raw note CH_DDTI | Physical ID proposé |
|---:|---|
| 16 | `splash1.hit` |
| 17 | `splash2.hit` |
| 18 | `ride.bow` |
| 19 | `ride.bell` |
| 20 | `crash1.bow` |
| 21 | `crash1.edge` |
| 22 | `crash2.bow` |
| 23 | `crash2.edge` |
| 24 | `crash3.edge` |
| 25 | `china1.edge` |
| 26 | `china1.bell` |
| 27 | `china2.edge` |
| 28 | `china2.bell` |
| 29 | `perc.hit` |
| 30 | `stack.hit` |
| 31 | réserve |

Les pads qui ne sont pas physiquement sur le DDTi sont simplement retirés de ce profile.

Les chokes/zone messages réels du DDTi doivent être normalisés par le profile sans imposer leur représentation au reste du système.

## 35.3 DDrum4 : Raw Trigger Map

Le DDrum4 utilise un seul channel MIDI global. Ses dix entrées physiques sont cependant faciles à identifier grâce au `NOTE #` de chaque channel.

Dans la configuration renderer proposée :

| Trigger/channel physique DDrum4 | Raw base note | Physical pad connecté |
|---|---:|---|
| KICK | 0 | **à renseigner selon câblage** |
| SNARE | 8 | **à renseigner** |
| RIM | 16 | **à renseigner** |
| TOM HIGH | 24 | **à renseigner** |
| TOM MID | 32 | **à renseigner** |
| TOM LOW | 40 | **à renseigner** |
| PERC | 48 | **à renseigner** |
| CYMBAL1 | 56 | **à renseigner** |
| CYMBAL2 | 64 | **à renseigner** |
| HI-HAT | 72 | **à renseigner** |

Cette table est la seule partie du `Source Profile DDrum4` à modifier si l'on recâble les pads sur d'autres trigger inputs.

Pour un pad positionnel branché au DDrum4, les offsets du bloc raw (`base + 0…7`) doivent être interprétés comme **position physique du hit**, et non comme l'articulation du Sound renderer actuellement chargé. Le Source Profile reconstruit donc d'abord `pad + position`, puis le Scene Router décide de la destination.

### Exemple important

Supposons que le pad physique `tom3` soit branché sur `TOM LOW`. Il émettra un raw hit dans le bloc 40–47.

```text
CH_DDRUM note 40
     ↓ Raw Source Map
physical = tom3.hit
```

Mais dans le **renderer DDrum4**, le même bloc 40–47 est actuellement assigné à `S07 HH_EDGE_PEDAL`.

Ce n'est pas une contradiction :

- `CH_DDRUM note 40` reçu depuis le bus brut = **entrée physique à décoder** ;
- `note 40` envoyé par Arduino au DDrum4 IN = **adresse renderer S07/P1**.

La direction et l'étape du pipeline donnent le sens.

---

# 36. MIDI Map C — `Logical Scene Router`

Cette table transforme `Physical ID + State` en `Logical Sound`.

Exemples :

| Physical ID | Metalcore | Sleep Hybrid | DnB | Industrial | Trap |
|---|---|---|---|---|---|
| `kick.hit` | MC Kick | Sleep Kick | DnB Kick | Industrial Kick | 808 Kick |
| `snare1.head` | VP1 Snare | VP1 Snare | VP1 Snare | VP1 Snare | VP1 Snare |
| `snare2.head` | Tom4 ou VP2 Snare | VP2 | VP2 | VP2 e-snare | VP2 e-snare |
| `stack.hit` | Acoustic Stack | Stack/Impact | Glitch | Metallic Hit | Clap/Stack |
| `perc.hit` | Utility | Low E-Tom/Clap | Click | Glitch/Metal | Click/Clap |
| `splash1.hit` | Splash | Splash/e-HH | E-HH Closed | Glitch | E-HH Closed |
| `china2.edge` | China | China/FX | Glitch/Woodblock | Industrial Hit | Woodblock/Rim |

Le Scene Router doit être **commun en données** entre Arduino et Midi Converter. Idéalement les deux applications chargent le même fichier de configuration généré par l'outil de gestion du kit.

---

# 37. MIDI Map D — Arduino → DDrum4 Renderer

Le renderer DDrum4 traduit un `Logical Sound` vers :

```text
DDrum channel + Sound + Variation + NOTE P + velocity + expression
```

Les notes suivantes sont proposées comme contrat stable.

## 37.1 S01 / KICK block 0–7

| Note | Destination |
|---:|---|
| 0 | S01 P1 Acoustic Kick |
| 1 | S01 P2 Acoustic Hard Alternate |
| 2 | S01 P3 DnB Kick |
| 3 | S01 P4 Industrial Kick |
| 4 | S01 P5 808/Trap Kick |
| 5 | S01 P6 Sub/Body |
| 6–7 | réserve |

La Variation active définit le caractère global du Sound.

## 37.2 S02 / SNARE block 8–15

| Note | Destination |
|---:|---|
| 8 | Center principal |
| 9 | Center Hard B |
| 10 | Center Hard C |
| 11 | Mid |
| 12 | Edge |
| 13–15 | réserve |

Arduino ne choisit 9/10 que dans les zones fortes où le RR est pertinent. La velocity originale reste inchangée.

## 37.3 S03 / RIM PAIR block 16–23

| Note | Destination |
|---:|---|
| 16 | Rimshot A principal |
| 17 | Rimshot A hard alternate |
| 18 | Cross-stick/Rim A |
| 19 | Rimshot B principal |
| 20 | Rimshot B hard alternate |
| 21 | Cross-stick/Rim B |
| 22–23 | réserve |

## 37.4 S04 / TOMS block 24–31

| Note | Destination |
|---:|---|
| 24 | Tom1 |
| 25 | Tom2 |
| 26 | Tom3 principal |
| 27 | Tom3 hard alternate |
| 28–31 | réserve |

## 37.5 S05 / FLEX block 32–39

| Note | Destination |
|---:|---|
| 32 | Tom4 |
| 33 | Snare2 Center |
| 34 | Snare2 Mid |
| 35 | Snare2 Edge |
| 36 | Snare2 Rimshot |
| 37 | Snare2 Cross-stick |
| 38 | DnB/Electro Snare |
| 39 | Industrial/Trap Snare |

Si le channel TOM MID charge S02, S11 ou S12 à la place de S05, la table de ce block est remplacée par la map NOTE P du Sound correspondant.

## 37.6 S07 / HH EDGE block 40–47

| Note | Destination |
|---:|---|
| 40 | Edge Closed |
| 41 | Edge 1/4 |
| 42 | Edge 1/2 |
| 43 | Edge Open |
| 44 | Pedal Close |
| 45 | Pedal Splash |
| 46–47 | réserve |

## 37.7 S10 / PERC block 48–55

| Note | Destination |
|---:|---|
| 48 | Acoustic Stack |
| 49 | Clap |
| 50 | E-HH Closed |
| 51 | E-HH Open |
| 52 | Click/Rim |
| 53 | Metallic Hit |
| 54 | Low E-Tom **ou Cowbell** selon Variation |
| 55 | Glitch **ou Woodblock** selon Variation |

## 37.8 S08 / CYMBAL1 block 56–63

| Note | Destination |
|---:|---|
| 56 | Crash1 Bow |
| 57 | Crash1 Edge |
| 58 | Splash partagé |
| 59 | China Edge partagé |
| 60 | China Bell partagé |
| 61 | Crash3 Edge |
| 62–63 | réserve |

## 37.9 S09 / CYMBAL2 block 64–71

| Note | Destination |
|---:|---|
| 64 | Crash2 Bow |
| 65 | Crash2 Edge |
| 66 | Ride Bow |
| 67 | Ride Bell |
| 68–71 | réserve |

## 37.10 S06 / HI-HAT block 72–79

| Note | Destination |
|---:|---|
| 72 | Bow Tight Closed |
| 73 | Bow Barely Open |
| 74 | Bow 1/4 Open |
| 75 | Bow 1/2 Open |
| 76 | Bow Open |
| 77–79 | réserve |

Arduino convertit le CC4 continu en l'un de ces cinq slots pour le DDrum4.

---

# 38. Chokes, position et expression dans le DDrum4 Renderer

## 38.1 Velocity

Toujours transmise sans réduction de résolution.

## 38.2 Snare position

La position continue/haute résolution devient :

```text
Center / Mid / Edge
```

puis NOTE P correspondant au Sound actif.

## 38.3 Hi-Hat

```text
CC4 continu
  ↓
5 zones Bow ou 4 zones Edge
  ↓
NOTE P DDrum4
```

Le CC original reste disponible sur le bus brut pour SD3.

## 38.4 Choke

Le Source Profile transforme le signal réel du pad/module en événement canonique `cymbal.choke`.

Le DDrum4 Renderer l'émet avec le mécanisme de choke/Aftertouch attendu par le channel cible ; le SD3 Renderer utilise indépendamment son articulation de mute/choke.

Le contrat `expression-routing` encode cette verticale comme
`poly_aftertouch` avec `note_from: active_rendered_hit`. Arduino et le
Converter PC utilisent alors le ledger borné de la frappe source (canal/note)
pour ne pas appliquer le choke à une Scene ou une palette sélectionnée après
la frappe. Le simulateur offline reproduit cette séquence (Note-On, changement
d'état, aftertouch) avec son propre ledger : il ne réévalue donc jamais la
nouvelle Scene pour un hit déjà joué. Aucun profil ne l'active sans trace
isolée mesurée.

---
# 39. MIDI Map E — vers SD3 : custom mega-kit

Comme le mega-kit SD3 est entièrement reconfigurable, la map peut être choisie pour être lisible et stable plutôt que compatible GM.

## 39.1 Kicks — notes 24–31

| Note SD3 | Logical Sound |
|---:|---|
| **24** | Metalcore Kick |
| **25** | Sleep Kick |
| **26** | DnB Kick |
| **27** | Industrial Kick |
| **28** | 808/Trap Kick |
| **29** | Hybrid/Sub Kick |
| 30–31 | réserve |

## 39.2 Snares — notes 32–55

| Note SD3 | Logical Sound |
|---:|---|
| **32** | Metalcore Snare Center |
| **33** | Metalcore Snare Mid |
| **34** | Metalcore Snare Edge |
| **35** | Metalcore Rimshot |
| **36** | Metalcore Cross-stick/Rim |
| **37** | Deftones Snare Center |
| **38** | Deftones Snare Mid |
| **39** | Deftones Snare Edge |
| **40** | Deftones Rimshot |
| **41** | Deftones Cross-stick/Rim |
| **42** | Sleep Snare Center |
| **43** | Sleep Snare Mid |
| **44** | Sleep Snare Edge |
| **45** | Sleep Rimshot |
| **46** | Sleep Cross-stick/Rim |
| **47** | DnB/Electro Snare |
| **48** | Industrial Snare |
| **49** | Trap/Electro Snare |
| **50** | Clap-as-snare |
| **51** | Electronic Rim/Click |
| 52–55 | snares futures / reserve |

## 39.3 Toms — notes 56–63

| Note SD3 | Logical Sound |
|---:|---|
| **56** | Tom1 Metalcore |
| **57** | Tom2 Metalcore |
| **58** | Tom3 Metalcore |
| **59** | Tom4 Metalcore |
| **60** | Tom1 Sleep/Low |
| **61** | Tom2 Sleep/Low |
| **62** | Tom3 Sleep/Low |
| **63** | Tom4 Sleep/Low |

Si les mêmes instruments SD3 suffisent avec un autre traitement déjà mixé, ces quatre dernières notes peuvent être réaffectées.

## 39.4 Hi-Hat — notes 64–71

| Note SD3 | Logical Sound |
|---:|---|
| **64** | Acoustic HH Tip/Bow — utilise CC4 continu |
| **65** | Acoustic HH Edge — utilise CC4 continu |
| **66** | HH Pedal Close |
| **67** | HH Pedal Splash |
| **68** | Electronic HH Closed |
| **69** | Electronic HH Open |
| **70** | Noise Hat / E-Ride |
| 71 | réserve |

## 39.5 Cymbales acoustiques — notes 72–87

| Note SD3 | Logical Sound |
|---:|---|
| **72** | Crash1 Bow |
| **73** | Crash1 Edge |
| **74** | Crash2 Bow |
| **75** | Crash2 Edge |
| **76** | Crash3 Edge |
| **77** | Splash1 |
| **78** | Splash2 |
| **79** | China1 Edge |
| **80** | China1 Bell |
| **81** | China2 Edge |
| **82** | China2 Bell |
| **83** | Ride Bow |
| **84** | Ride Bell |
| **85** | Acoustic Stack |
| **86** | E-China |
| **87** | E-Crash |

## 39.6 Percussions / électronique — notes 88–111

| Note SD3 | Logical Sound |
|---:|---|
| **88** | Metallic Hit |
| **89** | Glitch / Noise Hit |
| **90** | Low Electronic Tom |
| **91** | High Electronic Tom |
| **92** | Cowbell |
| **93** | Woodblock |
| **94** | Impact / Boom |
| **95** | Reverse / transition hit |
| **96** | Shaker |
| **97** | Tambourine |
| **98** | Noise Burst |
| **99** | Alternate Clap |
| 100–111 | electronic/future reserve |

## 39.7 Expansion — notes 112–127

Réservées aux futurs pads, stacks, FX ou articulations SD3 supplémentaires.

---

# 40. Conversion haute résolution vers SD3

Le SD3 Renderer doit utiliser les données **avant quantification DDrum4**.

## 40.1 Snare

```text
raw snare position
      ↓
SD3 positional articulation/position si possible
      ou
Center/Mid/Edge custom notes 32–34, 37–39, 42–44
```

Le DDrum4 peut se limiter à trois zones tandis que SD3 conserve plus d'information si le device source la fournit.

## 40.2 Hi-Hat

```text
HH Bow → Note 64 + CC4 original
HH Edge → Note 65 + CC4 original
Pedal   → 66/67
```

Le Converter ne doit jamais recevoir comme source de vérité les cinq ouvertures DDrum4 quantifiées si l'eDRUMin USB est disponible.

## 40.3 Chokes

Les chokes sont mappés vers les fonctions mute/choke de SD3 et ne dépendent pas du Sound DDrum4 utilisé.

---

# 41. DDrum4 Programs/Palettes natifs : rôle dans cette architecture

Les Programs et Palettes natifs sont des **outils du renderer DDrum4**, pas l'état logique principal.

Le module supporte notamment :

- Programs utilisateurs P1–P26 ;
- Programs factory F27–F99 ;
- quatre groupes de Palette : Kick, Snare, Toms, Percussion ;
- cinq valeurs par groupe.

Le protocole Program Change natif peut sélectionner :

| MPC | Fonction DDrum4 native |
|---:|---|
| 0–25 | P1–P26 |
| 26–98 | F27–F99 |
| 99 | Palette mode default |
| 100–104 | Kick Palette 1–5 |
| 105 | retour Kick au Kit |
| 106–110 | Snare Palette 1–5 |
| 111 | retour Snare au Kit |
| 112–116 | Toms Palette 1–5 |
| 117 | retour Toms au Kit |
| 118–122 | Percussion Palette 1–5 |
| 123 | retour Percussion au Kit |

Dans le projet, ces commandes peuvent être utilisées de deux façons :

1. **renderer command** : Arduino envoie les Program/Palette nécessaires pour matérialiser l'état ;
2. **physical control input** : un changement manuel sur le DDrum4 est décodé par Arduino/Converter comme une commande logique.

## 41.1 NativeControlMap

Exemple de convention possible :

```text
DDrum Program P1  → Scene Metalcore
DDrum Program P2  → Scene Sleep
DDrum Program P3  → Scene DnB
...

Native Snare Palette value → VP1
Native Toms Palette value  → VP2
Native Perc Palette value  → VP3 ou VP4 selon mode
```

La correspondance exacte peut être différente du comportement sonore natif du module. Arduino a le droit de recevoir la commande puis de **réconcilier** le DDrum4 vers la configuration complète correspondant à l'état logique.

---

# 42. Exemples de résolution complète

## 42.1 Metalcore standard

```text
Scene = P01 Metalcore Core
VP1 = 1 Metalcore
VP2 = 1 Tom4
VP3 = 1 Acoustic
VP4 = 1 Full Acoustic
```

DDrum4 :

```text
KICK   → S01 V1
SNARE  → S02 V1
RIM    → S03 V1 / Rim A
TOM-H  → S04 V1
TOM-M  → S05 V1 / Tom4
TOM-L  → S07
PERC   → S10 V1 / Stack + utilities
CYM1   → S08
CYM2   → S09
HH     → S06
```

SD3 :

```text
Kick       → 24
Snare      → 32–36
Toms       → 56–59
HH         → 64/65 + CC4
Stack      → 85
Cymbals    → 72–84
```

## 42.2 Metalcore + Deftones side snare sans S11

```text
Scene = Metalcore
VP1 = 1 Metalcore
VP2 = 3 Deftones
```

DDrum4 :

```text
SNARE  → S02 V1 Metalcore
TOM-M  → S02 V2 Deftones-like
RIM    → S03 V2 : A=Metalcore, B=Deftones
```

Le pad Tom4/Snare2 devient Snare2. Rim2 est routé vers Rim B.

SD3 :

```text
Snare1 → notes 32–36
Snare2 → notes 37–41
```

Ici SD3 utilise la **vraie Deftones snare**, même si le DDrum4 utilise seulement une Variation de S02.

## 42.3 Metalcore + Deftones FULL

DDrum4 :

```text
SNARE → S02 V1
RIM   → S03 Rim A
TOM-M → S11 FULL
```

Rim2 est envoyé directement aux positions Rimshot/Cross-stick de S11.

SD3 reste identique au cas précédent.

## 42.4 Sleep Token

```text
Scene = P05 Sleep Token
VP1 = 3 Sleep
VP2 = 1 Tom4 ou autre
VP3 = 2 Hybrid
VP4 = 1..5
```

DDrum4 :

```text
Kick  → S01 V2
Toms  → S04 V2
Snare → S12 FULL si disponible, sinon S02 V3
Perc  → S10 V2
```

SD3 :

```text
Kick 25
Snare 42–46
Toms 60–63
Hybrid percs 85 / 88–95 selon VP4
```

## 42.5 DnB

```text
Scene = P07 DnB
VP2 = 5 electronic
VP3 = 3
VP4 = 1 Classic DnB
```

DDrum4 :

```text
Kick   → S01 V3
Snare2 → S05 V4 / P7
Stack  → S10 Glitch
Perc   → S10 Click
Splash1/2 → S10 E-HH Closed/Open
China1 → S10 Low E-Tom
```

SD3 :

```text
Kick 26
Snare 47
E-HH 68/69
Glitch 89
Click 51 ou autre logical destination
Low E-Tom 90
```

## 42.6 Industrial Metal

```text
Scene = P09
VP3 = 4
VP4 = 4 Industrial Metal
```

Crash1/2/Ride restent acoustiques. Stack/Perc/Chinas peuvent devenir Metallic/Glitch/Impact.

## 42.7 Trap / Metal-Trap

```text
Scene = P11
VP3 = 5
VP4 = 5 Metal-Trap
```

Kick → 808, snares/clap électroniques, hats secondaires électroniques, mais Crash1/2 et Stack peuvent rester acoustiques.

---

# 43. Modes d'utilisation

## 43.1 Mode A — répétition/module-only

PC audio non nécessaire.

```text
Pads/modules → Drum Merger → Arduino → DDrum4 IN → DDrum4 audio ×4 → mixer
```

Fonctions disponibles :

- tous les remaps Arduino ;
- Scenes/VP via DDrum4 front panel ;
- DDrum4 8 MB comme unique renderer ;
- pas de dépendance SD3/USB audio.

Le hardware THRU peut rester connecté au PC sans conséquence.

## 43.2 Mode B — répétition/live SD3

```text
Raw MIDI → Arduino → DDrum4 renderer
        └→ Hardware THRU / USB → Midi Converter → SD3 renderer
```

Les deux moteurs sont actifs.

Configuration mixer recommandée :

- SD3 4-stems ouverts ;
- DDrum4 4-stems mutés mais prêts ;
- en cas de problème PC : mute SD3 / unmute DDrum4.

Le Logical State est identique pour les deux.

## 43.3 Mode C — live sans DDrum audio mais DDrum actif

On peut laisser Arduino continuer à alimenter le DDrum4 tout en gardant ses sorties audio mutées. Avantages :

- module toujours synchronisé ;
- fallback immédiat ;
- vérification visuelle/état conservé.

## 43.4 Mode D — enregistrement

Priorité : enregistrer **avant la décision sonore** autant que possible.

À conserver :

1. eDRUMin USB raw MIDI ;
2. DDTi USB raw MIDI ;
3. DDrum4 raw MIDI via UMC ;
4. messages de Scene/VP avec timestamps ;
5. sortie MIDI canonique vers SD3 ;
6. audio SD3 4-stems ;
7. éventuellement audio DDrum4 4-stems comme référence/fallback.

Le bénéfice est majeur : après la prise, on peut changer :

- Metalcore Snare → Deftones Snare ;
- Acoustic Stack → Glitch ;
- Tom4 → Snare2 ;
- scène entière ;

sans modifier le jeu enregistré.

Dans Ableton 12, SD3 peut être utilisé comme plugin avec le flux du Converter routé via un port MIDI virtuel ou une entrée dédiée. En standalone, le même contrat MIDI reste applicable.

---
# 44. Configuration par module / software

Cette section est conçue comme référence de câblage/configuration.

## 44.1 eDRUMin

### Câblage

```text
eDRUMin USB → PC
eDRUMin MIDI OUT → Drum Merger
```

### Configuration MIDI

- channel fixe `CH_EDRUM` ;
- notes brutes stables ;
- conserver velocity complète ;
- conserver CC4 continu du Hi-Hat ;
- conserver la meilleure information positionnelle possible pour Snare1 ;
- ne jamais appliquer les remaps de Scene dans eDRUMin.

Le eDRUMin est un **capteur/source**, pas un renderer de Scene.

## 44.2 DDTi

### Câblage

```text
DDTi USB → PC
DDTi MIDI OUT → Drum Merger
```

### Configuration

- channel fixe `CH_DDTI` ;
- notes stables pour chaque pad/zone ;
- velocity 1–127 conservée ;
- zones/chokes normalisés dans le Source Profile ;
- aucun remap de Scene dans le module.

## 44.3 DDrum4

### Câblage

```text
DDrum4 MIDI OUT → Drum Merger
Arduino MIDI OUT → DDrum4 MIDI IN
DDrum4 Audio OUT ×4 → mixer B1–B4
```

### MIDI/System

- `Local = Off` ;
- MIDI channel = `CH_DDRUM` ;
- Program/Control reception/transmission activée selon besoin ;
- Aftertouch/choke activé si requis ;
- `NOTE #` configurés selon les 10 blocs renderer ;
- `NOTE P` adapté aux Sounds, avec 8 notes réservées par bloc ;
- Programs/Palettes/Sounds préchargés ;
- 8 MB optimisés selon le budget du présent document.

### Audio

Configurer les quatre sorties utilisées pour respecter autant que possible le contrat : Kick / Snares / Toms / Cym+Perc.

## 44.4 Drum MIDI Merger

Entrées :

1. eDRUMin MIDI ;
2. DDTi MIDI ;
3. DDrum4 MIDI OUT.

Sortie actuelle : Arduino IN.

Sortie future : Master Merger.

## 44.5 Master MIDI Merger — évolution

Entrées :

1. sortie du Drum Merger ;
2. UMC404HD MIDI OUT ;
3. contrôleur externe MIDI OUT.

Sortie : Arduino IN.

Il devient le bus physique central des hits et commandes.

## 44.6 Arduino

### Entrée

Bus mergé brut.

### Sorties

```text
MIDI OUT → DDrum4 MIDI IN
Hardware THRU → UMC404HD MIDI IN
```

### Configuration logicielle

Doit charger au minimum :

- Source Profiles ;
- Physical IDs ;
- Scene definitions ;
- VP definitions ;
- Snare Resolver ;
- Percussion layouts ;
- DDrum4 Renderer Map ;
- NativeControlMap ;
- echo guard.

## 44.7 UMC404HD

### MIDI

```text
MIDI IN  ← Arduino hardware THRU
MIDI OUT → Master Merger (architecture future)
```

### Audio

```text
OUT1 → DRUM-1 KICK
OUT2 → DRUM-2 SNARES
OUT3 → DRUM-3 TOMS
OUT4 → DRUM-4 CYM/PERC
```

Les noms sont logiques ; le mixer doit retrouver les mêmes familles que pour l'audio DDrum4.

## 44.8 Midi Converter

Doit avoir des profiles de connexion :

### `LIVE_USB_PRIMARY`

```text
eDRUMin USB = ON
DDTi USB = ON
UMC CH_DDRUM = ON
UMC CH_EDRUM = OFF
UMC CH_DDTI = OFF
DDrum SysEx/Program parsing = ON
External MIDI = ON
```

### `DIN_ONLY`

```text
eDRUMin USB = OFF
DDTi USB = OFF
UMC CH_DDRUM = ON
UMC CH_EDRUM = ON
UMC CH_DDTI = ON
```

### Sortie

Un seul port MIDI canonique vers le renderer software choisi. Le lancement du
Converter sélectionne `DDRUM4_RENDERER_TARGET=sd3` ou `drumgizmo` et charge le
même `runtime-profile.yaml`.

Le header Arduino est dérivé uniquement d'un `firmware-project-mapping.json`
marqué `ready`, avec le canal MIDI DDrum4 mesuré fourni explicitement à la
génération. Les routes Scene/VP deviennent des `StateRoute` PROGMEM, les
observations `native_control_map` deviennent des `NativeControlRoute` PROGMEM,
et les CC VP de CH14/15 restent ceux du contrat. Une capture qui ne permet pas encore
d'abaisser CC4, Note P ou une expression au firmware fait échouer la génération
plutôt que d'inventer une règle.

## 44.9 SD3

- un seul mega-kit ;
- toutes les destinations présentes simultanément ;
- custom MIDI map §39 ;
- CC4 continu pour HH ;
- sorties 4-stems vers UMC ;
- aucun changement de preset requis pendant le live.

## 44.10 DrumGizmo

- un seul kit exporté et chargé pour la session ;
- `drumgizmo-midimap.json` compilé depuis le projet est consommé par
  `drum-sampler export-drumgizmo --note-map` ;
- le backend et la version sont déclarés dans le rapport de session ;
- ALSA/JACK et les ports MIDI/audio sont préflightés avant le live ;
- les expressions non validées par le kit restent des sacrifices déclarés,
  jamais des CC inventés par le Converter.

## 44.11 Contrôleur externe

### Actuellement

```text
External → MIDI4x4 / PC
```

Il peut piloter :

- click ;
- Scene ;
- VP ;
- autres contrôles software.

### Cible

```text
External → Master Merger
          ├→ Arduino
          └→ HW THRU → PC
```

Les commandes de Scene/VP doivent utiliser le protocole logique CH_EXT_CTRL. Le click reste une fonction PC : Arduino peut simplement ignorer cette commande tout en la laissant passer au THRU.

---

# 45. Gestion du click

Le click n'appartient ni au DDrum4 Renderer ni au SD3 mega-kit.

Il appartient à la couche PC/live host.

Flux recommandé :

```text
External click control
    ↓
Midi Converter / Ableton / host
    ↓
Click audio / cue
```

Dans l'architecture future où le message passe aussi par Arduino :

- Arduino reconnaît la classe `CLICK_CONTROL` ;
- il **ne la traduit pas en note DDrum4** ;
- le hardware THRU la laisse atteindre le PC ;
- le Converter/host la traite.

---

# 46. Procédure de démarrage recommandée

## 46.1 Module-only

1. allumer Merger(s), Arduino et DDrum4 ;
2. vérifier DDrum4 `L.Of` ;
3. charger/valider le Program logique par défaut ;
4. frapper un pad DDrum4 : vérifier `OUT → Arduino → IN → audio` ;
5. tester eDRUMin/DDTi ;
6. vérifier Snare1, HH, Stack ;
7. vérifier le changement de Scene depuis le panneau DDrum4.

## 46.2 Live/SD3

1. démarrer la chaîne hardware ci-dessus ;
2. démarrer PC + driver UMC ;
3. lancer Midi Converter ;
4. vérifier `LIVE_USB_PRIMARY` ;
5. lancer SD3/host avec mega-kit ;
6. vérifier que Converter et Arduino affichent la même Scene/VP ;
7. tester une frappe de chaque source ;
8. vérifier qu'aucun pad ne double ;
9. tester CC4 HH ;
10. tester choke ;
11. tester changement de Scene depuis DDrum4 ;
12. tester changement depuis contrôleur/PC si Master Merger installé ;
13. laisser DDrum4 audio prêt mais muté si SD3 est principal.

---

# 47. Tests de validation avant live

## 47.1 Test Local Off

- frapper un pad DDrum4 avec Arduino OUT débranché : **aucun son interne** ;
- rebrancher Arduino OUT : le son revient par la boucle.

## 47.2 Test raw/renderer separation

Choisir un pad DDrum4 dont la note raw est remappée vers un autre Sound dans une Scene.

Vérifier :

```text
UMC/Converter voit le physical hit original
DDrum4 joue le Sound transformé
SD3 joue le Logical Sound correspondant
```

## 47.3 Test double trigger

Pour eDRUMin et DDTi USB : vérifier que leurs copies DIN présentes dans UMC ne génèrent aucun second hit SD3.

## 47.4 Test echo DDrum4

Envoyer un hit transformé Arduino → DDrum4. Vérifier :

- pas de boucle hardware ;
- pas de second hit SD3 issu d'un éventuel echo DDrum4.

## 47.5 Test bidirectionnel de state

Tester séparément :

1. Program/Palette changé sur DDrum4 ;
2. Scene changée dans Converter ;
3. Scene changée par External Controller.

Dans chaque cas, Arduino + Converter + DDrum4 doivent converger vers le même état.

## 47.6 Test fallback

Pendant que SD3 joue :

1. muter/arrêter SD3 ;
2. ouvrir les quatre stems DDrum4 ;
3. vérifier qu'il n'y a aucun changement de mapping/pads nécessaire.

---

# 48. Stratégie d'enregistrement

Le format d'enregistrement idéal distingue :

## 48.1 Performance brute

- MIDI eDRUMin USB ;
- MIDI DDTi USB ;
- MIDI DDrum4 raw ;
- CC4 ;
- position/chokes ;
- commandes Scene/VP.

## 48.2 Performance logique

Optionnel mais très utile : enregistrer aussi les événements canoniques produits par le Converter :

```text
logical_sound_id
articulation
velocity
expression
state_id
```

Sous forme MIDI, cela correspond à la custom SD3 map.

## 48.3 Audio

- SD3 4-stems ;
- DDrum4 4-stems optionnels ;
- click séparé ;
- room/ambience SD3 gérée dans le mix du mega-kit/stems selon la configuration choisie.

## 48.4 Re-render après la prise

Comme le raw MIDI est conservé, il devient possible de :

```text
rejouer exactement la même prise
+ changer Scene/VP
+ re-render SD3
```

C'est particulièrement utile pour comparer Snare Metalcore / Deftones / Sleep sans rejouer la batterie.

---

# 49. Évolution : ajouter un pad

Procédure standard :

1. brancher le pad à eDRUMin, DDTi ou DDrum4 ;
2. créer un nouveau `Physical ID` ;
3. ajouter le raw mapping au `Source Profile` du device ;
4. définir son comportement par Scene/VP ;
5. ajouter ses destinations dans le DDrum4 Renderer si le module doit le jouer ;
6. ajouter une note SD3 si nécessaire ;
7. tester velocity/expression/choke ;
8. ne modifier aucun autre mapping si les abstractions sont respectées.

Si le DDrum4 n'a plus de slot renderer disponible, le nouveau pad peut rester **SD3-only** ou partager un Sound/NOTE P existant.

---

# 50. Évolution : ajouter un son

## 50.1 SD3

Simple :

1. ajouter l'instrument au mega-kit ;
2. lui attribuer une note libre 112–127 ou une note reserve ;
3. créer le `Logical Sound` ;
4. l'utiliser dans une Scene/VP.

## 50.2 DDrum4

Trois niveaux :

1. réutiliser un sample existant via une nouvelle Variation ;
2. ajouter le son dans S10/S05 si un layer peut être remplacé ;
3. ajouter un nouveau Sound résident si `MEM.LEFT` le permet et le charger dans certains Programs.

Le renderer SD3 peut être plus riche que le renderer DDrum4 sans casser la logique : les deux n'ont pas besoin d'avoir exactement les mêmes samples, seulement le même **Logical Sound ID**.

---

# 51. Évolution : ajouter une Scene

Une nouvelle Scene ne doit jamais nécessiter de modifier les Source Profiles.

Elle contient :

```text
scene_id
name
default_vp1
default_vp2
default_vp3
default_vp4
logical routing overrides
ddrum renderer state requirements
sd3 routing targets
```

Exemple futur : `Breakbeat`, `Deftones Full`, `Industrial Ambient`, `Electronic Chill`.

---

# 52. Modèle de configuration software recommandé

La configuration devrait être data-driven plutôt que codée en dur.

Exemple conceptuel :

```yaml
sources:
  edrumin:
    channel: 3
    map:
      note_0: snare1.head
      note_2: hh.bow
      cc_4: hh.opening

scenes:
  metalcore:
    defaults: {vp1: 1, vp2: 1, vp3: 1, vp4: 1}
  dnb:
    defaults: {vp1: 5, vp2: 5, vp3: 3, vp4: 1}

logical_routes:
  dnb:
    stack.hit: perc.glitch
    splash1.hit: perc.ehh_closed
  metalcore:
    snare1.head:
      - logical_target: snare.electronic.head
        when: {vp1_snare1: 1}
      - logical_target: snare.metalcore.head

renderers:
  ddrum4:
    perc.glitch: {sound: S10, variation: 3, note: 55}
  sd3:
    perc.glitch: {note: 89}
```

L'éditeur de kit envisagé peut générer ce fichier pour Arduino et le Converter afin d'éviter toute divergence.

---

# 53. Invariants à ne pas casser

1. **Le DDrum4 reste en Local Off.**
2. **Le hardware THRU reste brut.**
3. **Les Source Profiles ne dépendent pas des Scenes.**
4. **La velocity n'est jamais utilisée comme adresse d'articulation.**
5. **NOTE P est le mécanisme principal de multiplexage DDrum4.**
6. **Arduino et Converter utilisent le même Logical State.**
7. **SD3 reste un seul mega-kit.**
8. **Le PC choisit une seule source primaire par pad.**
9. **Les loops DDrum4 et PC sont traitées explicitement.**
10. **S10/Stack n'est pas sacrifié pour obtenir une deuxième snare high-end.**
11. **Les deux crashes principales, Snare premium et HH restent prioritaires dans la Flash.**
12. **Tout nouvel élément passe par Physical ID → Logical Sound → Renderer.**

---

# 54. Priorités de qualité DDrum4

Si des compromis sont nécessaires :

1. **S02 Snare premium** ;
2. **S06/S07 Hi-Hat** ;
3. **Crash1 + Crash2** ;
4. **S03 Rimshots** ;
5. **Toms 1–3** ;
6. **Ride** ;
7. **Kick acoustique** ;
8. **S05 Tom4/Snare2 compact** ;
9. cymbales secondaires ;
10. percussions électroniques courtes.

Cowbell, Woodblock, Clap, Click et Glitch coûtent peu et apportent beaucoup de diversité : les supprimer n'est généralement pas une bonne optimisation.

---

# 55. Résumé d'architecture

```text
                         ┌──────── eDRUMin USB ──────────────┐
                         ├──────── DDTi USB ─────────────────┤
                         │                                    ▼
PADS → MODULES → RAW MIDI BUS → HARDWARE THRU → MIDI CONVERTER → SD3 MEGA-KIT ou DrumGizmo KIT
                    │                         ▲                            │
                    │                         │                            ▼
                    ▼                         │                        AUDIO OUT
                 ARDUINO                     │
                    │                         │
          Logical State + DDrum Renderer      │
                    │                         │
                    ▼                         │
               DDrum4 MIDI IN                 │
                    │                         │
                    ▼                         │
             DDrum4 AUDIO ×4                  │
                                              │
                   State/controls bidirectionnels
```

Le système n'est donc pas « un mapping MIDI vers DDrum4 puis vers SD3 ».

Il s'agit de :

> **un bus MIDI brut partagé, un état logique synchronisé, puis un renderer hardware et un renderer software sélectionnable du même instrument virtuel.**

C'est cette séparation qui permet :

- le même jeu sur DDrum4, SD3 ou DrumGizmo ;
- le fallback live immédiat ;
- les Scenes/Virtual Palettes complexes ;
- les deux snares high-end ;
- les remaps de cymbales vers percussions ;
- l'enregistrement reconfigurable ;
- l'ajout futur de pads et de sons sans reconstruire le système.

---

# 56. Références techniques DDrum4

Les points suivants ont été revérifiés dans la documentation DDrum4 :

- `Local Off` déconnecte les trigger inputs des sons internes tout en continuant à transmettre le jeu en MIDI ;
- le DDrum4 utilise un channel MIDI global pour l'émission/réception ;
- `NOTE P` transmet 1, 2, 4 ou 8 notes consécutives pour représenter la position ;
- les Programs/Palettes peuvent être sélectionnés par MIDI Program Change ;
- les quatre groupes de Palette natifs sont Kick, Snare, Toms et Percussion ;
- les system settings comme NOTE#/NOTE P sont stockés par channel et ne changent pas avec le Kit/Palette ;
- `ddrum4UI` permet de construire des Sounds custom jusqu'à 10 samples, 10 layers et 10 variations.

Sources de référence :

- Clavia DDrum4 Owner's Manual : https://manualzz.com/doc/1326119/clavia-ddrum4-owner-s-manual
- DDrum4 manual — NOTE P : https://clavia.manymanuals.com/music-drums/ddrum4/owners-manual-6725/19
- ddrum4UI overview : https://www.vdrums.com/forum/advanced/vst-samples/1302153-ddrum4ui-becomes-a-midi-drum-software

---

# 57. Paramètres restant volontairement configurables

Le document fixe l'architecture, mais laisse volontairement certains paramètres dans les fichiers de configuration plutôt que de les graver dans le design :

- quels pads non-eDRUMin sont physiquement sur DDTi ou DDrum4 ;
- notes brutes exactes DDTi/eDRUMin si elles diffèrent des propositions ;
- format exact de la position eDRUMin ;
- représentation réelle des chokes par chaque source ;
- numéros CC exacts du protocole logique externe si les contrôleurs existants imposent autre chose ;
- affectation exacte des quatre sorties physiques DDrum4 ;
- taille réelle de chaque Sound après conversion ;
- choix définitif des samples S02/S11/S12 ;
- présence ou non de S11/S12 selon `MEM.LEFT`.

Ces paramètres n'affectent pas le fonctionnement général tant que les invariants du §53 sont respectés.
