# eDRUMin — Greg Hybrid Raw Source Map

Ce document décrit la configuration persistante du module `eDrumIn BLACK`.
Elle impose les adresses brutes attendues par Arduino et par le Converter ; une
frappe de pad sert ensuite à calibrer le trigger, jamais à choisir sa note.

Profil machine : `profiles/physical/greg-hybrid-edrumin.yaml`.

## Configuration globale

1. Ouvrir eDRUMin Control et sélectionner `eDrumIn BLACK`.
2. Dans **Settings → Device Settings**, régler **Global Channel = 3**.
3. Laisser **Note Velocity = Linear Velocity** comme base de calibration.
4. Dans **Drum Map Editor**, créer `Greg Hybrid Raw Source Map`.
5. Affecter les notes ci-dessous, enregistrer la map puis double-cliquer dessus
   pour l'envoyer au module.
6. Attendre au moins cinq secondes après la dernière modification : l'eDRUMin
   sauvegarde automatiquement ses réglages dans le module.
7. Exporter ensuite un snapshot `.edp` sous le nom
   `Greg_Hybrid_Raw_Source_Map.edp` et conserver son hash dans le receipt de
   configuration local.

| Kit piece / articulation | Canal | Note MIDI | Nom (C-1 = 0) |
| --- | ---: | ---: | --- |
| Snare1 Head | 3 | 0 | C-1 |
| Snare1 Rimshot | 3 | 1 | C#-1 |
| Snare1 Cross-stick | 3 | 2 | D-1 |
| HH Bow | 3 | 3 | D#-1 |
| HH Edge | 3 | 4 | E-1 |
| HH Pedal Close | 3 | 5 | F-1 |
| HH Pedal Splash | 3 | 6 | F#-1 |
| Ride Bow | 3 | 7 | G-1 |
| Ride Bell | 3 | 8 | G#-1 |

## Affectation des entrées

- Snare1 possède deux sorties physiques séparées : `HIT` va sur l'entrée 1 et
  `RIM` sur l'entrée 2. Configurer cette paire comme **un seul pad dual-input
  dual-piezo**, HIT primaire et RIM secondaire — pas comme deux instruments
  mono indépendants. Affecter Head=0, Rimshot=1 et Side Stick=2 ; ajuster la
  plage Rimshot/Side Stick une fois le pad branché.
- Le cymbal hi-hat Zeitgeist va sur l'entrée 3, type **Hihat Cymbal**. Sa
  pédale va sur **Pedal 1**, mode **CC**, contrôleur **CC4**. L'option
  **Only send CC with Hit** reste désactivée pour conserver le mouvement
  continu de pédale.
- La ride à deux câbles utilise une paire verticale d'entrées : câble
  `BOW/EDGE` sur l'entrée du haut, type **Roland 3-Zone Ride**, et câble
  `BOW/BELL` sur l'entrée du bas automatiquement marquée **Bell**. Le projet
  consomme Bow et Bell ; une éventuelle Edge n'est pas routée.

## Contrôleurs d'expression

- Hi-hat : CC4 sur CH3, convention configurée `127 = fermé`, `0 = ouvert`.
  Une fois la pédale branchée, lancer sa calibration complète fermé → ouvert.
- Snare : activer le positional sensing et **Always Send Position With Hit**,
  avec CC16. Le Converter transmet CC16 à SD3 sans le quantifier.
- Les seuils, gain, scan, hold, decay, courbes et crosstalk restent une
  calibration électrique post-branchement. Ils ne changent ni le canal ni les
  notes ci-dessus.

Le manuel installé ne documente aucun CLI ni SysEx public pour écrire ces
réglages. Le chemin supporté est donc l'application eDRUMin et un snapshot
`.edp`; l'application n'a pas besoin de rester ouverte une fois la sauvegarde
effectuée.
