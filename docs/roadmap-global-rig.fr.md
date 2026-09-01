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
  le comportement de chaque renderer. Verticales réellement implémentées :
  `openness` CC4, position Snare1 CC16 et plage positionnelle Snare2 normalisée
  en CC16 vers SD3
  (CC et canal explicites)
  et, lorsqu'un kit le mesure, CC4 → note de zone discrète vers DrumGizmo.
  DDrum4 reste `planned` tant que polarité et seuils `NOTE P` ne sont pas
  capturés ; aucune cible ne devient fonctionnelle par défaut.
- [x] Un diagnostic offline « no-pad » parcourt chaque entrée Note/plage, scène,
  état VP connu et contrôle natif déclaré, puis produit un rapport sans ouvrir
  de port MIDI (`drum-control-center diagnose <projet>`). Les CC et
  aftertouch déclarés sont aussi signalés explicitement comme échec tant
  qu'une politique commune PC/Arduino/DDrum4/DrumGizmo n'est pas compilée :
  aucun faux PASS ni Note-On synthétique. Le contrat courant passe **5986/5986**
  chemins, dont les huit positions brutes de Snare2 à vélocité basse/haute et
  les 14 routes de choke dans toutes les scènes/palettes pertinentes.
- [x] Une matrice lisible de la banque r15 installée, y compris les layers,
  positions, vélocités, variations, pitch et round robin.
- [x] Les Program Change natifs sont des correspondances exactes
  `program → Scene/VP`, jamais des valeurs brutes copiées vers l'état.
- [x] L'éditeur expose ces commandes natives dans une table dédiée et le
  simulateur permet de déclencher directement chaque Program/Palette. Un smoke
  test Qt hors écran charge les 29 articulations, les 30 commandes natives et
  applique une commande sans ouvrir de port MIDI.
- [x] `Launch-Control-Center.cmd` précharge le projet r15, son dossier de build
  et le kit virtuel : l'application ne s'ouvre plus sur un workspace vide.
- [x] Un `control_bus` explicite sépare la sortie renderer PC (SD3/DrumGizmo)
  de la sortie logique PC → Master Merger/Arduino. Seul un profil `live` avec
  endpoint `user-confirmed` peut ouvrir ce second port sur CH14 ou CH15.
- [x] Le protocole MVP est borné à 128 scènes (Program Change 0–127) et
  quatre Virtual Palettes, les limites communes à l'UI et au firmware Uno.
- [x] Un preset e-drum SD3 portable couvre les 60 notes du renderer custom et
  CC4. Il permet de charger un kit/une extension standard sans modifier le
  Converter; les sons de scène retombent sur leur rôle acoustique équivalent.

## Palier B — garde-fous firmware

- [x] `deployment: simulation|live` est obligatoire pour un rig-project.
- [x] Un projet `simulation` produit des traces mais un générateur firmware le
  refuse; aucun profil `SIM_*` ne peut produire un header flashable.
- [x] Les actions DDrum4 sont conditionnables par Scene et VP; une observation
  native du DDrum4 ne lui est jamais réémise.
- [x] Le bridge Uno et le runtime PC sont compilés/testés avec la même
  correspondance exacte des contrôles.
- [x] Le mapping complet courant est compilé dans un environnement AVR
  d'estimation non téléversable : 339 `StateRoute`, 30 contrôles natifs et deux
  routes HH et 14 routes de pression occupent 12 224/32 256 octets de Flash
  (37,9 %) et 795/2 048 octets
  de RAM (38,8 %). Le header porte un garde-fou de compilation et la commande
  d'upload de `uno_capacity` échoue volontairement avant toute ouverture de
  port. Le rapport reproductible est généré par
  `scripts/build-firmware-capacity.ps1`.
- [x] Une expression explicitement PC-only, comme Snare1 CC16 vers SD3, reste
  visible comme `unsupported` pour DDrum4 mais ne bloque plus les tables de
  notes Arduino. Une expression non déclarée ou prétendument supportée sans
  implémentation reste, elle, bloquante.
- [x] L'ouverture de la sortie de contrôle exige une correspondance MIDI
  exacte, distincte du renderer; l'état Scene/VP complet est publié au départ
  et le panic ne touche jamais CH14/15.

## Palier C — modules configurés et profil live avant flash

- [x] Le Control Center crée une campagne de vérification versionnée depuis le
  projet sauvegardé : checklist des entrées, état DDrum4 et control-bus, hash
  du projet source, traces isolées Note/CC/aftertouch, et interdiction
  explicite de recopier les endpoints `SIM_*`. Les canaux/Notes/CC restent le
  contrat prescrit et toute divergence capturée devient `contract-mismatch`.
- [x] La campagne fraîche `greg-hybrid-r15-v23-r10` référence le SHA du projet
  courant et demande séparément 28 zones Note exactes, un sweep positionnel
  Snare2 de huit notes, eDRUMin CC4/CC16, 14 séquences Note-On → Poly
  Aftertouch et les 30 commandes natives Program/Palette, sans promouvoir
  aucune adresse matérielle inventée.
- [x] L'assistant `capture-greg-hybrid-live-trace.ps1` présente une seule zone
  à la fois, refuse une campagne dont le SHA source a changé, prévisualise sans
  I/O par défaut et n'écoute un port explicite qu'avec `-Capture`. Il valide la
  trace immédiatement et n'ouvre jamais de sortie MIDI.
- [x] Le même workflow est accessible depuis **Validation & deployment** du
  Control Center : sélection explicite de la campagne, de la preuve et du port
  d'entrée, confirmation receive-only, log asynchrone et review immédiate. Le
  remplacement d'une trace invalide archive l'ancienne preuve au lieu de la
  détruire.
- [x] Cette campagne relit les traces isolées et refuse une adresse absente ou
  ambiguë. Chaque décodeur MIDI brut possède sa propre trace : deux zones du
  même pad ne peuvent donc jamais être fusionnées. Une
  `note_range` n'est acceptée que si une trace isolée contient, sur un seul
  canal, chacun des codes Note On contigus attendus ; la plage observée remplace
  alors confirmer exactement la plage prescrite ; elle ne la remplace jamais.
- [x] `promote-configured` permet le premier profil live sans pads à partir du
  readback DDTi et du snapshot eDRUMin liés au même fingerprint de contrat.
  Ce profil est marqué `post-flash-validation-pending` : le flash est permis,
  mais le lancement live reste bloqué. Les traces restent obligatoires comme
  campagne fonctionnelle post-flash et produisent ensuite `hardware-verified`.
- [x] Une campagne complète permet une action explicite « créer le profil live
  mesuré » dans un **nouveau** YAML, avec les noms de ports fournis par
  l’opérateur. Cela ne crée ni firmware flashable ni écriture MIDI : le
  compilateur conserve le gate matériel suivant.
- [x] La promotion ne peut plus laisser le hi-hat dans une impasse `planned` :
  elle exige les endpoints fermé/ouvert présents dans la trace CC4 et tous les
  seuils normalisés DDrum4/DrumGizmo saisis par l'opérateur. Le profil produit
  est immédiatement recompilé par test avec `hardware_flash: ready`; aucune
  valeur proposée par la simulation n'est acceptée implicitement.
- [x] La promotion exige une topologie explicite par source (`din` ou `usb`).
  Le câblage Arduino THRU/UMC peut donc partager un endpoint pour CH12/CH2/CH3
  sans conserver par erreur les profils `LIVE_USB_PRIMARY` de simulation.
- [x] Une trace de choke n'est acceptée que si une unique frappe cible précède
  le Poly Aftertouch de même canal/note, sans seconde frappe active. La preuve
  source reste distincte de la sémantique renderer : DDrum4 et SD3 doivent être
  confirmés explicitement à la promotion et ne sont jamais marqués
  `measured` par la seule trace MIDI.
- [x] Réaliser la promotion configurée sur le rig physique avec les noms de
  ports observés, les canaux de sortie des trois modules et le canal global
  DDrum4 `C12`. Le profil local porte volontairement
  `post-flash-validation-pending` jusqu'aux traces de pads.
- [x] Écrire puis vérifier les notes prescrites de chaque module : readback
  DDTi 42/42, snapshot eDRUMin confirmé et configuration DDrum4 déjà validée.
  Seuls les noms d'endpoints étaient `SIM_*`; les canaux/notes du contrat ne
  sont jamais remplacés par une découverte de frappes.
- [ ] Capturer les six Program Change de scènes réellement utilisés et les 24
  commandes natives de palettes. Le DDrum4 peut adresser P1–P26, mais les
  programmes non déclarés par ce rig restent volontairement ignorés. Le script
  `capture-greg-hybrid-native-controls.ps1` les acquiert désormais en une
  séquence receive-only et ne publie les 30 preuves isolées que si l'ordre et
  chaque adresse correspondent exactement.
- [x] Compiler le profil live configuré, générer le header hashé, construire et
  flasher Uno via le gate à receipts, puis lancer le diagnostic sans pads. Le
  31 août 2026, le diagnostic offline passe 5986/5986 et l'audition DDrum4
  corrigée passe 30/30 avec 60/60 événements Note On/Off au THRU.
- [x] Construire le déploiement laptop Windows x64 autonome : CPython 3.12 et
  dépendances verrouillées, tous les outils, Converter Release, profils,
  installateur versionné sans admin, manifest SHA-256 exhaustif et diagnostic
  post-installation. Le premier ZIP `tools-only` a été extrait et installé dans
  un dossier vierge avec runtime/GUI verts ; il reste volontairement
  `post-flash-validation-pending`. Le mode `private-with-assets` ajoute le
  preset SD3 v23 et le kit DrumGizmo r5 uniquement dans l'archive locale
  non redistribuable.

## Palier D — test puis jeu avec pads

- [ ] Vérifier au THRU toutes les routes physiques, scènes et palettes, sans
  doublon USB/DIN et sans boucle. Le bootstrap sans pads est acquis pour la
  scène par défaut (30/30 sons, 60/60 événements), mais ne prouve pas encore
  les vrais pads ni les changements de programme.
- [ ] Mesurer dynamique, positions hi-hat, position Snare1 CC16 et sweep
  positionnel Snare2,
  aftertouch/choke et latence.
- [ ] Mesurer le soft-through DDrum4 sur la topologie isolée avant d'activer
  `DUAL`. `probe-ddrum4-soft-through.ps1` envoie 100 événements de chacun des
  trois types prévus et conserve les retours/latences dans un JSON ; il refuse
  toute émission sans confirmation qu'Arduino OUT est physiquement débranché.
- [x] Générer le MegaKit SD3 déterministe à partir du preset Metalcore et des
  presets utilisateur validés par SHA-256 ; les notes, sources, scènes et VP
  sont publiées dans `docs/greg-hybrid-r15-megakit.md` et son PDF. Le preset
  v23, sa calibration réelle, sa capture et l’export interne sont maintenant
  tous validés, y compris le smoke de l'hôte DrumGizmo Linux.
- [x] Générer la campagne v23 de 939 prises, avec cinq ouvertures HH bow, cinq
  edge, les articulations complètes des snares, le Custom Stack Progressive,
  trois toms Electronic Edge dédiés et l'identité immuable du preset. La
  campagne terminée conserve les 939 WAV masters et leurs rapports immuables.
- [x] Prouver la boucle fermée `out_ClyphX 6 → SD3 → loopback:OUT 3-4` à
  48 kHz et exécuter une calibration complète v16 des 61 articulations. Cette
  passe a validé les niveaux corrigés et isolé quatre snares importées muettes.
- [x] Valider en boucle fermée les 70 articulations de la v23, notamment
  `Center/Mid/Edge/Rimshot/Side Stick` des snares Deftones et Sleep. Aucun
  silence technique, écrêtage ou outlier relatif n'a été détecté.
- [x] Après approbation humaine du mix v23, exécuter les 939 captures, valider
  les WAV et produire le kit DrumGizmo réel seulement si le gate reste vert.
  Résultat du 29 août 2026 : 939/939 masters et 42/42 centres multicouches
  acceptés, zéro rejet/manquant/RR dupliqué ; export autonome de 77 instruments,
  1001 samples et 1018 fichiers validés.
- [x] Réattester hors I/O les composites après enrichissement du contrat
  CC16/mesures : `audit-composites` a accepté les 42/42 WAV et le réexport
  courant est identique octet pour octet aux 1018 fichiers du package v23.
  Après ajout de Snare2 positionnelle, un nouveau réexport r3 a de nouveau
  validé 77 instruments/1001 samples/1018 fichiers et reste identique octet
  pour octet. Aucun son n'a été recapturé ni modifié.
- [x] Ajouter les métadonnées DrumGizmo 2.0 exigées par `dgvalidator`, produire
  r5 et fermer le gate externe sous WSL Ubuntu : `dgvalidator --pedantic`
  0.9.20 accepte les 1018 fichiers, puis DrumGizmo 0.9.20 charge 2002 canaux en
  streaming, traite 48 000 frames sur entrée `test`/sortie `dummy` et quitte
  proprement. Le r5 ajoute le groupe `hihat` aux 14 articulations concernées ;
  son test Poly Aftertouch contrôle/choke mesure 23,69 dB d'atténuation de la
  queue avec une attaque identique. Aucun son n'a été recapturé.
- [ ] Autoriser explicitement le mode MIDI live du convertisseur seulement
  après ces mesures.
- [x] Intégrer le staging DDTi hors ligne au Control Center : sélection du dump
  complet reçu, compilation du template de rôles, application du layout
  Input/Tip/Ring et affichage du diff sémantique. Le script
  `capture-greg-hybrid-ddti-base.ps1` reste strictement receive-only. Un golden
  complet de 2016 octets / 42 paquets existe et le staging change exactement
  16 champs note/canal. Le 31 août 2026, l'écriture a utilisé un dump frais
  capturé dans la même exécution puis le readback obligatoire a reproduit les
  42/42 paquets du candidat, SHA-256
  `3809ff601575d0fd7637d5085b409ac4f9e34dc058f54b58adc4b12048766b8c`.

## Incrément de contrat — expressions communes

- [x] Implémenter le moteur Uno borné `CC4 → Note P` : il conserve le CC4 brut
  pour le PC et sélectionne, au coup, les cinq slots bow ou quatre slots edge
  définis par le profil renderer.
- [x] Séparer capacité et readiness dans le compilateur : le plan proposé est
  présent dans `firmware-project-mapping.json`, mais un unique verrou de mesure
  garde `hardware_flash: disabled`; le générateur refuse aussi directement un
  contrat hi-hat encore `planned`.
- [ ] Mesurer puis valider CC4 vers `NOTE P` DDrum4 (polarité, seuils,
  articulations bow/edge) dans une **nouvelle** copie `deployment: live`.
  Les valeurs de simulation ne peuvent jamais être flashées.
- [x] Ajouter la pression/choke corrélée avec le ledger borné
  `source/channel/note → destination` commun au runtime PC et au firmware.
  Cette verticale doit être déclarée `poly_aftertouch` / `active_rendered_hit`
  et mesurée avant d'être active dans un profil live. Le simulateur conserve
  aussi le dernier hit : un choke après un changement de Scene/VP reste lié à
  la destination rendue avant ce changement.
- [x] Déclarer les 14 routes exactes ride/crashes/splashes/stack/chinas,
  refuser les matchers génériques ambigus, tester l'aftertouch avant frappe,
  la seconde frappe active, le double hit, deux adresses de choke et la
  saturation du ledger. Le plan AVR de capacité les compile, mais la génération
  flashable les refuse tant que la campagne r10 et les confirmations renderer
  ne sont pas complètes.
- [x] Le ledger AVR ne mémorise que les adresses déclarées chokables : un burst
  de plus de 16 kicks/snares/toms non-pressure ne peut plus évincer une cymbale
  active avant son aftertouch. Une régression native couvre ce scénario.
- [x] Définir la verticale DrumGizmo `CC4 → note de zone` avec seuils et notes
  explicites par profil. Les dix captures cibles utilisent les notes 112–121
  (`edge_half` sur 121 pour éviter les notes SD3 occupées) ;
  l'activation live reste `planned` jusqu'à la mesure réelle du pédalier.
- [x] Transmettre la position Snare1 eDRUMin CC16 sans perte vers SD3 sur CH10,
  pour les six variantes de Snare1. DDrum4 et DrumGizmo restent explicitement
  `unsupported` jusqu'à la mesure et la définition d'un quantificateur.
- [x] Préserver la position Snare2 émise par NOTE P=8 : plage DDrum4 brute
  mesurable/promouvable, normalisation vers SD3 CC16 et quantification
  Center/Mid/Edge 8/11/12 dans `SNRE_981` par le générateur Uno. Le Converter DrumGizmo
  utilise les mêmes bornes 47/95 et sélectionne les captures acoustiques
  32–34, 37–39 ou 42–44 ; les scènes électroniques restent mono-position.
- [x] Prouver le choke/pression DrumGizmo : le runtime recible le Poly
  Aftertouch sur la frappe active, le package r5 groupe les 14 sons de hi-hat,
  et le smoke 0.9.20 mesure -23,69 dB dans la queue du crash de contrôle.
- [ ] Mesurer CC16 puis définir le quantificateur de position Snare1 pour
  DrumGizmo. Snare2 est désormais couvert sans mesure CC supplémentaire car
  sa position arrive déjà comme plage NOTE P discrète 8–15.

## Règle de flash

Ne passer le shield Arduino en programmation qu'après un artefact
`firmware-project-mapping.json` avec `deployment: live`, `status: ready` et
`hardware_flash: ready`. Le header de sécurité versionné par défaut est
volontairement inerte et ne route aucun son ; le générateur sait produire le
vrai header, mais uniquement depuis un profil live configuré qui franchit ce
gate et dont les receipts DDTi/eDRUMin portent le même contrat source.

## Lancement Windows final

Après promotion du profil configuré, `scripts/prepare-greg-hybrid-live.ps1`
compile le projet, vérifie séparément `runtime.sd3=ready` et
`firmware=ready`, puis écrit la configuration locale gitignorée. Le raccourci
`Launch-Greg-Hybrid-Live.cmd` lance SD3 et le Converter, ouvre les ports exacts,
publie Scene/VP sur CH15 et applique le plan d'alimentation enregistré. Le
raccourci `Stop-Greg-Hybrid-Live.cmd` arrête uniquement les processus possédés
par la session et restaure le plan précédent. Le preflight est désormais
strictement fail-closed avant tout lancement, y compris si le GUID du plan
d'alimentation manque. Chaque exécution conserve dans `local/reports` un JSON
avec hashes config/runtime, inventaire MIDI, buffer ASIO déclaré, PID, plan
d'alimentation appliqué/restauré et résultat d'arrêt ; l'état transitoire peut
donc être supprimé sans perdre le journal. Les lanceurs privilégient PowerShell
7 mais leurs écritures UTF-8 fonctionnent aussi sous Windows PowerShell 5.1.
Ce raccourci sélectionne le
renderer SD3 sous Windows ; DrumGizmo utilise sa session hôte Linux séparée,
avec le même projet compilé mais jamais un second renderer logiciel ouvert en
parallèle par ce lanceur.
