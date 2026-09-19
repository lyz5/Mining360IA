# Control Center — vérification du 19 septembre 2026

**Mise à jour ultérieure : HTTPS local configuré et validé après autorisation utilisateur.** `https://mining360-dev.neemba.local/` ouvre la page de connexion dans Microsoft Edge sans ignorer les erreurs TLS. `/health/` : HTTP 200, application et base OK. Le Control Center détecte désormais HTTPS en ligne. Seules la résolution hosts locale et la confiance du certificat existant dans le magasin utilisateur ont été ajoutées ; Production, base et pare-feu inchangés. Preuves : `../local-https-results.json` depuis la racine du dépôt. L'état incomplet décrit ci-dessous correspond au bilan avant cette autorisation.

**application locale opérationnelle, HTTPS non configuré**

## Réalisé

- Application conservée dans `C:\Users\diagnepa.NEEMBA\Documents\MBA\Supports CAT\CAT Documentation\Mining360IA\runtime` ; base existante `runtime\db.sqlite3`.
- Python effectif : `Mining360IA\.venv\Scripts\python.exe` (3.14.7), avec l'interpréteur de base `C:\Python314\python.exe`. Sous Windows, les processus enfants de redirection du virtualenv apparaissent avec ce dernier exécutable : leur ligne de commande désigne bien le virtualenv.
- Les deux lanceurs PowerShell sélectionnent explicitement `.venv` dans le dépôt, ou dans son parent pour cette restauration. Aucun repli sur le Python global.
- Le raccourci Bureau `Mining360 Control Center.lnk` ouvre `runtime\deployment\windows\Mining360 Control Center.cmd`, avec `runtime` comme dossier de travail. Le lanceur CMD utilise le Python graphique du même virtualenv. Aucune modification de la politique d'exécution PowerShell.
- Le Control Center et les services partagent `desktop/project_environment.py`. `desktop/dev_runtime.py` lance Waitress, le worker et, si le certificat existant convient, la passerelle locale. La dépendance `psutil==7.2.2` est déclarée et installée dans le virtualenv.
- PowerShell/JSON : UTF-8 explicite aux deux extrémités. `netstat` et `certutil` : encodage OEM Windows distinct.
- L'identité des processus repose sur les informations vivantes : PID, date de création, dossier courant, exécutable et arguments. Le manifeste ancien ne donne aucun droit d'arrêt. Nouvelle validation juste avant arrêt ; aucun arrêt par port seul, aucune terminaison récursive de descendants inconnus.
- Un démarrage avec l'application locale déjà saine ne crée pas une deuxième instance si HTTPS manque. Un verrou Windows sérialise les nouveaux démarrages.
- Le démarrage ne lance plus `setup_dev_https.py`. L'installation de confiance par cet outil nécessite désormais l'option explicite `--install-trust`. Cette option n'a pas été exécutée.
- L'interface affiche l'état local/HTTPS distinct et permet d'ouvrir l'application locale. L'ancienne fenêtre utilisant le Python global a été fermée normalement après vérification de son identité.
- Aucun changement de Production, DNS, hosts, certificat, magasin de confiance ou pare-feu. Aucun ancien dossier supprimé.

## Testé

- 19 tests unitaires Control Center/lifecycle réussis : PID réutilisé, ancien manifeste, port inconnu, identité changée avant arrêt, chemins accentués avec espaces, absence de duplication et avertissement HTTPS au redémarrage.
- Aller-retour réel PowerShell → JSON → Python avec `Données été avec espaces\certificat été.json` : identique.
- Lecture réelle de `netstat` OEM et reconnaissance des six processus existants : réussies.
- Arrêt, démarrage, puis redémarrage réels par le gestionnaire utilisé par l'interface : réussis. Démarrage et redémarrage terminés avec le seul avertissement HTTPS.
- Ports libérés après arrêt ; un seul processus écoute sur 8001 après démarrage/redémarrage. `/health/` retourne `status=ok`, `application=Mining360`, `database=ok`.
- Même fichier SQLite avant/après, 9 utilisateurs et 168 migrations enregistrées avant/après. Aucune migration appliquée.
- Contrôles Django `check` et `migrate --check` exécutés via les commandes de gestion : réussis. `pip check` : réussi.
- Ouverture réelle du raccourci : fenêtre V2 visible, virtualenv et dossier courant vérifiés, détection des services visible, message local/HTTPS visible.
- Journaux de l'interface et des nouveaux services : aucune `UnicodeDecodeError`, aucune traceback dans le journal de l'interface.
- Analyse syntaxique des deux lanceurs PowerShell : aucune erreur.

Preuves locales : `../control-center-live-results.json` et `../control-center-ui-results.json` depuis la racine du dépôt ; capture `.artifacts/restoration/control-center-repaired.png`.

## Non testé

- Accès HTTPS depuis d'autres postes et validation DNS/TLS complète : configuration volontairement non appliquée.
- Exécution directe des fichiers `.ps1` sous la politique restrictive actuelle : seul le raccourci CMD sans changement de politique a été exécuté ; le moteur Python partagé a été testé réellement.
- Les scénarios métier complets et la génération IA n'ont pas été rejoués pendant cette réparation du Control Center.

## Bloqué

- `https://mining360-dev.neemba.local/` reste non validé : résolution du nom et confiance utilisateur à configurer après levée de la restriction.

## Risques

- L'adresse réseau observée peut changer ; ne pas la publier dans le DNS sans réservation/validation réseau.
- Une instance non identifiable bloque volontairement les opérations de cycle de vie. Ne jamais contourner ce contrôle en arrêtant le seul propriétaire d'un port.
- Les corrections sont locales et non publiées sur Git. Les sauvegardes et anciens dossiers sont conservés.

## Prochaine action

Utiliser le raccourci Bureau et `http://127.0.0.1:8001/`. Appliquer ultérieurement le plan `DEVELOPMENT_HTTPS_PENDING.md`, selon le périmètre local ou réseau choisi, puis refaire les contrôles DNS/TLS depuis les clients concernés.
