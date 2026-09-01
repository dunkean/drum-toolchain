# Greg Hybrid — MIDI map pour les kits SD3 standards

Le preset e-drum `Greg_Hybrid_Standard_SD3_Kits` permet de conserver le
Converter et son namespace SD3 custom tout en chargeant un autre kit ou une
autre extension dans Superior Drummer 3. Il ne remplace pas le MegaKit : il
traduit ses notes renderer vers les rôles standards du kit actuellement
chargé.

Deux modes sont donc exclusifs :

- **MegaKit v23/capture** : `Kit_Metalcore_MidiMapping_Capture_V1` ;
- **autre kit ou extension SD3** : `Greg_Hybrid_Standard_SD3_Kits`.

Toujours remettre le premier avant une calibration ou une capture du MegaKit.

## Chargement dans SD3

1. Charger le kit ou preset SD3 souhaité.
2. Ouvrir la page **Settings / MIDI In-E-Drums / MIDI Mapping**.
3. Choisir le preset utilisateur `Greg_Hybrid_Standard_SD3_Kits`.
4. Laisser le Converter sur sa cible `sd3` et le canal renderer 10.

Le fichier installé se trouve dans
`Documents\Toontrack\Superior3\EdrumPresets\Greg_Hybrid_Standard_SD3_Kits`.
Si SD3 avait déjà ouvert la liste des presets pendant l'installation, fermer
puis rouvrir cette liste, ou redémarrer SD3 une fois.

## Résolution portable

| Entrées du renderer | Destination du kit chargé |
|---|---|
| 24–28 | kick principal |
| snares 32–55 | snare head, rimshot, cross-stick ou position |
| toms 52–63 | quatre niveaux de toms standards |
| 64–69 + CC4 | hi-hat bow, edge, chick, splash et ouverture continue |
| 72–76 | trois crashes |
| 77–78 | position splash |
| 79–82 | deux positions china |
| 83–84 | ride bow et bell |
| 85/89 | stack ramenée sur une troisième crash |
| 88/92/93 | cowbell/percussion standard |
| 50/99 et 51 | clap et sidestick |

Les variantes Sleep, Deftones, DnB, Industrial et Electro deviennent donc le
rôle acoustique équivalent lorsque ce preset est actif. Par exemple tous les
kicks custom jouent le kick du kit chargé, et toutes les snares de scène jouent
sa snare principale.

Les positions optionnelles restent celles de la topologie complète
(`Crash2`, `Crash5`, `Crash4`, `Splash3`, `China2`, `China6`, `Ride4`). Si un
kit SD3 ne charge aucun instrument dans l'une de ces positions, ce pad sera
silencieux jusqu'à l'ajout d'un instrument dans la position correspondante.
Les éléments fondamentaux kick/snare/toms/hi-hat/ride restent indépendants de
ces positions optionnelles.

## Reproduction sur un autre PC

Depuis la racine du dépôt :

```powershell
.\scripts\install-greg-hybrid-standard-sd3-map.ps1 -ConfirmInstall
```

Ajouter `-Force` uniquement pour remplacer une version déjà installée. Le
générateur refuse les notes manquantes, supplémentaires ou dupliquées par
rapport au plan du MegaKit.
