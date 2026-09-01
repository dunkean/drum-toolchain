# Greg Hybrid Live — archive Windows portable

1. Décompresser l'archive sur le laptop Windows 11 x64.
   Avant extraction, comparer le SHA-256 du ZIP avec le fichier `.zip.sha256`
   transféré à côté de l'archive (`Get-FileHash <archive.zip> -Algorithm
   SHA256`). Cette empreinte doit elle-même provenir de la machine de build ou
   d'un canal de confiance.
2. Lancer `Install-Live-Rig.cmd`. L'installation se fait sans droits
   administrateur sous `%LOCALAPPDATA%\GregHybridLive\versions` et crée trois
   raccourcis sur le Bureau.
3. Une fois la campagne de pads terminée et le bundle marqué
   `hardware-verified`, lancer `Configure-Live-Rig.cmd` pour sélectionner la
   sortie MIDI de SD3 et déclarer le buffer UMC/ASIO réellement vérifié.
4. Utiliser `Greg Hybrid - Live` pour démarrer. Le préflight refuse de lancer
   quoi que ce soit si un port, un chemin, un hash ou le profil live manque.
5. Utiliser `Greg Hybrid - Stop Live` pour arrêter uniquement les processus
   possédés par le lanceur et restaurer le plan d'alimentation.

`Test-Live-Rig.cmd` valide le runtime Python embarqué, tous les outils, le
Converter et le profil compilé sans ouvrir de port MIDI. Les anciennes versions
installées sont conservées pour permettre un retour arrière. Une nouvelle
version n'est rendue active et ses raccourcis ne sont remplacés qu'après le
succès de ce diagnostic.

Le runtime et tous ses wheels Windows sont verrouillés par SHA-256 au build.
Le scope partageable refuse aussi automatiquement les fichiers audio, presets
privés et archives de kit présents par accident dans son payload.

Le scope `private-with-assets` peut contenir le preset SD3 utilisateur et le
kit DrumGizmo dérivé. Cette archive est réservée au laptop de son propriétaire,
ne doit pas être publiée et ne remplace pas l'installation/licence des produits
Toontrack ou d'un hôte DrumGizmo.
