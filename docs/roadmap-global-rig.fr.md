# Roadmap d'exécution — rig global

Ce document sépare explicitement les fonctions prêtes à tester hors matériel,
les conditions nécessaires à un flash Arduino, et les tâches qui restent avant
le premier branchement des pads. Il complète l'architecture finale; il ne
change aucun réglage de module.

## Palier A — contrat et simulation

- [x] Un modèle unique `Physical → Logical → DDrum4 / SD3 / DrumGizmo`.
- [x] Un Control Center capable de charger, modifier visuellement, valider et
  compiler un projet rig sans ouvrir de port MIDI.
- [x] Un workspace visuel « Virtual kit & simulator » : une articulation
  physique sélectionne un son logique, puis montre côte à côte les trois
  destinations DDrum4, SD3 et DrumGizmo, avec vélocité, scène, journal et
  panic uniquement simulés.
- [x] Le compilateur publie aussi `virtual-kit-map.json`, la table
  état/source/physique/son logique/DDrum4/SD3/DrumGizmo exactement issue des
  routes compilées ; c'est le contrat de parité des trois renderers.
- [x] `expression-routing/v1` rend explicite, par source/physique/expression,
  le comportement de chaque renderer. Première verticale réellement
  implémentée : `openness` CC en passthrough vers SD3 (CC et canal explicites,
  testés de l'artefact au runtime C++). DDrum4 reste `planned` et DrumGizmo
  `unsupported` : ni le simulateur ni le compilateur ne les font passer pour
  fonctionnels.
- [x] Un diagnostic offline « no-pad » parcourt chaque entrée Note, scène,
  état VP connu et contrôle natif déclaré, puis produit un rapport sans ouvrir
  de port MIDI (`drum-control-center diagnose <projet>`). Les CC et
  aftertouch déclarés sont aussi signalés explicitement comme échec tant
  qu'une politique commune PC/Arduino/DDrum4/DrumGizmo n'est pas compilée :
  aucun faux PASS ni Note-On synthétique.
- [x] Une matrice lisible de la banque r15 installée, y compris les layers,
  positions, vélocités, variations, pitch et round robin.
- [x] Les Program Change natifs sont des correspondances exactes
  `program → Scene/VP`, jamais des valeurs brutes copiées vers l'état.
- [x] Un `control_bus` explicite sépare la sortie renderer PC (SD3/DrumGizmo)
  de la sortie logique PC → Master Merger/Arduino. Seul un profil `live` avec
  endpoint `user-confirmed` peut ouvrir ce second port sur CH14 ou CH15.
- [x] Le protocole MVP est borné à 128 scènes (Program Change 0–127) et
  quatre Virtual Palettes, les limites communes à l'UI et au firmware Uno.

## Palier B — garde-fous firmware

- [x] `deployment: simulation|live` est obligatoire pour un rig-project.
- [x] Un projet `simulation` produit des traces mais un générateur firmware le
  refuse; aucun profil `SIM_*` ne peut produire un header flashable.
- [x] Les actions DDrum4 sont conditionnables par Scene et VP; une observation
  native du DDrum4 ne lui est jamais réémise.
- [x] Le bridge Uno et le runtime PC sont compilés/testés avec la même
  correspondance exacte des contrôles.
- [x] L'ouverture de la sortie de contrôle exige une correspondance MIDI
  exacte, distincte du renderer; l'état Scene/VP complet est publié au départ
  et le panic ne touche jamais CH14/15.

## Palier C — profil live à mesurer avant flash

- [x] Le Control Center crée une campagne de mesures versionnée depuis le
  projet sauvegardé : checklist des entrées, état DDrum4 et control-bus, hash
  du projet source, et interdiction explicite de recopier les adresses `SIM_*`.
- [ ] Créer une copie `deployment: live` du projet, avec les noms de ports
  réellement observés, les canaux de sortie des trois modules et le canal
  global DDrum4 identique à son entrée (`C12` aujourd'hui).
- [ ] Relever les notes physiques de chaque pad et de chaque zone; ne pas
  reprendre les notes `SIM_*`.
- [ ] Déclarer les actions Program Change réellement utilisées pour les 26
  kits et les groupes de palettes. Toute valeur inconnue reste ignorée.
- [ ] Compiler ce profil live, générer le header hashé, construire Uno puis
  lancer le diagnostic sans pads avant tout test de jeu.

## Palier D — test puis jeu avec pads

- [ ] Vérifier au THRU toutes les routes, sans doublon USB/DIN et sans boucle.
- [ ] Mesurer dynamique, positions hi-hat, aftertouch/choke et latence.
- [ ] Compléter le MegaKit SD3 et le kit DrumGizmo à partir des captures.
- [ ] Autoriser explicitement le mode MIDI live du convertisseur seulement
  après ces mesures.

## Prochain incrément de contrat — expressions communes

- [ ] Mesurer puis abaisser CC4 vers `NOTE P` DDrum4 (polarité, seuils,
  articulations bow/edge) sans modifier le profil live avant capture réelle.
- [ ] Ajouter la pression/choke corrélée avec le ledger borné
  `source/channel/note → destination` commun au runtime PC et au firmware.
- [ ] Décider et prouver le comportement DrumGizmo pour les expressions ;
  jusque-là, le sacrifice note-only reste explicite et le diagnostic global
  d'expression reste négatif.

## Règle de flash

Ne passer le shield Arduino en programmation qu'après un artefact
`firmware-project-mapping.json` avec `deployment: live`, `status: ready` et
`hardware_flash: ready`. Le header actuellement versionné est volontairement
inerte et ne route aucun son.
