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
  implémentées : `openness` CC en passthrough vers SD3 (CC et canal explicites)
  et, lorsqu'un kit le mesure, CC4 → note de zone discrète vers DrumGizmo.
  DDrum4 reste `planned` tant que polarité et seuils `NOTE P` ne sont pas
  capturés ; aucune cible ne devient fonctionnelle par défaut.
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
- [x] L'éditeur expose ces commandes natives dans une table dédiée et le
  simulateur permet de déclencher directement chaque Program/Palette. Un smoke
  test Qt hors écran charge les 29 articulations, les 30 commandes natives et
  applique une commande sans ouvrir de port MIDI.
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
  du projet source, traces isolées Note/CC/aftertouch, et interdiction
  explicite de recopier les adresses `SIM_*`.
- [x] Cette campagne relit les traces isolées et refuse une adresse absente ou
  ambiguë. Chaque décodeur MIDI brut possède sa propre trace : deux zones du
  même pad ne peuvent donc jamais être fusionnées lors de la promotion. Une
  `note_range` exige encore une calibration manuelle et bloque explicitement
  toute promotion automatique plutôt que de conserver une plage simulée.
- [x] Une campagne complète permet une action explicite « créer le profil live
  mesuré » dans un **nouveau** YAML, avec les noms de ports fournis par
  l’opérateur. Cela ne crée ni firmware flashable ni écriture MIDI : le
  compilateur conserve le gate matériel suivant.
- [ ] Réaliser cette promotion sur le rig physique avec les noms de ports
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
- [x] Générer le MegaKit SD3 déterministe à partir du preset Metalcore et des
  presets utilisateur validés par SHA-256 ; les notes, sources, scènes et VP
  sont publiées dans `docs/greg-hybrid-r15-megakit.md` et son PDF. Ce statut
  prouve la génération structurelle, pas la validation audio : la révision
  courante doit encore passer la calibration réelle avant toute capture.
- [x] Générer la campagne complète v3 de 746 prises sur 59 articulations, dont cinq ouvertures HH bow
  et trois toms Electronic Edge dédiés
  et quatre edge pilotées par CC4, ainsi que l'export DrumGizmo reprenable.
  La campagne est préparée et reprenable, mais ses WAV ne sont pas encore
  capturés : le point suivant reste donc le gate audio autoritaire.
- [ ] Exécuter les 746 captures lorsque le port MIDI SD3 et le retour audio
  UMC seront visibles, puis valider les WAV et le kit DrumGizmo réel.
- [ ] Autoriser explicitement le mode MIDI live du convertisseur seulement
  après ces mesures.

## Incrément de contrat — expressions communes

- [x] Implémenter le moteur Uno borné `CC4 → Note P` : il conserve le CC4 brut
  pour le PC et sélectionne, au coup, les cinq slots bow ou quatre slots edge
  définis par le profil renderer.
- [ ] Mesurer puis valider CC4 vers `NOTE P` DDrum4 (polarité, seuils,
  articulations bow/edge) dans une **nouvelle** copie `deployment: live`.
  Les valeurs de simulation ne peuvent jamais être flashées.
- [x] Ajouter la pression/choke corrélée avec le ledger borné
  `source/channel/note → destination` commun au runtime PC et au firmware.
  Cette verticale doit être déclarée `poly_aftertouch` / `active_rendered_hit`
  et mesurée avant d'être active dans un profil live. Le simulateur conserve
  aussi le dernier hit : un choke après un changement de Scene/VP reste lié à
  la destination rendue avant ce changement.
- [x] Définir la verticale DrumGizmo `CC4 → note de zone` avec seuils et notes
  explicites par profil. Les captures cibles utilisent les notes 112–120 ;
  l'activation live reste `planned` jusqu'à la mesure réelle du pédalier.
- [ ] Décider et prouver les autres expressions DrumGizmo (choke, pression,
  position) ; elles restent explicitement non supportées.

## Règle de flash

Ne passer le shield Arduino en programmation qu'après un artefact
`firmware-project-mapping.json` avec `deployment: live`, `status: ready` et
`hardware_flash: ready`. Le header de sécurité versionné par défaut est
volontairement inerte et ne route aucun son ; le générateur sait produire le
vrai header, mais uniquement depuis un profil live mesuré qui franchit ce gate.

## Lancement Windows final

Après promotion du profil mesuré, `scripts/prepare-greg-hybrid-live.ps1`
compile le projet, vérifie séparément `runtime.sd3=ready` et
`firmware=ready`, puis écrit la configuration locale gitignorée. Le raccourci
`Launch-Greg-Hybrid-Live.cmd` lance SD3 et le Converter, ouvre les ports exacts,
publie Scene/VP sur CH15 et applique le plan d'alimentation enregistré. Le
raccourci `Stop-Greg-Hybrid-Live.cmd` arrête uniquement les processus possédés
par la session et restaure le plan précédent. Ce raccourci sélectionne le
renderer SD3 sous Windows ; DrumGizmo utilise sa session hôte Linux séparée,
avec le même projet compilé mais jamais un second renderer logiciel ouvert en
parallèle par ce lanceur.
