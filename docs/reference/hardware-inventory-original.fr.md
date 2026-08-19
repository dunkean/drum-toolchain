### Éléments de batterie

| Élément            | Modèle / type     |                           Zones / fonctions | Usage prévu                     |
| ------------------ | ----------------- | ------------------------------------------: | ------------------------------- |
| Kick               | DDrum mesh        |                                      1 zone | Kick principal                  |
| Snare principale   | DDrum mesh (capteur central)        |              Head + rim, positional sensing | Snare principale                |
| Snare secondaire     | DDrum mesh std capteur latéral        |                                  Head + rim | 4e tom ou seconde snare         |
| Tom 1              | DDrum mesh        |                                        Head | Tom aigu                        |
| Tom 2              | DDrum mesh        |                                        Head | Tom medium                      |
| Tom 3              | DDrum mesh        |                                        Head | Tom grave                       |
| Hi-hat principal   | ZEITGEIST ZG H-12 | Bow/edge + ouverture continue + foot splash | Hi-hat expressif principal      |
| Ride               | Millenium CR-18X  |         3 zones prévues : bow / edge / bell | Ride principale                 |
| Crash expressive 1 | Millenium CC-15X  |                             2 zones + choke | Crash principale                |
| Crash expressive 2 | Millenium         |                             2 zones + choke | Crash secondaire                |
| Crash 3            | Millenium         |                                      1 zone | splash |
| Cymbale compacte   | Yamaha PCY10      |                            Cymbale compacte  1 zone| Splash          |
| 1/2 Cymbale    | Yamaha PCY10      |                            1 zone | stack          |
| Cymbales DDrum 1    | DDrum4            |                                1/2 zone + choke | china / effets |
| Cymbales DDrum 2    | DDrum4            |                                Selon modèle | china / effets |
| Ancien hi-hat      | DDrum             |                              Trigger simple + potentiellement pédale| Percussion / crash / china / splash / son alternatif     |




### Périphériques / électronique

| Périphérique              | Modèle                                           | Fonction dans le setup                                                                       |
| ------------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| Module sonore / trigger   | DDrum4 SE                                        | Module standalone, lecture de la soundbank Clavia, cible principale du projet nested sounds  |
| Trigger interface         | DDTi                                             | Conversion pads → MIDI pour une partie du kit                                                |
| Trigger interface avancée | eDRUMin 4                                        | Gestion des triggers exigeants : hi-hat continu, positional sensing, cymbales multi-zones    |
| Microcontrôleur           | Arduino + MIDI shield                            | Traduction MIDI temps réel, conversion DDTi/eDRUMin → mapping nested DDrum4                  |
| MIDI merger               | MIDI merger hardware                             | Fusion des flux MIDI avant Arduino / DDrum4 selon le routage                                 |
| Ordinateur batterie       | Laptop XPS 15, Core i9, 64 GB RAM                | Superior Drummer 3, outils de configuration, développement du projet                         |
| Audio interface           | Behringer U-Phoria UMC404HD                      | Sortie audio faible latence, jusqu'à 4 line outputs                                          |
| Mixer live                | Behringer XR18                                   | Mix batterie / groupe, retours et envoi FOH                                                  |
| Drum software principal   | Superior Drummer 3                               | Moteur batterie principal sous Windows                                                       |
| Drum software alternatif  | DrumGizmo                                        | Moteur libre sous Linux / solution alternative                                               |
| Drum libraries            | SD3 + Death + Metal Machinery + EZX Modern Metal | Metalcore, prog, Deftones, Sleep Token-like                                                  |
| Soundbank standalone      | DDrum4 / Clavia, ~8 MB                           | Kit autonome optimisé sans ordinateur                                                        |
| Futur software            | Projet Codex                                     | Édition de soundbanks Clavia, nested sounds, génération de mappings et configuration Arduino |


| Famille                  | Élément du **kit augmenté cible**                                                                | Zones / articulations souhaitées                 | Variations / sons alternatifs                          | Remarque                                                  |
| ------------------------ | ------------------------------------------------------------------------------------------------ | ------------------------------------------------ | ------------------------------------------------------ | --------------------------------------------------------- |
| **Kick**                 | Kick principal                                                                                   | 1 zone, vélocité complète                        | Kick metal acoustique                                  | Son principal                                             |
|                          | Kick alternatif                                                                                  | 1 zone                                           | Electro / processed / sub kick                         | Peut être sélectionné par preset ou nested sound          |
| **Snare**                | Snare principale                                                                                 | Head + rim + idéalement positional sensing       | Plusieurs velocity layers                              | Snare metalcore moderne                                   |
|                          | Snare alternative                                                                                | Head + rim                                       | Industrial / high-pitched / decimated                  | Peut dériver de la snare principale avec pitch/processing |
| **Toms**                 | Tom 1                                                                                            | Head                                             | Normal + low-pitched                                   | Aigu                                                      |
|                          | Tom 2                                                                                            | Head                                             | Normal + low-pitched                                   | Medium-aigu                                               |
|                          | Tom 3                                                                                            | Head                                             | Normal + low-pitched                                   | Medium-grave                                              |
|                          | Tom 4                                                                                            | Head                                             | Normal + low-pitched                                   | Grave / floor tom                                         |
| **Hi-hat**               | Hi-hat principal                                                                                 | Bow + edge + ouverture continue                  | Closed → half-open → open                              | Expressif via ZEITGEIST + eDRUMin                         |
|                          | Hi-hat articulations                                                                             | Pedal chick + foot splash                        | —                                                      | À conserver dans le mapping nested                        |
|                          | Hi-hat alternatif                                                                                | 1 zone                                           | Trap / electronic HH                                   | Petit sample, coût mémoire faible                         |
| **Ride**                 | Ride principale                                                                                  | Bow + edge + bell                                | Éventuellement crash-ride                              | 3 zones                                                   |
| **Crash**                | Crash 1                                                                                          | Bow + edge/choke                                 | —                                                      | Crash expressive principale                               |
|                          | Crash 2                                                                                          | Bow + edge/choke                                 | —                                                      | Crash expressive secondaire                               |
| **Splash**               | Splash 1                                                                                         | 1 zone                                           | —                                                      | Petite cymbale                                            |
|                          | Splash 2                                                                                         | 1 zone                                           | —                                                      | Timbre différent                                          |
| **China**                | China 1                                                                                          | 1 zone                                           | —                                                      | China principale                                          |
|                          | China 2                                                                                          | 1 zone                                           | —                                                      | Autre taille/pitch                                        |
| **Stack**                | Stack                                                                                            | 1 zone                                           | éventuellement plusieurs traitements                   | Son court / agressif                                      |
| **Percussion**           | Percussion supplémentaire                                                                        | 1 zone                                           | Cowbell / metallic / FX selon preset                   | Peut utiliser l'ancien hi-hat DDrum                       |
| **Electro**              | Clap                                                                                             | 1 zone                                           | Plusieurs claps éventuellement                         | Très faible coût mémoire                                  |
|                          | Click / rim électronique                                                                         | 1 zone                                           | Click, stick, glitch                                   | Pour patterns electro/industrial                          |
|                          | Impact / FX                                                                                      | 1 zone                                           | Noise, hit, reverse, etc.                              | Selon mémoire disponible                                  |
| **Total physique cible** | **Kick + 2 snares + 4 toms + hi-hat + ride + 2 crash + 2 splash + 2 china + stack + percussion** | **≈18 éléments physiques, avec zones multiples** | + sons electro accessibles par nested mappings/presets | Kit pensé pour metalcore/prog + extensions electro        |


A VISER >>> 

Initialement: Des variations sur le kit doivent exister avec :
- 1 kit principal Metalcore
- 1 snare alternative type deftones (plus aigu et reverb)
- 1 modification de mix et potentiellement snare/tom pour un kit orienté "Sleep Token"
- des kits electro/drum n bass: > 1 snare DnB et potentiellement 1 snare electro, un kick ou 2 electro, des charley electro et des sons FX tous petits partout. Les cymbales bougent pas.

La batterie idéale pour sd3 en mix unique (on change les notes coté midi pour changer le kit et meme des CC pour gerer de l'automation de transition):

Ca veut dire que chaque son peut avoir des variants:

En gros je veux 
- 1 kit cymbales avec variants Electro
- 1 kit de fûts + snare Metalcore pur (avec une variation caisse claire pour claquer - facon deftone)
- 1 kit de fûts + snare "Sleep Token" qui sonne plus
- 1 kit Electro DnB avec des variants HiHat, Snare, Kick


Cymbales en détails (commune metalcore/sleep token/et quasi Electro):
- 2 main crash low/hi
- 1 crash mid | variants: des FXs pour kit electro/DnB
- 1 Ride | Variants: Ride(s) Electro
- 2 splash, 2 china
- 1 stack | variant: Bell, FXs pour electro/DnB
- 1 hat | variants: plusieurs hat electro/DnB

Kit:
- 4 toms (1 version Metalcore, 1 version SleepToken, 1 version DnB
- 1 snare Metalcore, 1 snare SleepToken, 1 snare variant Deftones, des variants snares DnB/Electro (surtout DnB)
- 1 kick metalCore/sleeptoken | Des kicks electros


Les variants electro devrait s'orienter vers 4 genres:
- Drum n Basse avec bmp rapide et caisse claire typique
- Trap: charley typique et kick aussi
- Beat planant genre Chillout
- Synthwave

JE sais pas comment tout se mélange, mais si je pouvais avoir un unique midimap avec ca et router les notes avec le modernizer en fonction du kit choisi se serait parfait !!!


