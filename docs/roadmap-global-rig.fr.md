# Roadmap d'exécution — rig global

Ce document sépare explicitement les fonctions prêtes à tester hors matériel,
les conditions nécessaires à un flash Arduino, et les tâches qui restent avant
le premier branchement des pads. Il complète l'architecture finale; il ne
change aucun réglage de module.

## Palier A — contrat et simulation

- [x] Un modèle unique `Physical → Logical → DDrum4 / SD3 / DrumGizmo`.
- [x] Un Control Center capable de charger, modifier visuellement, valider et
  compiler un projet rig sans ouvrir de port MIDI.
- [x] Un simulateur offline de notes, scènes et Virtual Palettes, avec une
  trace des trois renderers.
- [x] Un diagnostic offline « no-pad » parcourt chaque entrée Note, scène,
  état VP connu et contrôle natif déclaré, puis produit un rapport sans ouvrir
  de port MIDI (`drum-control-center diagnose <projet>`). Tout décodeur CC ou
  aftertouch non encore simulé échoue explicitement : aucun faux PASS.
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

## Règle de flash

Ne passer le shield Arduino en programmation qu'après un artefact
`firmware-project-mapping.json` avec `deployment: live`, `status: ready` et
`hardware_flash: ready`. Le header actuellement versionné est volontairement
inerte et ne route aucun son.
