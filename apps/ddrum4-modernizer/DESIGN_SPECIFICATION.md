# ddrum4 Converter — design et spécification

**Statut :** proposition d'architecture révision 2 (8 août 2026)  
**But :** convertir en temps réel le MIDI sortant d'un ddrum4 SE en un port MIDI virtuel moderne, nommé par défaut `ddrum_converted`, destiné d'abord à Superior Drummer 3 (SD3), puis à DrumGizmo sous Linux.

## Décision en une page

Le produit est une **application desktop native C++23/JUCE**, composée d'un moteur MIDI sans allocation sur le chemin temps réel et d'une interface de configuration séparée. Elle lit un seul port d'entrée `ddrum4 MIDI OUT`, traduit les messages à partir d'un profil YAML validé, puis les écrit immédiatement vers un endpoint virtuel. Elle ne traite pas l'audio. Un même kit SD3 peut contenir trois **kits virtuels** : trois couches de mapping commutables instantanément, sans recharger SD3.

La conversion ne peut pas recréer les samples/layers internes choisis par le ddrum4 : ceux-ci ne sortent jamais du module. En revanche elle préserve tout ce que le MIDI expose : vélocité 1–127, timing, position, articulation, poly-aftertouch/choke et CC. En particulier, les huit notes de position d'une peau deviennent, pour SD3, un **CC de position envoyé juste avant une unique note “trigger”**.

Le profil SD3 de départ pour une snare positionnelle est :

```text
ddrum4 : Note # + 0..7, vélocité V
             │
             ├── CC16 = 0, 18, 36, 54, 73, 91, 109 ou 127
             └── Note 6, vélocité V       (Snare Trigger SD3 par défaut)
```

`CC16` et la note 6 sont la convention Roland/SD3 courante, mais restent des valeurs de profil : le MIDI Learn et les réglages *MIDI In/E-Drums* de SD3 sont la référence finale. Aucun numéro de note du ddrum4 ne doit être figé dans le binaire, car `Note #` et `Note P` sont configurables sur le module.

## 1. Ce que le ddrum4 émet réellement

### 1.1 Position : une information discrète encodée dans la note

Le manuel ddrum4 définit `Note #` comme la note centrale. Avec `Note P = 1, 2, 4 ou 8`, le module émet cette note et jusqu'à 7 notes MIDI consécutives en allant du centre vers le bord. `Note P = 8` est obligatoire pour son hi-hat. Ce n'est donc pas huit instruments : c'est une position radiale en 1, 2, 4 ou 8 pas.

Pour une snare `Note # = B`, la position reçue est :

```text
B     B+1   B+2   B+3   B+4   B+5   B+6   B+7
centre                                       bord
```

Le nombre exact de pas provient de la configuration active du ddrum4, jamais d'une supposition. La configuration peut changer par kit ou après une édition du module.

### 1.2 Vélocité, layers et variations

Un `Note On` ne contient que la note et une vélocité MIDI sur 7 bits. Les layers, multisamples et variations du ddrum4 sont déjà résolus dans son moteur sonore ; ils ne sont pas transmis comme métadonnées MIDI. Le convertisseur doit donc :

- recopier la vélocité exactement par défaut ;
- offrir ultérieurement une courbe par zone/articulation, désactivée par défaut ;
- ne jamais essayer d'inférer le layer ddrum4 qui a joué ;
- laisser SD3/DrumGizmo faire son propre round-robin et ses propres layers.

Cette limite est structurelle, pas un défaut du logiciel. La dynamique jouée est néanmoins conservée, ce qui est l'information utile pour choisir les layers de SD3.

### 1.3 Autres informations expressives

Le ddrum4 peut transmettre du polyphonic aftertouch depuis certains pads sensibles à la pression. Il faut le transformer selon la même table de notes que le `Note On` associé, afin de conserver les chokes et les contrôles de pression compatibles. Les CC utiles (notamment CC4 de pédale s'il est effectivement vu dans la capture), Program Change, MIDI Clock et transport doivent être des politiques explicites de profil, jamais des effets de bord implicites.

Le hi-hat est un cas à part. Ses huit notes peuvent représenter foot/chick, bow/edge et des états d'ouverture ; une éventuelle information continue de pédale est un flux indépendant. Le MVP ne doit pas le réduire aveuglément à la même conversion que la snare. Il doit d'abord capturer un jeu complet de hi-hat et choisir l'un des deux modes configurables :

1. **continu (préféré)** : note tip/edge/chick/splash mappée + CC4 original remappé/calibré ;
2. **discret** : note(s) ddrum4 vers articulation SD3 + CC4 synthétique, avec une table de huit valeurs, uniquement si aucune donnée de pédale n'est émise.

## 2. Écart avec les cibles

| Sujet | ddrum4 OUT | SD3 | DrumGizmo |
| --- | --- | --- | --- |
| Snare position | note contiguë `B..B+7` | note trigger + zones déterminées par un CC configurable | mapping note → instrument ; pas de position/CC stable à supposer |
| Hi-hat | notes spéciales, éventuellement CC4 | articulation tip/edge/bell + ouverture CC4 | notes d'instruments (closed/open/pedal) ; groupe de choke possible |
| Vélocité | 1–127 | 1–127 et courbes par articulation | 1–127, couches propres au kit |
| Choke/pression | poly-aftertouch possible | pris en charge par les presets e-drums | dépend du kit/du moteur ; profil dédié |
| Mapping | configurable dans le module | MIDI Learn et presets utilisateur | `midimap.xml` note → instrument |

SD3 possède précisément des zones CC personnalisables pour les e-drums et sait gérer position de snare, position de ride, choke et réponse de vélocité. C'est la cible qui valorise le mieux l'information ddrum4. DrumGizmo reçoit très bien un MIDI normal via JACK, mais son `midimap.xml` standard est une table note → instrument : son profil initial choisira donc des notes dédiées par articulation. Il ne faut pas lui promettre la position continue avant d'avoir validé la version de DrumGizmo et le kit cible.

## 3. Architecture proposée

```text
ddrum4 MIDI OUT / USB interface
             │
             ▼
      [MIDI input callback]
             │ événement MIDI horodaté
             ▼
   ┌──────────────────────────┐        copie best-effort (SPSC)
   │ moteur de conversion +   │──────────────────────────► MIDI monitor/UI
   │ kit virtuel actif (A/B/C)│
   └────────────┬─────────────┘
                │ 0 à 4 événements, même horodatage
                ▼
     [backend de sortie MIDI]
          │                 │
          ▼                 ▼
 Windows MIDI Services    ALSA sequencer / JACK MIDI
 loopback `ddrum_         port `ddrum_converted`
 converted`               │
          │                 └── DrumGizmo / DAW
          └── SD3 standalone ou dans le DAW
```

Le cœur ne connaît ni fenêtres, ni YAML, ni disque, ni logs. Les changements de profil sont compilés hors temps réel puis appliqués par échange atomique d'un snapshot immuable. Un kit virtuel est lui aussi un snapshot précompilé : le changement A/B/C est donc une sélection O(1), sans parsing ni reconstruction de route. L'ancienne configuration reste vivante jusqu'à l'arrêt sûr du callback ; aucune allocation/libération n'est faite dans celui-ci.

### 3.1 Ordre d'émission d'une position

Un même coup se traduit de manière atomique dans cet ordre :

```text
CC de position -> Note On destination (même vélocité) -> Note Off mappé, si requis
```

CC et note portent le même timestamp de capture quand le backend le permet. Si la cible exige un ordre strict, la note peut être horodatée `+1 µs`, **sans temporisation active**. Le convertisseur ne bufferise jamais un coup pour « attendre » un autre coup.

Avec un câble DIN physique, deux messages MIDI successifs coûtent environ 1,92 ms sur le fil à 31,25 kbit/s ; ici la sortie est virtuelle, donc cette contrainte série n'existe pas. La latence audible restera majoritairement celle de l'USB, de SD3 et du tampon de l'interface audio.

### 3.2 Sémantique des événements

| Entrée | Action par défaut |
| --- | --- |
| Note On, vélocité > 0 | convertir et émettre immédiatement |
| Note On, vélocité 0 / Note Off | convertir vers la même note de destination ; option `suppress` pour les cibles purement percussives |
| Poly-aftertouch | convertir la note via la route active ; transmettre si le profil le demande |
| CC4 | transmettre/remapper uniquement au hi-hat déclaré |
| CC inconnu | monitorer ; bloquer par défaut, liste blanche possible |
| Program Change | sélectionner un kit virtuel si le gestionnaire est activé ; sinon bloquer, passage explicite optionnel |
| Clock/Start/Stop/Continue | passage optionnel et transparent |
| SysEx | ne jamais relayer dans le MVP ; capturer uniquement si demandé |

L'option `Note Off = forward` est la valeur sûre pour l'enregistrement MIDI. Plusieurs notes d'origine peuvent converger sur la même note destination ; pour un sampler de batterie one-shot cela ne pose pas de problème. Si une cible réagit à la durée des notes, le monitor doit signaler ce cas et le profil peut utiliser la politique `suppress` ou une articulation destination distincte.

### 3.3 Gestionnaire de programmes et kits virtuels

Un **kit virtuel** n'est pas un chargement de preset dans SD3. C'est un mapping alternatif vers les instruments déjà chargés dans *un seul* kit SD3 : par exemple `Core`, `Metal` et `Electro` peuvent interpréter le même coup ddrum4 comme trois notes de destination, trois canaux de sortie, ou trois zones/CC différents. Chaque kit peut aussi écouter un autre canal ou une autre plage de notes source. Le changement est donc immédiat et ne déclenche ni streaming de samples, ni silence, ni changement de kit côté SD3.

Les trois moyens de sélection sont équivalents :

1. clic sur `1 · Core`, `2 · Metal` ou `3 · Electro` dans la barre permanente de l'application ;
2. raccourcis clavier `1`, `2`, `3` quand la fenêtre est au premier plan ;
3. `Program Change` reçu du ddrum4 (ou d'un contrôleur MIDI explicitement autorisé).

Par défaut, `PC 0 → Core`, `PC 1 → Metal`, `PC 2 → Electro`. Le Program Change est **consommé localement** : il ne part pas vers SD3, afin de ne pas y charger un kit imprévu. Une politique distincte pourra ultérieurement autoriser l'émission d'un PC vers une cible particulière. Le ddrum4 transmet des Program Changes lors d'une sélection de kit : cette option permet donc de lier ses kits physiques aux trois interprétations SD3, mais elle peut aussi être désactivée si ces changements ne doivent pas affecter SD3.

La bascule prend effet sur le premier événement suivant le clic/PC, sans vider de notes ni envoyer de note artificielle. Un ledger fixe d'événements actifs mémorise, par note source, la note destination et la génération du kit virtuel : un `Note Off` ou un poly-aftertouch arrivé après une bascule utilise encore la route du coup original. Ce ledger est borné, préalloué et son overflow est visible dans le monitor.

## 4. Modèle de configuration

Le format de travail est YAML, versionné et validé par schéma. Le fichier source est lisible et sauvegardé dans le dossier utilisateur ; une version binaire compilée en mémoire est seule utilisée pendant le jeu.

Deux notions évitent une fausse « configuration ddrum4 par défaut » :

- `ddrum4-template.yaml` est livré avec la structure, les règles et le profil SD3 ;
- `ddrum4-<nom-kit>.yaml` est créé par l'assistant de capture et contient les vraies notes `Note #`, le canal et les articulations du module de l'utilisateur.

Le manuel rend les notes de chaque canal configurables : aucun fichier universel ne peut donc être garanti factory-correct sans capture d'un module donné. Le premier profil validé devient le **profil ddrum4 par défaut de l'installation** et peut être réimporté à partir d'un SysEx/configuration capturé ultérieurement.

### 4.1 Exemple : snare positionnelle SD3

```yaml
schema_version: 1
profile: ddrum4-to-sd3

input:
  port_match: "ddrum4"       # ID persistant préféré au nom
  channel: 10                 # 1..16 ; à mesurer sur le module

output:
  endpoint: ddrum_converted
  channel: 10
  backend: auto               # windows-midi-services | loopmidi | alsa | jack

program_manager:
  enabled: true
  source: { port: same_as_input, channel: 10 }
  initial_kit: core
  unknown_program: ignore_and_monitor
  forward_program_change: false
  bindings:
    - { program: 0, kit: core }
    - { program: 1, kit: metal }
    - { program: 2, kit: electro }

routes:
  - id: snare_head_position
    match:
      type: note_range
      first_note: 40          # EXEMPLE : vraie Note # à capturer
      count: 8
    transform:
      type: positional_note_to_cc
      destination_note: 6     # SD3 « Snare Trigger » par défaut
      position_cc: 16         # convention position snare Roland/SD3
      cc_values: [0, 18, 36, 54, 73, 91, 109, 127]
      cc_before_note: true
      velocity: preserve
      note_off: forward

  - id: snare_rim
    match: { type: note, note: 48 } # EXEMPLE, à capturer
    transform:
      type: note_map
      destination_note: 40          # rimshot/edge choisi avec MIDI Learn SD3
      velocity: preserve

policies:
  poly_aftertouch: map_active_note
  cc: { allow: [4] }
  program_change: drop
  realtime: pass
  sysex: drop
```

`cc_values` n'est pas une interpolation cachée : c'est une table explicite, réglable à l'oreille dans les seuils de zones SD3. La direction est centre = 0, bord = 127, conformément à l'encodage `Note #` → notes suivantes du ddrum4. Si une capture montre l'inverse, l'assistant inverse la table et le marque dans le profil.

### 4.2 Déclaration des trois kits virtuels

Le profil contient une base commune, puis seulement les différences par kit virtuel. Ainsi, une correction de CC4, de note source ou de vélocité partagée n'est écrite qu'une fois. Une surcharge peut modifier le **match d'entrée** (note/canal reçu), la transformation, ou le canal/note de sortie. Elle ne peut pas ajouter une route non validée sans recevoir un `id` unique.

```yaml
virtual_kits:
  - id: core
    label: "1 · Core"
    color: amber
    # Hérite des routes définies plus haut : snare -> CC16 + note 6, etc.

  - id: metal
    label: "2 · Metal"
    color: red
    route_overrides:
      - route: snare_head_position
        transform: { destination_note: 14 } # autre Snare Trigger configuré dans SD3
      - route: snare_rim
        transform: { destination_note: 41 }

  - id: electro
    label: "3 · Electro"
    color: cyan
    output_override: { channel: 11 }
    route_overrides:
      - route: snare_head_position
        match: { channel: 12, first_note: 52, count: 8 }
        transform:
          destination_note: 60
          position_cc: 20
          cc_values: [0, 18, 36, 54, 73, 91, 109, 127]
      - route: snare_rim
        match: { channel: 12, note: 61 }
        transform: { destination_note: 61 }
```

Dans cet exemple, `Metal` garde les mêmes pads entrants mais cible d'autres articulations du kit SD3 déjà chargé. `Electro` montre l'autre cas demandé : il n'accepte cette snare que sur le canal 12 et les notes 52–59, puis l'envoie au canal 11. Les champs omis héritent du kit de base ; une surcharge de `transform` est un merge champ à champ, non un remplacement implicite de la vélocité ou de la politique de Note Off.

Pour la V1, trois slots nommés sont fournis. Le modèle autorise 1–128 entrées afin de ne pas casser les profils futurs, mais l'interface Performance n'affiche que les trois premiers slots dans le flux normal. Bank Select (`CC0`/`CC32`) est mémorisé et monitoré mais ne change rien dans le MVP ; son exploitation vers davantage de programmes est une extension explicitement planifiée.

### 4.3 Routes requises

- `note_map` : une note source vers une note destination ;
- `positional_note_to_cc` : N notes contiguës vers CC + note ; N ∈ {1, 2, 4, 8} ;
- `hihat_continuous` : note/articulation + transformation CC4 et calibration fermé/ouvert ;
- `hihat_discrete` : table de notes vers note(s) et CC4 synthétique ;
- `aftertouch_map_active_note` : conserve le choke après remapping ;
- `passthrough` contrôlé : messages explicitement acceptés.

Le validateur refuse : canal/note/CC hors plage, intervalle `first_note + count - 1 > 127`, routes ambiguës, valeurs CC non monotones sans `allow_non_monotonic`, endpoint identique à l'entrée, et une route de position qui partagerait un CC avec un autre pad sans l'autoriser explicitement. Il refuse aussi un `Program Change` lié deux fois, une référence de kit/route inexistante, ou une surcharge qui laisse un kit virtuel sans destination pour une note déclarée.

## 5. Pile technique retenue

### C++23 + JUCE 8.x (moteur et interface)

**Choix : C++23 avec JUCE**, CMake et tests Catch2/doctest. C'est le meilleur compromis ici : callbacks MIDI natifs, construction Windows/Linux depuis la même base, UI native compacte, accès direct aux timestamps et aucune dépendance à un runtime GC. Rust serait techniquement excellent pour le cœur, mais impose davantage d'intégration spécifique pour l'UI et les ports virtuels ; la latence ne serait pas meilleure que C++ dans ce cas.

Composants proposés :

- `converter-core` : C++ pur, déterministe, testé sans matériel ;
- `program-manager` : trois snapshots de kit virtuel, sélection UI/PC et ledger de continuité des notes ;
- `midi-runtime` : adaptateurs JUCE pour entrée/sortie et timestamps ;
- `virtual-port` : abstraction Windows MIDI Services / loopMIDI / ALSA / JACK ;
- `config` : yaml-cpp + JSON Schema généré/validé hors callback ;
- `app` : UI JUCE (pas de framework web ni Electron) ;
- `cli` : mêmes profils, pour diagnostic et lancement sans UI.

JUCE doit être compilé sans audio device callback : l'application est un routeur MIDI. Ceci réduit l'empreinte et évite toute compétition avec le pilote ASIO de SD3.

### Backends de port virtuel

| Système | Chemin recommandé | Repli |
| --- | --- | --- |
| Windows 11 avec Windows MIDI Services disponible | endpoint virtuel de sortie nommé `ddrum_converted`, ou paire loopback persistante configurée | port créé par loopMIDI, sélectionné par nom/ID |
| Linux | port de sortie ALSA sequencer nommé `ddrum_converted` | port JACK MIDI direct ; pont ALSA↔JACK si nécessaire |

Sous Windows, Windows MIDI Services est le chemin durable : il offre des endpoints loopback app-à-app et JUCE 8 expose la création d'un port MIDI 1 compatible quand ce service est actif. La détection doit être explicite car le support dépend de l'installation/du rollout. Cet adaptateur JUCE/WMS est encore qualifié d'expérimental ; il reste isolé derrière `virtual-port` et couvert par tests d'intégration. Pour le MVP, fournir aussi une procédure loopMIDI fiable est plus sûr qu'exiger le dernier SDK. Sous Linux, le port JACK permet de connecter directement DrumGizmo lancé avec son input `jackmidi` ; le port ALSA est préférable pour les DAW/moniteurs ALSA.

## 6. Interface utilisateur

L'UI ne doit jamais être dans le chemin MIDI. Elle s'inspire de la lisibilité de SD3 — panneau sombre, contrastes limités, informations musicales avant les réglages techniques — sans en copier les assets ni l'organisation. La vue par défaut est une seule surface **Performance** : pas de menu profond, pas de table de routage visible tant qu'on joue.

```text
┌ ddrum4 Converter                      ● CONNECTÉ     [⚙]
│ ddrum4 MIDI OUT  →  ddrum_converted   10  →  10
├───────────────────────────────────────────────────────────
│ KITS VIRTUELS
│ [ 1  CORE    PC 0 ] [ 2  METAL   PC 1 ] [ 3  ELECTRO PC 2 ]
│      actif                 clic / touches 1–3 / Program Change
├───────────────────────────────────────────────────────────
│ SNARE  Pos. 3/8  CC16=36 → Trigger 6       ●  Vél. 104
│ HI-HAT CC4=22     Edge → Trigger 46        ●
│ RIDE   Bell      → Trigger 53              ●
├───────────────────────────────────────────────────────────
│ [Mapping]  [Learn]  [Monitor]     0 drops · cœur 6 µs · Panic
└───────────────────────────────────────────────────────────
```

La barre `KITS VIRTUELS` est permanente dans toutes les vues. Le kit actif est très clairement coloré, les deux autres restent discrets, et chaque bouton affiche le PC assigné. Un changement par UI devient effectif immédiatement ; l'interface indique aussi l'origine de la dernière sélection (`UI`, `PC ch.10 #1`, ou `startup`) et l'heure de celle-ci. Cela rend visible un Program Change involontaire envoyé par le ddrum4.

Les écrans secondaires, ouverts seulement au besoin, sont :

1. **Connexion** : ports détectés, statut du port virtuel, profil actif, start/stop et message de repli WMS/loopMIDI/ALSA/JACK.
2. **Mapping** : liste compacte des pads, avec une ligne par route et trois colonnes `Core | Metal | Electro`. La ligne ouvre un inspecteur latéral pour les notes/canaux entrants, note/CC de sortie et courbe. Les modifications sont *staged*, validées, puis appliquées par un unique bouton `Apply`.
3. **Programmes** : affectation graphique `PC → kit virtuel`, canal écouté, comportement des PC inconnus, et test manuel. Bank Select reste une option avancée repliée.
4. **Learn** : demander centre/milieu/bord, rim, bow/edge/bell, chick/splash et pédale fermée/ouverte ; enregistrer les traces et proposer la table dans le kit virtuel sélectionné.
5. **Monitor** : événement brut à gauche, événement transformé à droite, kit virtuel/génération utilisés, delta de traitement, filtres par canal/note/CC et compteurs de drops.

La différence importante est la suivante : `Apply` sert à publier une **édition de mapping**, alors que les trois boutons de programme sont des **contrôles de jeu** et n'ont pas de confirmation. Le bouton `Panic` est séparé, agit immédiatement et envoie les messages de coupure configurés ; il ne modifie ni profil ni kit actif.

Le monitor reçoit des copies via un ring buffer SPSC de taille fixe. S'il est saturé, il perd seulement l'affichage et incrémente un compteur ; jamais un événement musical. Les traces d'enregistrement sont écrites par un worker, hors callback.

## 7. Budget de latence et exigences non fonctionnelles

« Sans latence » signifie ici **ne pas ajouter de latence de conception**. On ne peut pas supprimer l'USB, l'ordonnanceur, le driver MIDI, SD3 ni le buffer audio.

- pas d'allocation, lock, accès disque, parsing YAML, log synchrone ou appel UI dans le callback MIDI ;
- coût du cœur de conversion : cible médiane < 10 µs, p99 < 100 µs sur le PC cible ;
- pas de look-ahead ni debounce additionnel ;
- ordre des événements source conservé, à l'exception du couple CC→Note produit pour un seul coup ;
- aucune note musicalement routable ne doit être perdue dans un test de rafale ;
- CPU et mémoire bornés ; mêmes résultats pour une même trace MIDI et un même profil ;
- reconnexion des ports sans crash, avec arrêt de sortie et indication visible plutôt que des messages envoyés au mauvais périphérique.

La mesure de référence est double : (a) timestamp entrée → sortie dans l'application et (b) écoute/mesure audio de bout en bout avec SD3 au buffer réellement utilisé. Réduire seulement le buffer ASIO est souvent bien plus audible que d'optimiser quelques microsecondes du routeur.

## 8. Protocole de validation matériel

Avant de déclarer un profil « par défaut », capturer et versionner ces scénarios :

1. chaque pad : 20 coups doux, moyens, forts ; note, canal et vélocité ;
2. snare : centre, 25 %, 50 %, 75 %, bord, rim, rimshot/cross-stick ;
3. ride/cymbales : bow, edge, bell, choke ;
4. hi-hat : bow/edge fermé, demi-ouvert, ouvert, chick, splash, fermeture d'une note ouverte, mouvement de pédale sans coup ;
5. rolls rapides, flams, coups simultanés sur deux pads, et 30 s de jeu dense ;
6. changement de kit et redémarrage du ddrum4, pour repérer une configuration de notes différente.
7. `PC 0`, `PC 1`, `PC 2`, un PC inconnu, et un PC envoyé par le changement de kit du ddrum4 ;
8. une Note On suivie d'un changement de programme puis de son Note Off/poly-aftertouch, afin de vérifier que le ledger conserve la route du coup d'origine.

Les tests automatiques rejouent chaque trace dans `converter-core` et comparent un fichier d'événements attendu. Les tests d'intégration bouclent la sortie virtuelle vers le monitor, puis vérifient ordre, note, vélocité, CC, aftertouch, kit virtuel et absence de Program Change transmis par erreur. La validation SD3 se fait en utilisant son MIDI Monitor, puis en ajustant les seuils de *Snare Zones* / *Hi-hat and Snare CC* et en sauvegardant un preset SD3 dédié à `ddrum_converted`.

## 9. Roadmap détaillée

### Phase 0 — caractériser le ddrum4 et préparer les références

- construire un captureur MIDI passif qui ne modifie jamais le flux, avec timestamp monotone et export JSON Lines/MIDI ;
- capturer les huit scénarios de la section 8, nommer les fichiers par kit ddrum4 et les déposer dans `tests/fixtures/` ;
- relever le canal, `Note #`, `Note P`, vélocités réelles, Program Changes et le comportement de redémarrage ;
- confirmer CC4 du hi-hat, le format exact des chokes et si une pression est émise sur la note de position ou la note de base ;
- produire `ddrum4-greg.yaml` depuis `ddrum4-template.yaml`, avec les routes marquées `validated: true` seulement après capture.

**Livrables :** fixtures MIDI reproductibles, premier profil mesuré, tableau des ambiguïtés à résoudre.  
**Sortie :** chaque pad du kit possède une identité MIDI documentée ; aucune hypothèse de mapping ne reste cachée dans le code.

### Phase 1 — noyau temps réel et gestionnaire de trois programmes (MVP CLI)

- initialiser CMake, CI locale, `converter-core` C++ pur et les tests de fixtures ;
- compiler le YAML en tableaux de routes fixes : `note_map`, `positional_note_to_cc`, Note Off, CC4 et poly-aftertouch ;
- implémenter le ledger préalloué de Note On/Off et les compteurs d'overflow ;
- implémenter `program_manager` : trois kits virtuels, sélection par commande CLI et par `PC 0/1/2`, PC consommé par défaut, swap atomique de snapshot ;
- exposer CLI `list`, `run`, `monitor`, `validate`, `program set <core|metal|electro>` et `program dump` ;
- créer les trois overlays SD3 de démonstration, même si `Metal` et `Electro` ne remappent d'abord que la snare ;
- mesurer p50/p95/p99 du cœur sur une trace dense et rejouer les transitions de programme en test.

**Critère de sortie :** `PC 0/1/2` change l'interprétation du coup suivant sans PC vers SD3 ; snare centre→bord, rim, kick et toms sont jouables dans SD3 sans note perdue sur une session de 30 minutes.

### Phase 2 — transport virtuel et intégration SD3/DrumGizmo

- intégrer les entrées/sorties JUCE et les reconnecter proprement après débranchement USB ;
- livrer la sortie `ddrum_converted` via loopMIDI sous Windows et ALSA sequencer sous Linux ; ajouter WMS lorsque l'environnement le permet ;
- tester le loopback et le comportement de ports par identifiant stable, pas seulement par nom ;
- créer `sd3-default` avec le mapping Snare Trigger/CC16, ainsi que `drumgizmo-note-map` et la génération optionnelle de `midimap.xml` ;
- vérifier dans SD3 le monitor MIDI, les zones de snare, le preset sauvegardé et les trois kits virtuels dans un même kit chargé ;
- valider DrumGizmo via JACK MIDI, en gardant les restrictions de position explicites.

**Critère de sortie :** les mêmes fixtures passent sous Windows et Linux ; SD3 voit un unique port `ddrum_converted` stable et les trois programmes sans rechargement de kit.

### Phase 3 — UI Performance très simple, puis édition sûre

- livrer d'abord la surface Performance et sa barre `Core | Metal | Electro`, plus les indicateurs de coup, de port et de latence ;
- ajouter les écrans Connexion, Mapping, Programmes et Monitor sans faire grossir la surface de jeu ;
- implémenter les éditions staged, validation, `Apply`, sauvegarde atomique, import/export et restauration d'un profil ;
- intégrer l'assistant Learn par pad et l'affichage de l'origine du dernier changement de programme ;
- ajouter le bouton Panic, les alertes de PC inconnu/ledger saturé et l'aide de diagnostic de port virtuel.

**Critère de sortie :** une répétition peut se faire avec la seule vue Performance ; une modification de mapping ne peut ni casser un profil actif silencieusement ni bloquer le jeu.

### Phase 4 — expressivité complète et robustesse live

- calibrer le hi-hat continu/discret et vérifier les chokes par trace ;
- ajouter ride positionnel, courbes de vélocité opt-in et transport MIDI facultatif ;
- rendre disponible Bank Select + Program Change seulement après tests de compatibilité ;
- tester changements de programmes rapides, reconnexion USB, reprise après veille et surcharge monitor ;
- ajouter comparaison de profils, édition graphique de seuils/curves et rapport de capture exportable ;
- documenter le setup live Windows et Linux, incluant le plan de repli loopMIDI/ALSA/JACK.

**Critère de sortie :** jeu dense, changement de trois kits virtuels et reconnexion ne produisent ni note perdue, ni mauvaise route, ni latence ajoutée perceptible.

## 10. Ce qui doit rester configurable

Les valeurs suivantes sont volontairement hors code : port/ID, canal, note de base, nombre de positions, orientation centre/bord, note trigger SD3, numéro de CC, seuils SD3, courbe de vélocité, politique de Note Off, hi-hat, choke, canal écouté pour les Program Changes, table `PC → kit virtuel` et comportement d'un PC inconnu. Le seul « défaut » acceptable est un profil de départ explicitement étiqueté `à valider`.

Le projet inverse voisin `../arduino_midi_router` est une excellente source de règles et de fixtures : son cœur C++ est déjà sans allocation, traite CC4 et conserve la vélocité. Il ne faut toutefois pas le copier tel quel : il fait l'opération inverse (eDRUMin/DDTi → ddrum4) et ses `Note #` sont des valeurs de kit déclarées, pas un mapping universel du ddrum4.

## Références étudiées

- [Manuel ddrum4 SE v1.5](https://images.thomann.de/pics/atg/atgdata/document/manual/123249_manual.pdf) — `Note #`, `Note P`, Local Off et aftertouch.
- [Toontrack : e-drums avec SD3](https://www.toontrack.com/blog/using-e-drums-with-ezdrummer-3-superior-drummer-3/) — position snare/ride, choke, courbes et zones CC personnalisées.
- [Toontrack : CC4 du hi-hat](https://www.toontrack.com/forums/topic/midi-high-hat-not-triggering-correctly-when-i-edit-them-in-sd3/) — les articulations open numérotées ne remplacent pas la pédale e-drum CC4.
- [Roland : exemple de position CC16 puis Note On](https://www.vdrums.com/forum/general/products/30901-positional-sensing-midi-cc-data-what-does-the-module-send) — convention centre = 0 et ordre CC→note.
- [Windows MIDI Services : loopback](https://microsoft.github.io/MIDI/kb/virtual-loopback/) — endpoints MIDI app-à-app persistants.
- [JUCE : endpoints virtuels et Windows MIDI Services](https://docs.juce.com/develop/classjuce_1_1universal__midi__packets_1_1Endpoints.html) — détection du service et création de ports MIDI virtuels.
- [DrumGizmo : CLI JACK MIDI](https://drumgizmo.org/wiki/doku.php?id=cli-howto) et [format `midimap.xml`](https://drumgizmo.org/wiki/doku.php?id=documentation%3Afile_formats) — entrée `jackmidi` et table note → instrument.
