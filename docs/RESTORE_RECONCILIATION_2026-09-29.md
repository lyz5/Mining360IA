# Restauration locale : état et rapprochement du 29 septembre

Mise à jour : voir [la validation fonctionnelle locale](LOCAL_FUNCTIONAL_VALIDATION_2026-09-29.md). Le réseau NEEMBA permet désormais le bind Active Directory. Des interactions navigateur ont été vérifiées ; le chatbot reste partiel à cause de son profil Codex non authentifié. Les sections ci-dessous conservent le diagnostic initial de restauration.

## État actuel après reprise

**Development démarré ; validation complète encore partielle.** Accès local : `http://127.0.0.1:8001/`. Les sections suivantes conservent le diagnostic initial et le plan de rapprochement.

- Le processus Control Center restant (PID 25048) a été identifié par son interpréteur, module, dossier courant et heure de création. Sa fenêtre encore visible a reçu une fermeture normale ; le processus résiduel a ensuite été arrêté après disparition de la fenêtre. Windows ne signalait plus de détenteur du verrou SQLite.
- Les 23 fichiers de données/configuration/médias/certificats ont été installés et comparés par SHA-256 à la copie extraite. Sauvegarde de l'état remplacé : `.migration-review/restore-20260929/before-restore-20260929-015305/`. L'archive, la copie extraite initiale et la première sauvegarde locale restent conservées.
- Les 19 773 anciennes connaissances sont conservées mais inactives, ainsi que leurs documents/sections/chunks ; Best Practices Bootstrap est désactivé. Aucun enregistrement supprimé. Les revues/corpus de septembre 23–24 ne sont pas présents dans cette archive ancienne.
- Migration additive `codex_chatbot.0004_unified_history` appliquée. Les migrations de suppression `reports.0146` et `0147` ne sont pas appliquées ; l'accord explicite demandé reste en attente.
- `manage.py check` réussi. `manage.py migrate --check` retourne encore 1 à cause des deux migrations en attente.
- Une seule instance applicative écoute sur 8001 (PID 19976), une passerelle sur 443 (PID 14544), un worker actif (PID 25792). Leurs parents respectifs 16932/21952/20148 sont les lanceurs Python du venv, pas trois instances applicatives supplémentaires. Tous ont une identité vérifiée par le contrôleur.
- `/health/` retourne 200 avec `database=ok`, `/login/` retourne 200. Les quatre pages protégées renvoient 302 sans session et 200 avec une session temporaire d'un administrateur existant. Cette session a été supprimée après test ; aucun compte ni rôle créé/modifié. La connexion par mot de passe, les interactions JavaScript, les réponses du chatbot et les scénarios complets ne sont pas validés.
- HTTPS sur boucle locale, avec SNI `mining360-dev.neemba.local` et vérification explicite contre le certificat restauré : 200, base OK. Le magasin de confiance Windows et le DNS n'ont pas été modifiés ; le nom Development ne se résout toujours pas sur cette machine. Cela ne constitue donc pas une validation HTTPS dans le navigateur utilisateur.
- Les journaux des trois composants ne contiennent aucun traceback ni ligne ERROR au contrôle. Le journal Waitress contient des avertissements de délai SQL (`pytds`) ; les connexions externes ne sont pas toutes validées.
- La synchronisation Revenue automatique déjà prévue dans le lanceur a ajouté 106 445 lignes d'un nouvel instantané (total 522 588). Les 416 143 lignes initiales sont présentes, leurs valeurs Revenue et empreintes sont inchangées. Les comptes utilisateurs, intégrations chiffrées, mappings et publications sont identiques à la sauvegarde. L'unique nouvel audit est `Source synchronization` ; aucune publication de mapping effectuée.
- Preuves locales : `.migration-review/restore-20260929/installed-files.json`, `runtime-validation.json`, `protected-data-verification.json`, `retired-knowledge-preserved.json`.

Restent à traiter : décision sur les deux migrations de suppression, validation navigateur/utilisateur et des intégrations, corpus de recherche documentaire Resources. Les PDF ont depuis été rétablis (voir ci-dessous). Aucune restauration complète de l'ensemble de la plateforme annoncée.

### Bibliothèque Ressources rétablie

La sauvegarde de l'ancien projet a été retrouvée sous `C:\Users\diagnepa\OneDrive - NEEMBA\Bureau\Backup Documents\Documents\MBA\Supports CAT\CAT Documentation\Mining360IA`.

- 424 PDF ont été copiés depuis `res/bp` après comparaison avec les empreintes `ResourceKnowledgeDocument` de la SQLite sauvegardée vérifiée.
- 24 autres fichiers étaient illisibles via les entrées OneDrive (erreur d'opération cloud, également constatée avec un alias temporaire de chemin court). Ils ont été récupérés depuis la copie archivée `.runlogs/mining360-bodefm-test-20260804.zip`, uniquement lorsque l'empreinte et la taille étaient strictement identiques aux références de la sauvegarde du 18 septembre. Aucun déploiement BODEFM effectué.
- Contrôle final sur les fichiers installés dans `res/bp` : **448/448 SHA-256 et tailles conformes, 438 empreintes distinctes, zéro fichier manquant ou divergent**. Les sources et copies de staging restent conservées. L'alias temporaire R: a été retiré.
- Validation HTTP avec une session temporaire d'un administrateur existant, supprimée après test : dix pages de catalogue en HTTP 200, 448 liens de documents distincts ; ouverture d'un PDF en HTTP 200, signature PDF et SHA-256 du contenu servi conformes au fichier local.
- Les anciennes connaissances restent inactives (zéro item actif, bootstrap désactivé). Restaurer les PDF ne réactive pas le générateur retiré et n'établit aucune nouvelle couverture de lecture.
- Le corpus `var/resource-memory/corpus.sqlite3` et les revues de septembre 23–24 ne sont toujours pas restaurés. Cela ne bloque pas l'affichage de la bibliothèque de fichiers.
- Preuves : `.migration-review/restore-20260929/resources/final-verification.json`, `fallback-recovery.json`, `http-validation.json`.

### Diagnostic de connexion utilisateur

Le formulaire utilise Active Directory. Les trois derniers audits inspectés indiquent `failed / bind_failed`. Le contrôleur configuré est `BODAD10.ad.neemba.com`, port LDAPS 636. Un diagnostic hors bac à sable échoue à la résolution DNS (`gaierror`), avant toute connexion TLS ou vérification de mot de passe. Le bind du compte technique échoue sur `LDAPSocketOpenError`, sans indication de rejet des identifiants. Le même problème de résolution empêche aussi le contrôle TLS avec le certificat restauré.

Cela établit un blocage de résolution du contrôleur configuré, pas un mot de passe utilisateur incorrect ni un diagnostic définitif de certificat. Vérifier l'accès au réseau/VPN d'entreprise et la résolution interne de ce nom ; si le nom du contrôleur a changé, obtenir le FQDN autorisé avant de modifier l'intégration. Aucun compte, mot de passe, paramètre LDAP, DNS, certificat de confiance ou contrôle d'accès modifié dans ce diagnostic.

## Archive et base vérifiées

- Archive OneDrive `Mining360IA-local-data-2026-09-18.tar.zst` : SHA-256 conforme au handoff (`40050725B4D7FCAC3AC5017404419C42DD849E517700CDA6323D49B8F3FCA20B`).
- Extraction séparée dans `.migration-review/restore-20260929/staging/` après contrôle des 33 entrées (chemins relatifs autorisés, aucun lien).
- SQLite : 5 186 088 960 octets ; SHA-256 `3323F3AFB145828F6458DFB153FD48675489EA67B304B5C609AD21AD1DF1517F`, conforme au manifeste.
- `PRAGMA quick_check=ok`, 232 tables, 168 migrations, 9 utilisateurs.
- Six configurations chiffrées déchiffrables avec la configuration existante ; aucune valeur affichée.
- L'archive contient les médias, cinq fichiers de configuration locale et les certificats ; elle ne contient pas `res/bp` ni le corpus Resources.
- Aucune archive mémoire/authentification Codex utilisée.

## État local préservé et verrou

La base vide locale, ses fichiers annexes et une sauvegarde SQLite cohérente sont conservés dans `.migration-review/restore-20260929/before-restore/`.

La copie vérifiée destinée à l'installation se trouve dans `db.sqlite3.restore-pending`. Le remplacement est bloqué par un verrou Windows sur `db.sqlite3-wal` (WinError 32), bien qu'aucun service reconnu ni écouteur 443/8001 ne soit détecté. La base en place n'a pas été remplacée. La fermeture des fenêtres Control Center a été demandée ; aucun processus non identifié n'a été arrêté.

Windows Restart Manager identifie le détenteur du verrou comme `pythonw.exe`, PID 22364. Aucun arrêt demandé à Restart Manager. Le nom seul n'établit pas son appartenance au projet ; attendre la fermeture des fenêtres concernées et revérifier.

Les certificats extraits inspectés sont actuellement dans leur période de validité (certificat HTTPS Development jusqu'au 12 septembre 2027). Cela ne valide ni la chaîne de confiance Windows, ni la résolution DNS, ni une connexion LDAP/HTTPS. Aucun certificat de confiance installé.

## Migrations du code actuel à examiner

Plan enregistré dans `.migration-review/restore-20260929/migration-plan.txt`.

1. `codex_chatbot.0004_unified_history` ajoute quatre champs de liaison à l'historique des conversations/messages ; aucune suppression.
2. `reports.0146_remove_api_management` retire les tables de l'ancien catalogue API (dont 4 fournisseurs, 2 enregistrements de credentials chiffrés, 180 journaux d'utilisation) et leurs anciens types de contenu/permissions/attributions.
3. `reports.0147_remove_openai_usage` retire les anciennes tables de suivi OpenAI (dont 1 budget, 2 tarifs de modèle, 1 037 journaux d'utilisation) et leurs anciens types de contenu/permissions/attributions.

Les deux dernières migrations sont déjà présentes dans le code reçu, mais pas appliquées à la sauvegarde du 18 septembre. Elles ne publient pas de Business Mapping. Elles suppriment des données et des permissions des modules retirés : compte tenu de la demande de préserver les données et de ne pas changer la sécurité, leur application nécessite un accord explicite sur ce rapprochement local. L'archive et la base extraite d'origine resteraient conservées pour revenir à l'état antérieur. Aucun déploiement Production/BODEFM n'est proposé.

## Connaissances retirées

La base ancienne contient encore 19 773 `ResourceKnowledgeItem`, 448 documents, 27 085 sections et 27 085 chunks, antérieurs au retrait documenté le 23 septembre. Ces éléments ne doivent pas être réactivés comme connaissances valides. Le générateur déterministe est déjà neutralisé dans le code actuel. Avant exposition du chatbot, isoler/désactiver ces anciens enregistrements dans la copie de travail, en conservant leurs données dans la sauvegarde ; ne pas prétendre que les synthèses revues du 23–24 septembre ou le corpus PDF ont été restaurés.

## Validation restante

Libérer le verrou, finaliser la copie locale, traiter les migrations et les connaissances retirées, puis exécuter `manage.py check` et `manage.py migrate --check`, démarrer une seule instance et vérifier les quatre parcours applicatifs. Aucun succès fonctionnel ni restauration complète annoncé à ce stade.
