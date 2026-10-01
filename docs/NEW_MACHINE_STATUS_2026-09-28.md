# Reprise sur la nouvelle machine — 2026-09-28

**Mise à jour du 29 septembre :** l'archive a finalement été téléchargée et vérifiée, les données restaurées et Development démarré. Voir [le compte rendu de restauration du 29 septembre](RESTORE_RECONCILIATION_2026-09-29.md) pour l'état actuel, les contrôles réussis et les limites restantes. Le contenu ci-dessous conserve l'historique du diagnostic.

## Réalisé

- Projet identifié : `C:\Users\diagnepa\Documents\MBA\Mining360IA` ; le sous-dossier `Mining360IA` contient les réglages Django, pas un second dépôt.
- Lecture intégrale du README de migration, du prompt de reprise, de `AGENTS.md` et du handoff du 18 septembre.
- Les 721 fichiers de `SHA256SUMS.txt` sont conformes au paquet reçu. Cette vérification établit la cohérence avec le manifeste fourni, pas une authentification indépendante de son origine.
- Aucun historique `.git` dans le paquet initial. Lecture effective de GitHub : `refs/heads/main` pointe sur `43ece518b10d13e3714995a579ee2993fa4e3f5e`, comme le manifeste.
- Copie Git filtrée de comparaison dans `.migration-review/main-source/` ; aucun reset, checkout ou écrasement des sources de l'instantané. Le répertoire principal reste un instantané sans `.git` ; le dépôt de comparaison possède `origin/main` et son propre historique limité au commit courant.
- Comparaison terminée : 714 fichiers communs ; exactement les trois modifications source annoncées dans le manifeste, toutes conservées. Sept fichiers du manifeste sont propres à l'instantané, dont la documentation de réparation, le test Revenue et les deux sauvegardes SQL ; tous conservés. 637 fichiers ne diffèrent que par les fins de ligne. Résultat : `.migration-review/comparison.json`.
- Deux modules de code absents du ZIP récupérés à l'identique depuis le checkout du commit distant vérifié : `deployment/services/credentials.py` et `desktop/secret_redactor.py`. Leur récupération rétablit les imports sans changer le comportement de sécurité ou de déploiement. Aucun secret privé restauré.
- Les téléchargements Git complets et non filtrés ont été interrompus au profit de la copie filtrée ; leurs répertoires incomplets restent sous `.migration-review/upstream/` et `.migration-review/main-shallow/`. Ils ne constituent pas des copies utilisables du dépôt.
- Python 3.13.15 installé pour l'utilisateur Windows via le catalogue winget ; empreinte de l'installateur vérifiée par winget.
- Environnement dédié créé : `.venv\Scripts\python.exe`. Installation des versions exactes de `requirements.txt` terminée.
- Aucun changement de Production, BODEFM, DNS, magasin de certificats, règles de sécurité ou authentification Codex.

## Testé

- Empreintes : 721 conformes, zéro écart.
- Syntaxe des 515 fichiers Python du manifeste : valide avec Python 3.13.15.
- `.venv\Scripts\python.exe -m pip check` : `No broken requirements found`.
- Inventaire Windows sous le compte utilisateur : aucun écouteur sur 443, 8000, 8001, 8080 et 8443 ; aucun processus python/pythonw/waitress/caddy au moment du contrôle. À refaire immédiatement avant démarrage.
- Premier `manage.py check` en Development, SQLite imposée en lecture seule (`MINING360_SQLITE_PATH=file:db.sqlite3?mode=ro`) pour empêcher la création d'une base vide : échec sur un module absent du ZIP, `deployment.services.credentials`.
- Analyse statique des imports absolus internes : `deployment.services.credentials` et `desktop.secret_redactor` absents. Le résultat est enregistré dans `.migration-review/missing_imports.json`. Cette analyse n'est pas exhaustive des imports dynamiques ou relatifs.
- Après récupération des deux modules : `manage.py check` réussit, zéro problème. Journal : `.migration-review/django-check.log`.
- `manage.py migrate --check` tenté avec le même garde-fou SQLite en lecture seule : code retour 1, `OperationalError: unable to open database file`. Il s'agit de l'absence de base, pas d'une vérification réussie des migrations. Journal : `.migration-review/migrate-check.log`. Aucune base créée.
- Résolution Django des quatre routes demandées : réussie ; import du module de masquage du Control Center : réussi. Ce contrôle ne teste ni authentification, ni données, ni interactions navigateur.
- Contrôle final : toujours aucun écouteur sur les cinq ports contrôlés, aucun processus Git/Python/Waitress remonté par l'inventaire ciblé. La copie Git filtrée est propre. Les 721 fichiers initiaux conservent leurs empreintes.
- Versions installées enregistrées dans `.migration-review/installed-requirements.txt`.

## Non testé

- `manage.py migrate --check` sur une base restaurée.
- Intégrité et contenu d'une sauvegarde des données ; déchiffrement des configurations d'intégration.
- Parcours authentifiés et données réelles : Business Overview (`/business-review/command-center/`), Excellence Center (`/excellence-center/`), Reporting (`/reporting/`) et M360 Chatbot (`/codex-chatbot/`).
- HTTPS local, intégrations externes, worker du chatbot et journaux d'un service démarré.

## Bloqué

- Le chemin de la sauvegarde séparée et de son manifeste d'empreintes a été demandé ; il n'est pas encore fourni.
- `db.sqlite3`, `media/` et `local-config/` sont absents du projet. Aucune base vide créée et aucune donnée inventée.
- Les configurations privées, clés de chiffrement, certificats, journaux historiques et PDF Resources ne sont pas inclus dans le ZIP.
- Le démarrage Development et la validation complète restent bloqués par l'absence des données et de la configuration privée vérifiées. Aucun service applicatif démarré.

## Risques

- Une installation Python réussie ne constitue pas une restauration applicative.
- Les empreintes du ZIP ne valident pas une sauvegarde séparée.
- Le handoff du 18 septembre cite une ancienne sauvegarde ; sa fraîcheur et sa couverture doivent être établies avant usage.
- Le déchiffrement des intégrations exige la clé originale appropriée, sans l'afficher ni la versionner.
- Certains tests ont été volontairement omis du ZIP ; aucune équivalence avec la validation historique de l'ancienne machine n'est revendiquée.
- 1 447 chemins suivis dans le dépôt distant sont absents du manifeste du ZIP ; seuls les deux modules nécessaires aux imports ont été récupérés. Ce nombre inclut des éléments hors du périmètre de l'instantané, et ne signifie pas 1 447 modules applicatifs manquants. Ne pas recopier aveuglément les autres fichiers ; examiner leur nature avant récupération.

## Prochaine action

1. Fournir le chemin de la sauvegarde séparée et son manifeste SHA-256, sans envoyer de secrets dans la conversation.
2. Vérifier les empreintes avant extraction, inspecter les chemins de l'archive et travailler dans un répertoire de staging. Sauvegarder toute base/configuration existante avant remplacement. Ne restaurer aucun profil d'authentification Codex.
3. Pour l'archive historique exactement nommée `Mining360IA-local-data-2026-09-18.tar.zst`, le handoff fournit SHA-256 `40050725B4D7FCAC3AC5017404419C42DD849E517700CDA6323D49B8F3FCA20B`. Ne pas appliquer cette empreinte à une archive plus récente ou différente.
4. Valider SQLite en lecture seule et la cohérence des clés/configurations ; restaurer uniquement les éléments vérifiés et autorisés, sans installer de certificats de confiance.
5. Exécuter les contrôles Django avec `.venv\Scripts\python.exe manage.py check` puis `manage.py migrate --check`. Examiner d'éventuelles migrations en attente avant toute application.
6. Recontrôler les propriétaires des ports et démarrer une seule instance Development. Vérifier les quatre parcours avec les droits existants, les journaux et les processus identifiés.
7. Conserver l'ancien poste, les sauvegardes et l'instantané jusqu'à validation complète.

**Restauration complète non réalisée.**

## Incident suivant : démarrage depuis le Control Center

Après le bilan initial ci-dessus, l'utilisateur a tenté le démarrage le 28 septembre à 18:36. Les journaux `launcher-20260928-183637-*.log` montrent que Waitress a écouté sur 127.0.0.1:8001, mais que le worker s'est arrêté sur `OperationalError: no such table: codex_run`. Le Control Center a enregistré `completed_with_warnings`, malgré cette installation incomplète.

Une base `db.sqlite3` de 4 096 octets existe désormais ; inspection en lecture seule : `quick_check=ok`, **zéro table**. Cette base n'est pas une restauration des données et a été conservée sans migration ni remplacement. Les deux fichiers HTTPS attendus dans `.runlogs/dev-https/` sont absents.

Le port 8001 était occupé par `python.exe`, PID 24828, parent 8996, tous deux créés à 18:36:37. L'inventaire Windows accessible ne fournit pas leur exécutable/ligne de commande ; le contrôleur ne peut donc pas prouver leur appartenance au projet. Aucun arrêt forcé et aucun second service lancé.

Correctif local : ajout de `desktop/database_preflight.py`, appelé avant le lancement par `desktop/control_core.py` et `desktop/dev_runtime.py`. Il ouvre SQLite en lecture seule et refuse une base absente, illisible ou dépourvue des tables minimales `django_migrations`, `auth_user`, `codex_run`. Le contrôle ne crée pas de base et ne remplace pas une validation complète des migrations, données et secrets. Les fichiers de code ainsi modifiés constituent de nouveaux changements locaux, distincts des travaux déjà inclus dans le ZIP.

Validation : 13 tests réussis (`desktop.test_database_preflight` et `desktop.test_service_lifecycle_manager`) ; `manage.py check` réussi. Le garde-fou rejette effectivement la SQLite vide actuelle. L'interface déjà ouverte doit être fermée puis rouverte pour charger le correctif ; sa fermeture ne garantit pas l'arrêt de services enfants existants.

Blocage restant : sauvegarde réelle et empreintes toujours nécessaires. Aucun parcours applicatif réel validé. Fournir leur chemin pour reprendre la restauration, puis identifier à nouveau le propriétaire du port avant tout démarrage ou arrêt.

## Sauvegarde retrouvée sur cette machine

Le dossier existe sous `C:\Users\diagnepa\OneDrive - NEEMBA\Bureau\Backup Documents\Mining360IA-Transfer-2026-09-18` (et non sous l'ancien nom OneDrive RESDELMAS).

L'inventaire affiche `Mining360IA-local-data-2026-09-18.tar.zst` (999 504 255 octets annoncés), `backup-manifest.json` et `RESTORE_INSTRUCTIONS.txt`, ainsi qu'une archive mémoire Codex qui ne doit pas être restaurée. Toutefois, la lecture des deux fichiers texte et le calcul SHA-256 de l'archive échouent avec l'erreur Windows **« L'opération de cloud n'est pas valide »**, même hors bac à sable. Les entrées OneDrive sont présentes, mais leur contenu n'a pas pu être lu ni vérifié. Aucune extraction effectuée.

Prochaine action : rendre ce dossier disponible localement via OneDrive (ou télécharger l'archive et son manifeste depuis OneDrive Web), puis refaire la vérification SHA-256 avant restauration.

### Nouvelle vérification du dossier indiqué par l'utilisateur

`RESTORE_INSTRUCTIONS.txt` et `backup-manifest.json` sont désormais lisibles. Le manifeste annonce une base de 5 186 088 960 octets, SHA-256 `3323F3AFB145828F6458DFB153FD48675489EA67B304B5C609AD21AD1DF1517F`, 168 migrations, 9 utilisateurs et 416 143 lignes Revenue (106 112 actives) au moment de la sauvegarde du 18 septembre. Ce sont les déclarations du manifeste, pas des contrôles effectués sur une base extraite.

L'archive de 999 504 255 octets est toujours signalée `Offline=True`, `Pinned=True`, `RecallOnDataAccess=True` par Windows : la demande de disponibilité locale est enregistrée, mais son contenu reste à récupérer via OneDrive. Le calcul SHA-256 n'a pas encore fourni de résultat. Aucune extraction ni restauration faite. L'archive mémoire Codex demeure exclue de la restauration.

Le nouvel inventaire de processus ne détecte aucun service Mining360 et aucun écouteur sur 443/8001. Cet état devra être recontrôlé au moment de la restauration.
