# Roadmap multi-agent — prototype eDrum DDrum4 / SD3 / DrumGizmo

Statut : baseline hors ligne, configuration des modules, promotion configurée,
flash Uno et bootstrap matériel sans pads validés au 31 août 2026 ; validation
physique avec pads encore requise.

## Statut d'exécution

Le contrat `rig-project/v1`, le compilateur offline, le Converter, le bridge
firmware, le Control Center et les lanceurs Windows sont implémentés. Le
MegaKit SD3 v23 est approuvé et capturé (939 masters et 42 composites), et le
kit DrumGizmo r5 autonome est exporté (77 instruments, 1001 samples, 1018
fichiers). `dgvalidator` et DrumGizmo 0.9.20 l'ont chargé sous WSL, y compris
une preuve audio de choke. Les diagnostics hors ligne passent 5986/5986 et le
mapping complet tient sur Uno dans l'environnement non téléversable de
capacité (37,9 % Flash, 38,8 % RAM).

Le bootstrap matériel sans pads est désormais acquis : dump DDTi frais,
écriture/readback 42/42, snapshot eDRUMin, promotion configurée, flash Uno,
diagnostic 5986/5986 et audition 30/30 avec 60/60 événements au THRU. Cela ne
clôt pas le MVP : après branchement des pads, les 75 traces r10 doivent vérifier
strictement le contrat prescrit, puis viennent les campagnes de dynamique,
CC4/CC16, chokes, absence de doublons/boucles et latence. Seules ces mesures
peuvent promouvoir le profil de `post-flash-validation-pending` à
`hardware-verified` et autoriser le lanceur live.

Linux est une cible portable pour les messages MIDI des DDrum4, DDTi et
eDRUMin lorsque les backends ALSA/JACK ou équivalents et les périphériques USB
sont disponibles. SD3, ddrum4UI et ddrum4edit restent des prérequis Windows;
DrumGizmo remplace SD3 pour la validation audio Linux.

Une session Linux `renderer: drumgizmo` est déclarée dans
`profiles/live-session.drumgizmo.example.json` : elle démarre le Converter et
DrumGizmo, transmet le profil runtime et n'établit que les connexions JACK
explicitement enregistrées. Le chargement moteur et le choke audio sont
prouvés hors matériel ; le chemin depuis les vrais pads et sa latence restent
à mesurer sur le rig.

Document directeur : `architecture_finale_edrum_ddrum4_sd3.md`.

## 1. Décision de produit

Le dépôt n'est pas un projet neuf. Il contient déjà des briques fonctionnelles pour la capture, la construction de Sounds DDrum4, l'édition DDTi, l'export DrumGizmo, le routage MIDI C++ et le bridge Arduino. Le chemin court consiste à les faire converger autour d'un contrat de kit unique, puis à fournir un point d'entrée simple pour les utiliser.

Le prototype doit respecter cette chaîne :

```text
MIDI brut d'une source
  -> Physical Event stable
  -> Scene + VP1..VP4
  -> Logical Sound
  -> renderer DDrum4 ou renderer SD3/DrumGizmo
```

Le produit sera composé de deux processus, mais présenté depuis un seul lanceur :

- un moteur live C++/JUCE, seul dans le chemin MIDI temps réel ;
- un Control Center Python/PySide pour éditer, compiler, lancer les workflows et ouvrir les outils spécialisés.

Le Control Center génère les configurations et ouvre la vue Performance JUCE, qui reste l'unique propriétaire des ports, Scene/VP et du Panic live. Il ne route jamais les frappes en Python. Ce découpage fournit un point d'entrée unique sans dupliquer l'UI live ni introduire de jitter Python dans le jeu.

Le premier système officiellement supporté est Windows 11. Le moteur JUCE, les contrats et les exporteurs restent portables. Linux/ALSA/JACK vient après le MVP, essentiellement pour le Converter et DrumGizmo. Les transports MIDI USB/DIN des DDrum4, DDTi et eDRUMin restent portables lorsqu'un backend adapté est disponible; les outils propriétaires ddrum4UI/ddrum4edit et SD3 restent Windows.

« Zéro latence » signifie dans cette roadmap : aucune attente, allocation, journalisation synchrone ou mise en file évitable dans le chemin live. La latence physique ne peut pas être nulle ; elle doit être mesurée précisément, décomposée et tenue sous un budget explicite.

## 2. État de l'existant

| Besoin | Existant à réutiliser | Écart principal |
| --- | --- | --- |
| Domaine kit/profils | Contrat unique Physical → Logical → trois renderers, Scene/VP et expressions validées | Contrat configuré ; vérification fonctionnelle par les 75 traces r10 |
| Capture SD3 | Campagne v23 résumable, calibration, quality gates, 939 masters + 42 composites | Aucun écart hors nouvelle recapture décidée par l'utilisateur |
| Sons DDrum4 | Banque r15 encodée, transférée, auditionnée et documentée | Affectations physiques à revalider après promotion live |
| Converter live | Runtime multi-source Scene/VP, CC4/CC16, position, choke, contrôle logique et UI JUCE | Ports exacts et comportement DUAL à mesurer |
| Arduino | Tables compactes Scene/VP, commandes natives, HH et chokes ; profil configuré compilé, flashé et testé sans pads | Mesures physiques, comportement DUAL et echo guard actif à valider |
| DDTi | Éditeur intégré, dump/diff/staging sûr ; écriture et readback 42/42 vérifiés | Réglages électriques et frappes réelles à valider avec les pads |
| DrumGizmo | Kit r5 autonome et immuable, midimap, groupes HH/choke, validation et smoke moteur/audio | Jeu depuis pads et latence réelle à mesurer |
| SD3 | MegaKit v23 natif, MIDI maps custom/standard, calibration et capture complète | Session live depuis pads à valider |
| OS/live | Preflight fail-closed, réglages basse latence, lancement/arrêt, profil local configuré et rapports persistants | Promotion `hardware-verified` et rapport de session réel après essais pads |
| UI globale | Control Center PySide + Performance JUCE + DDTi Editor, compilation et workflows intégrés | Validation ergonomique finale pendant les essais pads |

Le 31 août, `scripts/test-all.ps1` passe : 229 tests Python partagés, 63 tests
Control Center, les tests firmware/DIN natifs et les tests Converter/runtime
C++. L'application JUCE Release et l'environnement AVR `uno_capacity` se
compilent également sans upload.

## 3. Périmètre du MVP

Le MVP est atteint lorsqu'un même projet permet les opérations suivantes sur la machine personnelle :

1. décrire le rig réel, ses sources, ses Physical Events et un namespace de Logical Sounds ;
2. générer les artefacts exécutables quand un backend validé existe, et sinon les packs, candidats, maps et checklists explicites, sans recopier manuellement les notes ;
3. jouer un kit Metalcore complet dans SD3 sous Windows avec toutes les sources prévues, HH continu, snare positionnelle et chokes ;
4. jouer le même kit logique, avec les sacrifices de renderer déclarés, sur DDrum4 en standalone avec Local Off et le bridge Arduino ;
5. démontrer au moins une Scene alternative électronique et les changements VP essentiels ;
6. inventorier la couverture des captures SD3 existantes, recapturer les articulations manquantes/rejetées et disposer d'une recette complète résumable ;
7. reconstruire les Sounds DDrum4 du kit depuis la bibliothèque et produire un pack contrôlé ;
8. exporter et charger réellement un kit DrumGizmo ;
9. sauvegarder, comparer et mettre à jour les champs DDTi déjà validés ;
10. démarrer une session live depuis un lanceur unique et obtenir un rapport de santé et de latence.

Le MVP n'inclut pas :

- un DAW, un moteur audio, un séquenceur ou un éditeur MIDI générique ;
- un éditeur SD3 générique : le générateur actuel reste borné aux structures
  et presets sources validés par hash ;
- l'automatisation souris/clavier de DDrum4UI ;
- un éditeur complet de tous les SysEx DDrum4 ;
- l'auto-calibration des pads ou la reconstruction sophistiquée d'un rimshot mal détecté par le module ;
- le support de périphériques arbitraires ou le packaging Linux complet ;
- une UI « 128 notes » exhaustive avant que le flux vertical soit fonctionnel.

Pour SD3, le workflow génère le preset MegaKit, sa MIDI map, sa recette et sa
checklist à partir de sources validées par hash. Le chargement dans SD3 et
l'approbation auditive restent des actions utilisateur ; la v23 courante a
franchi ces deux gates.

Prérequis externes suivis dans le `project-report` : Master Merger pour le contrôle dual bidirectionnel ; loopMIDI ou Windows MIDI Services ; UMC404HD, driver et buffer déclaré ; chemin du host/SD3 et mega-kit confirmé ; version/backend DrumGizmo ; versions locales DDrum4UI/ddrum4edit ; racines de samples externes, hashes et licences. Aucun de ces assets locaux n'est copié dans Git. Le bundle partageable reste lui aussi sans asset privé ; une archive personnelle distincte peut embarquer explicitement le preset SD3 utilisateur et le kit DrumGizmo dérivé, avec manifeste `redistribution: prohibited`, uniquement pour migrer vers le laptop du propriétaire.

## 4. Modes live et gate de sécurité

Les documents du dépôt ne permettent pas encore de déclarer sûr le mode dual
final. Le firmware contient l'echo guard borné et ses tests natifs, mais le
profil flashé le laisse volontairement désactivé. Des documents signalent un
écho/round-trip observé dans certaines configurations ; le comportement propre
du DDrum4 doit être reproduit et quantifié sur un banc isolé avant d'activer le
guard et d'ouvrir le mode `DUAL`. Le probe borné
`scripts/probe-ddrum4-soft-through.ps1` matérialise ce gate : 100 Note On, 100
releases zéro-vélocité et 100 poly-aftertouch, rapport JSON, double confirmation
et Arduino OUT physiquement débranché.

Le prototype est livré par paliers :

| Mode | DDrum4 | Arduino | Renderer | Usage |
| --- | --- | --- | --- | --- |
| `BENCH_PC_LOCAL_ON` | Local On | Silent | SD3/DrumGizmo | Diagnostic seulement ; audio DDrum4 muté au mixer |
| `STANDALONE` | Local Off | Nested | DDrum4 | Répétition sans PC audio |
| `DUAL` | Local Off | Nested ; PC sur THRU matériel brut | SD3 et DDrum4 | Seul mode live PC final, ouvert après le gate DIN |

Le gate DIN utilise un banc isolé : sonde -> DDrum4 IN et DDrum4 OUT -> capture indépendante, sans retour PC, loopMIDI ou Arduino vers DDrum4 IN. Il émet Note On, Note On vélocité zéro et poly-aftertouch au repos, en répétition et en rafale. L'absence d'écho pendant un seul run ne suffit pas à ouvrir `DUAL`.

Si un retour est systématique et discriminable, le renderer préfère d'abord un namespace de notes distinct du raw. Le filtre éventuel est ensuite strictement causal : FIFO unitaire d'événements réellement émis, expiration fondée sur la fenêtre aller-retour mesurée, limitée à `CH_DDRUM` et au mode `DUAL`. Les flams/rolls au débit maximal déclaré doivent donner zéro faux positif sur la matrice testée. Si frappe réelle et retour restent indiscernables, `DUAL` reste fermé plutôt que de risquer d'avaler une frappe.

Avant tout bus live contenant du SysEx, le parser DIN doit aussi prouver qu'un SysEx ou System Common intercalé annule correctement le running status et ne produit aucun faux hit.

Le second Master Merger reste nécessaire pour une synchronisation bidirectionnelle propre des commandes PC/contrôleur vers Arduino. Avant son installation, seuls les changements initiés depuis le DDrum4 sont déclarés globaux ; les commandes UI sont désactivées ou marquées `SD3-only`. Après installation, la convergence Arduino + Converter + DDrum4 est mesurée séparément pour une commande DDrum4, PC et contrôleur.

## 5. Contrat de projet unique

Le lot le plus important est un `rig-project/v1` validé par JSON Schema. Il ne remplace pas immédiatement tous les anciens documents : il les référence ou les compile, puis devient l'unique source d'autorité du runtime.

Structure minimale ; les endpoints et notes ci-dessous sont des placeholders tant que M0 ne les a pas mesurés :

```yaml
project: greg-hybrid
rig: profiles/physical/greg-hybrid-kit.yaml

sources:
  edrumin: { endpoint: "MEASURE_ME", channel: 3, primary: usb }
  ddti:    { endpoint: "MEASURE_ME", channel: 2, primary: usb }
  ddrum4:  { endpoint: "MEASURE_ME", channel: 1, primary: din_bus }

source_decoders:
  - match: { source: edrumin, type: note, note: 0 }
    emit: { physical: snare1.head, expressions: [velocity, position] }
  - match: { source: edrumin, type: cc, cc: 4 }
    emit: { physical: hh.opening, normalize: cc7 }
  - match: { source: ddti, type: poly_aftertouch, active_note: true }
    emit: { physical: cymbal.choke, correlate: source_channel_note }

physical_events: [snare1.head, hh.bow, hh.opening, cymbal.choke]

state:
  scenes: [metalcore, electronic]
  variables: [vp1_snare1, vp2_flex, vp3_family, vp4_variant]
  defaults: { scene: metalcore, vp1_snare1: 0, vp2_flex: 0, vp3_family: 0, vp4_variant: 0 }

logical_control_protocol:
  scene: { channels: [14, 15], type: program_change }
  vp1_snare1: { channels: [14, 15], type: cc, cc: 20 }

connection_profiles:
  LIVE_USB_PRIMARY: { deduplicate_din_copies: true }
  DIN_ONLY: { usb_sources: false }

logical_routes:
  metalcore:
    snare1.head:
      - logical_target: snare.metalcore.alt
        when: {vp1_snare1: 1}
      - logical_target: snare.metalcore.head # fallback obligatoire
    stack.hit: perc.acoustic_stack
  electronic:
    stack.hit: perc.glitch

renderers:
  ddrum4:
    snare.metalcore.head: { note: 8, position_policy: snare_3_zone }
  sd3:
    snare.metalcore.head: { note: 32, position_cc: 16 }

native_control_map:
  ddrum4_program_change: { decode_to: scene }

policies:
  echo: measured_only
  unknown_message: drop_and_count
```

Le compilateur doit produire des artefacts résolus et hashés :

```text
build/generated/<project>/
  project-report.json
  runtime-profile.yaml             # Converter C++
  firmware_mapping.h               # Uno, tables précompilées
  ddrum4-routing-contract.json
  ddrum4-bank-plan.json
  ddti-configuration-preset.yaml    # seulement avec --base-dump
  sd3-megakit-map.md
  sd3-midimap.json
  drumgizmo-midimap.json
```

Tous les artefacts contrôlés par la toolchain embarquent le même hash. Le Converter expose le hash actif. Le firmware contient un build ID/hash tronqué consultable dans le rapport de build ou une cible diagnostic, sans utiliser le Serial partagé avec le DIN en production. Les états DDTi/DDrum4 et le mega-kit SD3 sont associés au projet par manifest, hash de fichier, receipt/readback ou validation manuelle ; la roadmap ne suppose pas que ces systèmes acceptent une métadonnée arbitraire.

Le `project-report.json` marque chaque cible `ready`, `planned`, `unresolved` ou `user-confirmed`. Les sentinelles explicites `MEASURE_ME_*`, jamais la valeur MIDI valide `0`, gardent les artefacts dépendants en `planned`. Sans golden dump, le preset DDTi reste `unresolved`. Sans bibliothèque/catalogue, le bank plan DDrum4 reste `planned`. Le mapping SD3 et l'affectation finale Program/Palette restent `user-confirmed` au MVP.

Validations bloquantes : collisions source, notes hors plage, Physical Event sans route, Logical Sound sans renderer requis, expression incompatible, block NOTE P dépassé, source primaire ambiguë, conflit DDTi, mapping DrumGizmo non injectif et référence manquante. Le validateur impose aussi : Source Profile indépendant de Scene ; velocity jamais utilisée comme adresse d'articulation ; séparation raw/renderer exigée par la politique d'écho ; commandes natives distinctes de CH14/15 ; SysEx channel-less ; couverture Note Off/aftertouch ; defaults VP déterministes ; budget flash/PROGMEM/SRAM et marge de pile Uno.

Sur Arduino Uno, « charger une config » signifie pour le MVP : compiler plusieurs Scenes/VP en tables PROGMEM, générer le header et flasher. Le changement de Scene en jeu est instantané et ne lit ni SD ni YAML. Le chargement SD/EEPROM à chaud est reporté ; il augmente les risques sans améliorer le jeu.

## 6. Banc de mesure de latence

La latence est une fonctionnalité du produit. `tools/midi-lab` est d'abord étendu, puis un petit `tools/latency-lab` et `contracts/schemas/latency-run.schema.json` conservent les mesures brutes, le câblage, les versions, la configuration ASIO déclarée, le sample rate, le buffer, le profil et les statistiques. La baseline DDrum4 + SD3 au buffer live est un gate MVP ; la matrice exhaustive est un lot M8 et ne bloque pas le premier vertical.

### 6.1 Instants et segments

Pour ne pas attribuer la sérialisation DIN au code de routage, on distingue :

```text
t0_wire     premier start bit du message MIDI source, ou marqueur GPIO calibré
t1_wire     premier start bit reçu par le routeur
t1_ready    dernier octet reçu ; événement complet disponible
t2          décision de routage terminée
t3_enqueue  appel/écriture dans l'API de sortie
t3_wire     premier start bit réellement émis par la sortie
t4_ready    dernier octet reçu par le renderer
t5          début analogique du signal audio du renderer, si observable
t6          début du signal audio enregistré par l'interface commune
```

Les métriques publiées sont :

- entrée/transport : `t1_ready - t0_wire` ;
- cœur : `t2 - t1_ready` ;
- attente callback/driver/UART : `t3_wire - t2`, avec `t3_enqueue` conservé séparément ;
- sortie/transport : `t4_ready - t3_wire` ;
- renderer : `t5 - t4_ready` uniquement sur un banc partageant une référence fiable ;
- mesure headline « MIDI émis -> son capturé » : `t6 - t0_wire` ; une estimation de `t5 - t0_wire` ne soustrait le délai DAC/ADC que si la boucle UMC a été calibrée de façon répétable ;
- p50, p95, p99, maximum, écart-type, jitter p99-p50, pertes, doublons et ordre ;
- résultats par source, renderer, Scene, événement, buffer audio et charge système.

Des timestamps pris sur deux horloges non synchronisées ne sont jamais soustraits ni additionnés. `sendMessageNow()` et `Serial.write()` mesurent une mise en file, pas le début physique d'émission ; `t3_wire` vient du TX observé au logic analyzer.

### 6.2 Sonde et câblage de référence

Une sonde Teensy USB-MIDI/DIN dédiée émet une séquence déterministe et fournit un GPIO corrélé au TX réel. Si le GPIO précède le premier start bit, l'offset GPIO -> `t0_wire` est mesuré et publié. Un Uno classique ne sert pas de source USB-MIDI native.

Le front GPIO est observé au logic analyzer ou envoyé vers une entrée audio uniquement au travers d'une adaptation de niveau/protection documentée. Le signal audio du renderer et le marqueur sont enregistrés par la même UMC404HD :

```text
Sonde MIDI OUT -> chemin testé -> renderer MIDI IN
Sonde GPIO     -> UMC entrée 1, via adaptation protégée
Renderer audio -> UMC entrées 3/4
```

Pour DDrum4, on capture DDrum4 OUT. Pour SD3, une paire UMC indépendante est rebouclée vers UMC IN 3/4, ou un loopback calibré est utilisé. La disponibilité indépendante des sorties, le direct monitoring et toute boucle audio sont vérifiés avant la mesure. Le délai DAC -> ADC est mesuré séparément et n'est soustrait que si sa dispersion le permet.

Le stimulus de référence est le click B0 ou un click court sans room, humanisation ni attaque lente. Une seconde campagne utilise les vrais sons du kit afin de quantifier leur pré-silence et leur attaque perceptive. Une mesure optionnelle « pad -> son » ajoute un capteur piezo/contact indépendant ; elle reste séparée de « MIDI émis -> son ».

### 6.3 Instrumentation

- Converter : build Release, horloge monotone aux points callback reçu, fin du core et appel de sortie ; ring buffer fixe, export par worker après le run.
- Firmware : pins de debug réservées par une cible de build, après vérification des conflits shield/LED/SPI ; aucune log Serial pendant la mesure.
- MIDI DIN : logic analyzer TX/RX. Un message de trois octets à 31,25 kbit/s prend environ 0,96 ms ; deux messages de trois octets successifs représentent environ 1,92 ms, hors merger/files UART. Chaque message de sortie supplémentaire ajoute environ 0,96 ms.
- USB MIDI : sonde USB native ou injecteur Windows séparé, séquences note/vélocité uniques et compteurs ; aucun timestamp API seul n'est présenté comme instant physique.
- Audio : enregistrement multicanal unique, calibration loopback et onset reproductible.

Le WAV brut est toujours conservé. L'onset automatique utilise une enveloppe et un seuil relatif au bruit dont paramètres et version sont inscrits dans le rapport ; les runs de référence sont vérifiés visuellement. Les outliers ne sont jamais supprimés sans être comptés et justifiés.

### 6.4 Campagnes MVP et complète

Le MVP mesure 1 000 événements espacés sur les deux chemins prioritaires, au buffer réellement retenu pour le live :

| Chemin MVP | Résultat |
| --- | --- |
| Sonde -> DDrum4 direct, puis sonde -> Arduino -> DDrum4 | baseline renderer et coût bridge |
| Sonde USB/DIN -> Converter -> port virtuel -> SD3 | chemin PC final |

M8 étend ensuite la matrice à `DIN_ONLY`, DrumGizmo et `DUAL`, puis aux buffers 32/64/128/256 quand disponibles, à vide et sous charge. Chaque configuration reçoit 1 000 événements ; un soak de dix minutes est réservé aux configurations représentatives et au pire cas de chaque renderer, pas répété sur toute la matrice.

L'enveloppe de charge est déclarée. Le DIN plafonne théoriquement à environ 1 041 messages/s de trois octets sans running status ; une transformation 1 -> 2 réduit fortement le débit soutenable. Les tests de surcharge sont séparés, comptent les drops et ne redéfinissent pas le débit nominal.

### 6.5 Budgets et régressions

Le budget de conception du seul `converter-core` Release est p99 < 100 microsecondes, sans allocation ni attente. Le callback -> appel sortie a sa propre baseline, car le backend Windows peut dominer. Les budgets end-to-end sont gelés après trois runs matériels comparables, pas inventés avant mesure.

Pertes, doublons, boucle ou ordre incorrect dans l'enveloppe nominale sont bloquants dès le premier run. Une hausse end-to-end de 0,5 ms ou 25 % au p99 déclenche d'abord une alerte ; elle devient bloquante seulement si trois runs comparables dépassent la dispersion de la baseline. Le cœur échoue toujours s'il dépasse son plafond absolu, même si la variation relative paraît faible.

Le lanceur ouvre le dernier rapport compatible et avertit quand buffer, driver, profil, câblage ou hash rendent la comparaison invalide.

## 7. Lots de travail

### M0 — Baseline reproductible et preuve DIN

Propriétaires : agent Validation/bench + intégrateur.

Travail :

- créer un environnement Python 3.12 propre, installer le workspace et `-e 'apps/ddti[api,gui]'` ;
- faire passer `scripts/test-all.ps1`, vérifier qu'il exécute aussi `tests/python/test_ddti.py`, puis écrire une nouvelle baseline ;
- corriger et tester en priorité `SysEx intercalé -> aucun faux hit/running status résiduel` dans le parser DIN ;
- capturer le rig réel : notes, channels, CC4, position, aftertouch, PC et zones ;
- réaliser le gate DDrum4 IN -> OUT décrit en section 4 ;
- étendre `midi-lab` pour une première baseline DDrum4 direct et conserver le format de rapport de latence ;
- créer de nouveaux profils `measured` à côté des templates, sans transformer une hypothèse en fait.

Sortie : tests verts, traces brutes, décision `DUAL`, câblage de mesure documenté et première baseline DDrum4/SD3. La sonde complète et la grande matrice restent dans M8.

### M1 — Contrat central et compilateur multi-target

Propriétaire : agent Domaine/Compiler.

Travail :

- ajouter le schema `rig-project/v1` et les modèles Python ;
- migrer un projet minimal Metalcore + Electronic ;
- compiler les artefacts de la section 5 avec un hash partagé ;
- adapter le bank builder et le générateur firmware sans maintenir un deuxième modèle ;
- ajouter une commande `drum-toolchain validate|compile|report` ;
- écrire un unique golden test projet -> artefacts.

Sortie : changer un Logical Sound ou une note régénère tous les artefacts prêts et marque explicitement les autres `planned/unresolved/user-confirmed` ; les collisions échouent avec un message actionnable.

### M2 — Converter live multi-source

Propriétaire : agent C++/Realtime.

Travail :

- séparer `converter-core`, `midi-runtime`, `state-manager` et UI sans changer de framework ;
- ouvrir simultanément les trois sources nécessaires eDRUMin USB, DDTi USB et UMC ; le contrôleur attend le Master Merger ;
- identifier la source par endpoint + channel et appliquer `LIVE_USB_PRIMARY`/`DIN_ONLY` ;
- appliquer la politique de source primaire avant une file bornée, horodater localement et traiter dans l'ordre d'arrivée sans prétendre synchroniser les horloges des devices ;
- sérialiser les callbacks multi-port vers un unique thread de traitement temps réel par une file MPSC bornée, ou prouver une alternative sans data race sur le ledger ;
- implémenter Source -> Physical -> State -> Logical -> SD3 ;
- publier Scene + VP1..VP4 comme un snapshot immuable remplacé atomiquement, avec commandes CH14/15 idempotentes ;
- préserver la résolution MIDI native 7 bits de position, CC4 et poly-aftertouch/choke ;
- ajouter l'echo guard uniquement sur `CH_DDRUM` en `DUAL` et selon M0 ;
- intégrer les points de mesure et compteurs drops/duplicates/unknown ;
- garder la vue Performance : ports, Scene, VP, hash, latence, Panic et état de connexion.

Sortie : une trace golden multi-source est comparée à l'expected trace de référence générée par M1. Un stimulus numéroté donne 100 % des événements attendus, sans double/loop/out-of-order au débit nominal ; 30 minutes de jeu physique complètent l'audition.

### M3 — Firmware renderer DDrum4

Propriétaire : agent Firmware.

Travail :

- sécuriser le parser DIN face à SysEx/System Common et running status, même si SysEx est ignoré ;
- compiler Scene/VP/Logical routes en tables compactes triées en PROGMEM, lues par `pgm_read_*` après benchmark, sans table dense en SRAM ;
- quand `firmware-project-mapping.json` est `ready`, générer le header avec `python firmware/ddrum4-midi-bridge/tools/generate_mapping.py --project-mapping build/generated/<projet>/firmware-project-mapping.json --output-channel <canal_DDrum4_mesure> --output firmware/ddrum4-midi-bridge/include/generated_mapping.h` ; la commande refuse les placeholders et les décodeurs non abaissables au firmware ;
- gérer changements PC/CC, position snare en trois zones, CC4 par source/pédale et HH quantifié en NOTE P par frappe ;
- abaisser `native_control_map` vers le runtime PC et le bridge : Program Change, CC ou Note mesuré du DDrum4 met à jour Scene/VP sans être interprété comme une frappe ;
- gérer aftertouch/choke avec un ledger borné `source/channel/note -> destination`, et une expiration/remplacement sans croissance ;
- fixer `MAX_OUTPUT_EVENTS`, le débit maximal et la priorité HIT/EXPRESSION ; compter tout overflow UART au lieu de bloquer silencieusement ;
- ajouter le guard causal uniquement si M0 le justifie ;
- intégrer des pins de mesure uniquement dans une cible diagnostic après vérification des conflits shield/LED/SPI.

Sortie : PC et firmware produisent les mêmes Physical Events, Logical Sounds et transitions d'état, puis chacun correspond à son golden renderer MIDI. Un stimulus compté et 200 frappes physiques couvrent pertes, boucles et chokes.

### M4 — Couverture SD3 et bibliothèque neutre

Propriétaire : agent Capture/Audio.

Travail :

- inventorier les 469 WAV/28 instruments déjà documentés et leur couverture réelle ;
- définir plusieurs sessions versionnées par famille, fusionnables en une bibliothèque et couvertes par un rapport global ;
- exposer controllers, traitement WAV, silence/clipping policy, retry et rapport dans la CLI/API ;
- garantir reprise et immutabilité des raws ;
- générer la fiche du mega-kit/mapping SD3 à créer manuellement ;
- recapturer uniquement les articulations manquantes, rejetées ou insuffisantes pour kick, snare, toms, HH, ride, crashes et stack ;
- conserver les répétitions/round robins pour DrumGizmo et sélectionner séparément les couches DDrum4.

Sortie outil : sessions résumables, aucune prise silencieuse/clippée non signalée, bibliothèque hashée. Sortie asset distincte : bruit, tails, dynamique et timbre auditionnés ; silence/clipping seuls ne prouvent pas la qualité musicale.

### M5 — Pack DDrum4 du kit retenu

Propriétaire : agent DDrum4/Bank.

Travail :

- terminer d'abord les deux Sounds combinés crash + HH-edge déjà identifiés ;
- auditionner et finaliser la palette ; toute suppression de Sound reste une action utilisateur distincte et confirmée ;
- reconstruire les Sounds effectivement retenus : sélection, préparation, cfg, build `ddrum4edit`, re-inspection, hashes et rapport ; l'orchestrateur full-bank générique est post-MVP ;
- distinguer `ddrum4edit transfer_blocks` et `measured_mem_left_delta`, ce dernier restant `unknown` s'il n'est pas isolable ;
- générer notes/NOTE P, routing contract et instructions de Program/Palette ;
- exposer `launch-ddrum4ui` ainsi que `ddrum4edit info|inspect|build` ;
- maintenir confirmation explicite, settings dump valide, inventaire/ID réservé, receipt et lecture `MEM.LEFT` avant/après. Le settings dump n'est jamais présenté comme une sauvegarde des Sounds audio.

Sortie : une commande offline reconstruit le pack ; les opérations hardware restent séparées, confirmées et traçables. Une affectation manuelle finale dans DDrum4UI est acceptable au MVP si le protocole de kit n'est pas décodé.

### M6A — Intégration DDTi

Propriétaire : agent Devices. Dépend de M1 et d'un golden dump, pas de la capture SD3.

- compiler le preset depuis projet + wiring + golden dump ;
- ouvrir l'éditeur actuel pour review/diff/write ;
- vérifier les champs modélisés par un nouveau dump initié au panneau ;
- ne jamais toucher les bytes opaques.

Sortie : base dump + diff + hash + confirmation + dump de relecture égal sur les champs ciblés.

### M6B — DrumGizmo

Propriétaire : agent Capture/Export. Dépend de M1 et de la bibliothèque M4.

- fournir à la CLI les notes issues du projet ; fait : `drumgizmo-midimap.json` contient `instrument`, `articulation` et note, puis `drum-sampler export-drumgizmo --note-map` les applique ;
- exporter les canaux réellement capturés ; quatre canaux seulement si la capture et le backend cible ont été validés ; l'export valide aussi les liens XML (instruments, canaux, WAV lisibles et `filechannel`, puis `midimap`) avant de remettre le kit ;
- ajouter rapport et smoke test avec version/backend DrumGizmo enregistrés ;
  fait avec DrumGizmo 0.9.20 sous WSL, `dgvalidator --pedantic`, chargement du
  moteur et sortie audio WAV factice. La preuve comparative Poly Aftertouch
  0/127 mesure une atténuation de queue de 23,69 dB ; le package r5 groupe en
  outre les 14 articulations de hi-hat pour éviter les queues superposées.

Sortie : kit DrumGizmo réellement chargé/joué avec le même namespace logique que SD3.

### M7 — Control Center et scripts live Windows/Linux

Propriétaires : agent UI/Orchestration + agent Windows/Ops.

Le Control Center MVP valide/compile le projet, lance les jobs CLI et ouvre la vue Performance JUCE, DDTi Editor et DDrum4UI. Les ports, Scene/VP, métriques et Panic restent dans JUCE. Capture, builds et exports restent d'abord des jobs avec rapports JSON ; l'UI n'en réimplémente ni l'éditeur ni les safety gates.

Scripts :

- `live-preflight.ps1` : dépendances, noms uniques des ports, loopMIDI/WMS, UMC, hash et buffer ASIO déclaré/confirmé quand le driver n'offre pas d'API stable ;
- `start-live.ps1` : ordre de lancement, process IDs possédés, journal de session et injection limitée au processus Converter de `DDRUM4_RUNTIME_PROFILE`/`DDRUM4_RENDERER_TARGET=sd3` ;
- `stop-live.ps1` : arrêt des seuls processus lancés ;
- `set-low-latency.ps1` : après confirmation, sauvegarde le GUID du power plan dans l'état de session ; applique au plus la priorité `High`, jamais `Realtime`, et seulement aux PID possédés ;
- `restore-live.ps1` : restauration exacte ;
- `measure-latency.ps1` : orchestre la matrice de la section 6.
- `live-preflight.sh`, `start-live.sh`, `stop-live.sh` : session Linux DrumGizmo explicite, avec bridge ALSA -> JACK `a2jmidid`, PIDs possédés et connexions JACK déclarées. `start-live.sh ... --dry-run` et `stop-live.sh ... --dry-run` valident et décrivent l'action sans I/O matériel.

Tous possèdent un mode `-WhatIf`/dry-run et échouent avant lancement si un endpoint est ambigu. Au démarrage, ils détectent et proposent de restaurer une session interrompue. Ils ne désactivent ni sécurité Windows ni services non liés.
`start-live.ps1` exige `-ConfirmStart` comme confirmation explicite unique; `-Confirm` reste disponible pour demander la confirmation PowerShell standard.

Sortie : avec prérequis et configuration locale installés (loopMIDI/WMS, UMC, chemin SD3/host, mega-kit sauvegardé), un clic ou une commande vérifie et lance la session. Le bon mega-kit reste `user-confirmed` faute d'API officielle. L'arrêt restaure les réglages possédés.

### M8 — Validation verticale et bundle personnel

Propriétaires : intégrateur + Validation/bench.

Travail :

- [x] produire un environnement Windows x64 reproductible et un raccourci/lanceur sans `PYTHONPATH` manuel : CPython embarqué, dépendances verrouillées, Converter Release, manifest SHA-256, installation versionnée sans droits administrateur, diagnostic post-installation et refus des chemins Win32 trop longs ; un installeur signé reste hors scope personnel ;
- [x] séparer le ZIP `tools-only`, partageable sans captures/audio, du ZIP `private-with-assets` destiné uniquement au laptop du propriétaire et pouvant contenir le preset SD3 approuvé et le kit DrumGizmo r5 ; aucune archive générée ne rentre dans Git ;
- exécuter le flux projet -> configs -> flash -> live -> capture -> DDrum4 -> DrumGizmo ;
- tester Metalcore, Scene électronique, VP1 et VP3/VP4 ;
- tester débranchement/reconnexion, Panic, fallback DDrum4 et restauration OS ;
- exécuter les runs de latence sur les deux renderers et archiver les raws ;
- documenter seulement le démarrage, les branchements et les limites restantes.

Sortie : prototype personnel lançable, rapports de validation et de latence, aucun blocker silencieux. Le bundle public exclut captures/audio, profils locaux et secrets interdits par les règles du dépôt. L'archive privée est un artefact local ignoré, réservé au transfert vers le laptop live, et ne contient jamais les applications ou banques Toontrack elles-mêmes.

## 8. Organisation multi-agent

Avec quatre slots simultanés, trois agents produisent et un intégrateur garde le chemin critique. Les agents n'éditent pas les mêmes sous-arbres dans une même vague.

| Agent | Responsabilité et propriété principale |
| --- | --- |
| Intégrateur | décisions de contrat, revue des artefacts, tests globaux, `docs`, scripts racine |
| Domaine/Compiler | `packages/drum-domain`, `contracts`, nouveau compilateur et profils projet |
| Realtime C++ | `apps/ddrum4-modernizer` |
| Firmware | `firmware/ddrum4-midi-bridge` |
| Capture/Export | `apps/drum-sampler`, export DrumGizmo, profils capture |
| DDrum4/Bank | `apps/ddrum4-bank-builder`, profils banks/targets |
| Devices | intégration `apps/ddti` et wiring ; modifications DDTi limitées aux adaptateurs nécessaires |
| UI/Ops | nouveau Control Center et scripts live/latence Windows |
| Validation/bench | traces, rapports, tests hardware ; ne modifie pas les moteurs en parallèle d'un propriétaire |

Chaque lot se termine par un handoff contenant : fichiers, commandes exécutées, résultats, artefacts, actions hardware, hypothèses, critères passés et points nécessitant une audition.

Les écritures hardware sont toujours séquentielles. Deux agents ne flashent/transfèrent jamais en parallèle. L'intégrateur réserve le device, vérifie la cible et demande/consigne la confirmation nécessaire.

### Vague 0 — fondations, 1 à 2 jours de code plus branchements

- Intégrateur : environnement propre et baseline.
- Validation/bench : preuve DIN et première mesure de latence.
- Domaine/Compiler : spécification `rig-project/v1` et fixture.

Gate : parser SysEx sûr, preuve DIN, décision dual et draft du contrat accepté.

### Vague 1 — MVP Live vertical, 3 à 5 jours de code

- Domaine/Compiler : générateurs runtime.
- Realtime C++ : multi-input + pipeline canonique.
- Firmware : parser sûr + state/tables générées.

Gate : mêmes Physical Events, Logical Sounds et transitions d'état sur PC/firmware, puis golden propre à chaque renderer.

### Vague 2 — MVP Toolchain offline, lot de code time-boxé séparément des gates matériels

- Capture/Export : recette complète et quality gates.
- DDrum4/Bank : repack immédiat puis pack reconstructible des Sounds retenus.
- Devices : preset DDTi généré et intégration.

Gate : bibliothèque acceptée, pack DDrum4 reconstructible, DDTi diff sûr, DrumGizmo chargeable.

### Vague 3 — agrégation et validation, 2 à 4 jours de code

- UI/Ops : lanceur, preflight et scripts.
- Realtime C++ : UI Performance, métriques et reconnexion.
- Validation/bench : matrice latence et soak tests.

Gate : lancement depuis machine redémarrée, stimulus compté, audition 30 minutes, fallback conditionnel et rapports.

Deux branches convergent : runtime `M0 + M1 -> M2 + M3 -> M7-live`, offline `M1 -> M4 -> M5 + M6B` et `M1 -> M6A`, puis intégration `M7 -> M8`. M0 et le draft M1 avancent en parallèle, mais le contrat runtime attend le gate commun. Les estimations ne couvrent que le code ; captures, transferts, production d'assets et auditions sont des gates matériels sans durée promise.

## 9. Critères d'acceptation du MVP

Le prototype est déclaré utilisable seulement si :

- tous les artefacts contrôlés portent le même hash ; les systèmes externes sont reliés par manifest/receipt/readback ;
- chaque source a une seule route primaire en mode live ;
- le Converter et Arduino résolvent les mêmes traces vers les mêmes Physical Events, Logical Sounds et transitions d'état, puis passent leurs goldens renderer respectifs ;
- velocity 1–127 est préservée hors courbe explicitement déclarée ;
- position snare, CC4, chick/splash et chokes passent les tests matériels ;
- un stimulus compté atteint 100 % des événements attendus, sans boucle, double, mauvais Note Off ou réordonnancement au débit nominal ; 30 minutes de jeu humain complètent l'audition ;
- après installation du câblage permanent et validation `DUAL`, le fallback SD3 -> DDrum4 ne demande aucun remapping ni recâblage MIDI ; avant cela, un runbook explicite couvre Local/mode Arduino/mixer ;
- sans Master Merger, les changements globaux partent du DDrum4 et l'UI désactive/marque les commandes locales ; avec Master Merger, les trois origines convergent dans un délai mesuré ;
- les sessions de capture sont fusionnables/résumables et ne remplacent jamais un raw ;
- le pack DDrum4 retenu est reproductible ; rapports `ddrum4edit` et delta `MEM.LEFT` sont distincts, avec `unknown` si nécessaire ;
- le kit DrumGizmo charge et joue réellement ;
- toute écriture DDTi reste précédée du base dump/diff/hash/confirmation ; toute écriture Sound DDrum4 exige settings dump, inventaire/ID, confirmation et receipt sans prétendre sauvegarder l'audio existant ;
- les rapports de latence publient p50/p95/p99/max, pertes et câblage pour DDrum4 et SD3 ;
- les scripts Windows restaurent le power plan et n'arrêtent que leurs processus ;
- l'utilisateur peut accomplir les workflows principaux depuis le Control Center ou un bouton qui ouvre l'outil spécialisé approprié.

## 10. Ordre d'exécution immédiat

1. Installer le workspace Python 3.12 et refaire passer `scripts/test-all.ps1`.
2. Corriger/tester le parser SysEx, effectuer la preuve isolée MIDI IN -> OUT et une baseline DDrum4/SD3 simple.
3. Compléter le wiring mesuré du rig.
4. Geler `rig-project/v1` sur Metalcore + une Scene électronique.
5. Générer un profil commun et faire converger Converter/firmware sur une trace golden.
6. Terminer les deux Sounds crash + HH-edge et la palette DDrum4 actuelle.
7. Livrer `STANDALONE`, garder `BENCH_PC_LOCAL_ON` pour le diagnostic et ouvrir le live PC officiel en `DUAL` après le gate.
8. Ouvrir `DUAL` seulement selon la preuve DIN et le câblage Master Merger.
9. Fermer les trous de couverture de la bibliothèque et valider DrumGizmo.
10. Ajouter le lanceur, les scripts Windows, la sonde dédiée et la matrice finale de latence.

Ce séquencement donne rapidement un kit jouable, tout en gardant la cible finale : un bus MIDI brut partagé, un état logique commun et deux renderers indépendants du même instrument.
