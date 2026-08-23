# Baseline de latence M0

`midi-lab` conserve les déclarations et les résultats dans `latency-run/v1`. La préparation, la validation et l'analyse sont volontairement offline : elles n'ouvrent aucun port MIDI/audio et n'émettent aucun message.

```powershell
python -m midi_lab.cli latency-prepare --output reports/ddrum4-direct.json --run-id ddrum4-direct-001 --source probe-din --renderer ddrum4 --note 38 --wiring "docs/latency-baseline.md#cablage"
python -m midi_lab.cli latency-validate reports/ddrum4-direct.json
```

Un outil de capture peut ensuite remplacer `status` par `measured` et renseigner les `observations`. Un run `prepared` doit conserver une liste d'observations vide et ne peut pas être analysé. Chaque observation contient les instants observés en microsecondes et leur `clock_domains`; les deux objets emploient exactement les mêmes milestones connus. L'analyse ne soustrait deux instants que lorsqu'ils déclarent le même domaine d'horloge ; sinon elle compte la paire incompatible. Les pertes sont calculées sur les séquences uniques valides dans `[0, count-1]`; les doublons, séquences hors plage et retours strictement décroissants sont comptés séparément (une égalité est un doublon, pas un retour d'ordre). Les statistiques publiées sont p50/p95/p99/max, écart-type, jitter p99-p50, pertes, doublons et ordre. Les fichiers bruts (WAV, trace logic analyzer) restent référencés et archivés séparément : ils ne sont pas créés par cette CLI.

Après la capture et seulement après le passage de `status` à `measured`, lancer :

```powershell
python -m midi_lab.cli latency-analyze reports/ddrum4-direct.json --output reports/ddrum4-direct-analysis.json
```

## Statut de M0

La toolchain, son schéma de rapport et les validations hors ligne sont codés.
Les traces brutes, baselines DDrum4/SD3 et la décision d'ouverture du mode
`DUAL` sont volontairement reportées au test final du rig complet. Aucun
rapport `measured` ne doit être fabriqué avant ce branchement.

## Câblage de référence

Topologie actuellement déclarée, à confirmer dans chaque run plutôt qu'à
traiter comme un profil de routage mesuré : tous les modules, dont l'UMC404HD,
sont connectés en USB au PC ; DDrum4 MIDI OUT alimente Arduino MIDI IN et
DDrum4 MIDI IN reçoit UMC404HD MIDI OUT. Cette topologie permet de caractériser
les segments Arduino, PC et DDrum4 séparément. Elle ne remplace pas le Master
Merger nécessaire au contrôle bidirectionnel final.

La baseline utilise une sonde dédiée, pas l'Uno :

```text
Sonde MIDI OUT -> chemin MIDI testé -> renderer MIDI IN
Sonde GPIO     -> UMC404HD entrée 1, uniquement via adaptation de niveau protégée
Audio renderer -> UMC404HD entrées 3/4
```

Pour DDrum4, capturer aussi DDrum4 OUT avec une interface/logic analyzer indépendant afin d'observer le transport. Pour SD3, utiliser une paire de sorties UMC séparée rebouclée vers IN 3/4, ou un loopback préalablement calibré. Confirmer avant chaque run les entrées/sorties indépendantes, l'absence de direct monitoring et toute boucle audio.

Le front GPIO et le premier start bit MIDI ne sont interchangeables qu'après calibration de leur offset. `t0_wire` est le premier start bit, `t3_wire` provient du TX observé (pas d'un appel d'API), et `t6` est le début audio capturé. Ne soustraire DAC/ADC que si le loopback UMC a une calibration répétable. Conserver le WAV brut, les paramètres d'onset et une vérification visuelle des runs de référence. Aucune sonde GPIO, capture MIDI/audio ni écriture vers du matériel n'est implémentée dans M0.
