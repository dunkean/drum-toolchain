# ddrum4 Converter

Routeur MIDI temps réel ddrum4 → SD3/DrumGizmo, avec position de snare, CC, trois kits virtuels et Program Change local.

## Démarrage Windows

```powershell
cmake -S . -B build -G Ninja
cmake --build build --target ddrum4_converter
./build/ddrum4_converter_artefacts/Debug/'ddrum4 Converter.exe'
```

Le routeur charge `config/ddrum4-template.yaml` à côté de l'exécutable (ou depuis le dépôt en développement). L'onglet **Mapping** permet de modifier ce YAML et de l'appliquer : le routage est arrêté, le profil est validé, puis il peut être redémarré. Les erreurs de schéma, chevauchements de notes, valeurs CC et bindings PC sont refusés avant toute ouverture MIDI.

L'interface reste volontairement compacte : **Jeu** (ports, trois kits, Panic), **Programmes** (kits virtuels), **Mapping** (profil) et **Monitor** (flux entrant et nombre d'événements produits). Les Program Changes sont locaux par défaut ; passe `forward_program_change: true` si SD3 doit aussi les recevoir.

Le template contient aussi un exemple `hihat_continuous` : il calibre un CC entrant (`input_cc`, typiquement CC4) entre `closed_value` et `open_value`, et l'émet sur `output_cc`. `hihat_discrete` utilise au contraire `cc_values` sur une plage de notes pour synthétiser le CC d'ouverture avant la note d'articulation.

Sur Windows, crée d'abord un port loopMIDI nommé `ddrum_converted`, sélectionne le MIDI OUT du ddrum4 comme entrée, puis ce port comme sortie. Dans SD3, sélectionne `ddrum_converted` comme entrée MIDI et sauvegarde un preset e-drums dédié.

Pour un profil `rig-runtime-profile/v1`, le lancement supervisé utilise trois
variables de processus : `DDRUM4_RUNTIME_PROFILE`, `DDRUM4_RENDERER_TARGET`
et `DDRUM4_RENDERER_OUTPUT`. La dernière doit correspondre exactement et une
seule fois à un MIDI OUT visible. Le Converter ouvre alors toutes les entrées
du profil, le renderer et le bus global CH15, publie Scene/VP, puis démarre le
routage sans clic manuel. Une sortie absente ou ambiguë laisse le routeur
arrêté avec une erreur lisible.

## CLI

```powershell
./build/ddrum4ctl validate config/ddrum4-template.yaml
./build/ddrum4ctl programs config/ddrum4-template.yaml
./build/ddrum4ctl list config/ddrum4-template.yaml
./build/ddrum4ctl benchmark config/ddrum4-template.yaml
```

`PC 0`, `PC 1` et `PC 2` sélectionnent respectivement `Core`, `Metal` et `Electro`, sans relayer le Program Change vers SD3.

Les aides d'intégration sont fournies dans [config/sd3-default.md](config/sd3-default.md) et [config/drumgizmo-note-map.yaml](config/drumgizmo-note-map.yaml). Elles restent volontairement des points de départ : capture tes propres notes ddrum4 avant de marquer le profil comme validé.
