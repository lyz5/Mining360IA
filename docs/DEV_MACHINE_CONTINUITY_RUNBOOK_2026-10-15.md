# Continuité et changement du poste de développement

Version du 15 octobre 2026.

L'exposition quantitative courante est enregistrée dans
`docs/DEV_MACHINE_LOSS_EXPOSURE_2026-10-15.md`. La consulter avant de déclarer
qu'une migration ou une sauvegarde est complète.

L'architecture cloud cible est définie dans
`docs/CLOUD_BACKUP_TARGET_ARCHITECTURE_2026-10-15.md` : Azure Blob Storage pour
les sauvegardes, Azure Key Vault pour les secrets, avec des périmètres séparés
pour Neemba et les projets personnels/Pac Digitale.

## Objectif

Permettre de remplacer le poste de développement sans perdre le code, les bases et fichiers métier, les configurations et credentials, les environnements, les procédures, les connaissances et les preuves de validation.

Le processus sépare strictement **code**, **données**, **secrets**, **outils** et **connaissances**. Une copie Git ne suffit pas à restaurer l'environnement complet.

## 1. Sources de vérité

| Catégorie | Source primaire | Copie de continuité |
| --- | --- | --- |
| Code | Dépôts Git de chaque projet | Git distant + bundle Git chiffré périodique |
| Documentation | `AGENTS.md`, handoffs et dossiers `docs/` versionnés | Git + archive documentaire chiffrée |
| Bases | Backups natifs SQLite/MySQL/SQL Server | Archive chiffrée avec checksums |
| Médias | Dossiers `media`, uploads WordPress et documents applicatifs autorisés | Archive chiffrée séparée |
| Secrets | Gestionnaire de mots de passe ou coffre approuvé | Export chiffré hors Git, mot de passe conservé séparément |
| Outils | Manifeste de versions, `winget export`, requirements et configuration IIS/SQL | Dossier de continuité non secret |
| Preuves | `.runlogs`, `.artifacts` et dossiers de migration sélectionnés | Archive chiffrée ; ne pas tout publier dans Git |

## 2. Risques actuels identifiés

1. La copie de travail Mining 360 n'a pas de métadonnées Git actives à sa racine. Un clone propre existe dans `.migration-review/git-publish`, arrêté au commit du 1er octobre 2026. Les évolutions ultérieures doivent être réconciliées dans le dépôt principal.
2. `db.sqlite3` Mining 360 et son WAL sont volumineux et actifs. Une simple copie pendant l'exécution peut être incohérente.
3. `BODEFM.txt`, `mysql_access`, `.env.local`, `wp-config.php` et les configurations locales Mining 360 contiennent ou référencent des secrets ; ils ne doivent pas être placés dans Git ou dans un zip non chiffré.
4. Les médias Mayite et DSTV de production ne font pas partie des sauvegardes de source PythonAnywhere.
5. Miningprod_test distant est un snapshot, pas une synchronisation automatique ni une sauvegarde suffisante pour le développement local.
6. SQL Server 2025 Enterprise Developer `17.0.1000.7` a été installé le 15 octobre alors que la dernière preuve BODEFM confirme SQL Server 2022 Developer 16.x. Aucune base applicative ne doit y être migrée avant la décision d'alignement.

## 3. Sauvegarde par projet

### Mining 360

- Commit/push du code et des documents après réconciliation du dépôt.
- SQLite : utiliser l'API de backup SQLite ou arrêter proprement le runtime avant copie coordonnée du fichier et du WAL. Vérifier `PRAGMA quick_check` sur la copie.
- Après passage local à SQL Server : `BACKUP DATABASE ... WITH COPY_ONLY, COMPRESSION, CHECKSUM`, puis `RESTORE VERIFYONLY WITH CHECKSUM`.
- Sauvegarder `media/`, configurations locales autorisées et certificats dans le paquet chiffré.
- Conserver la clé permettant de déchiffrer `SystemIntegrationConfig.encrypted_secrets`. Sans elle, une copie de la base ne restaure pas les intégrations.

### MiningProd local

- Sauvegarder le code de l'application locale et le `web.config` local séparément.
- Backup SQL Server natif de `Miningprod_test` avec checksum et test de restauration.
- Exporter l'inventaire IIS du site, du pool, des bindings et des ACL sans mot de passe.
- Ne jamais réutiliser le backup local comme remplacement automatique de la production.

### Mayite et DSTV

- Commit/push de la source et des handoffs.
- Export MySQL cohérent avec `mysqldump --single-transaction --routines --triggers --events`.
- Sauvegarder les médias autorisés séparément lorsqu'ils seront restaurés.
- Inclure `.env.local` et la configuration MySQL uniquement dans le paquet chiffré.
- Conserver requirements, version Python et procédure de démarrage locale.

### Site Pacdigitale

- Commit/push du thème et de sa documentation.
- Export MySQL WordPress.
- Sauvegarde séparée de `wp-content/uploads` et inventaire des plugins/thèmes actifs.
- `wp-config.php` local/production uniquement dans le paquet chiffré, jamais dans Git.

### Marketing Digital

- Committer les stratégies, analyses, créations autorisées et exports non sensibles.
- Préserver séparément les exports Ads Manager bruts, captures et originaux ; ne jamais les écraser par des fichiers calculés.
- Conserver les accès Meta, tokens, identifiants de compte et données d'audience dans le coffre approuvé, jamais dans Git.
- Produire un export natif des campagnes et un manifeste SHA-256 avant changement de machine.
- Le dépôt local sans remote doit être inclus dans l'archive de continuité et recevoir un remote privé approuvé avant migration définitive.

### Mémoire MBA

- Conserver Word, PDF, sources utilisées, points à confirmer, archives de cours et anciens mémoires.
- Produire une somme SHA-256 des livrables finaux.
- Garder au moins une copie chiffrée hors du poste et une copie synchronisée vérifiée.

## 4. Paquet de continuité

Créer un dossier daté comportant quatre sous-ensembles :

```text
DevContinuity-YYYYMMDD/
  01-manifest/       # versions, dépôts, hashes, checklist
  02-source/         # bundles Git et fichiers non secrets nécessaires
  03-data/           # backups DB et médias, chiffrés
  04-secrets/        # archive chiffrée séparée, accès restreint
```

Le manifeste non secret doit contenir versions Windows/outils, branches et commits, noms de bases et niveaux de compatibilité, URLs locales, présence des fichiers secrets sans leur contenu, hashes des backups et date du dernier test de restauration.

## 5. Chiffrement et credentials

Utiliser un coffre de mots de passe approuvé comme source de vérité. À défaut, créer une archive 7-Zip avec chiffrement **AES-256**, noms de fichiers chiffrés et phrase secrète forte saisie de manière interactive. Ne pas passer la phrase secrète dans une commande, un script, un journal ou un message.

La phrase de l'archive doit être conservée séparément du fichier. Une archive chiffrée dont la phrase est uniquement sur l'ancien poste ne constitue pas une sauvegarde.

| Projet | Élément secret à préserver, sans valeur dans ce document |
| --- | --- |
| Mining 360 | clé de chiffrement config, secrets SQL/Power BI/Power Automate/OpenAI/AD, accès BODEFM, certificats privés éventuels |
| MiningProd | accès web/SQL de test et de production, secrets de connexion du `web.config` |
| Mayite | secret Django, MySQL, e-mail, paiement et API |
| DSTV | secret Django, MySQL et tokens API |
| Pacdigitale | accès WordPress/LWS/FTPS, MySQL, SMTP, clés WordPress |
| Marketing Digital | accès Meta Business Suite/Ads Manager, moyens de paiement, identifiants de compte et audiences |
| MBA | documents confidentiels, consentements et données anonymisées éventuelles |

## 6. Procédure avant changement de machine

1. Geler les changements applicatifs pendant la sauvegarde finale.
2. Mettre à jour les handoffs et le portefeuille.
3. Vérifier que chaque dépôt a un commit identifié et que les changements voulus sont poussés.
4. Produire les backups natifs des bases et vérifier leur restauration ou intégrité.
5. Sauvegarder les médias et documents hors Git.
6. Générer le manifeste du poste et les bundles Git.
7. Constituer les archives chiffrées données/secrets.
8. Calculer les SHA-256 et copier sur au moins deux supports distincts.
9. Restaurer sur la nouvelle machine sans supprimer l'ancienne.
10. Valider tous les projets avec la matrice de recette.
11. Conserver l'ancien poste intact jusqu'à l'acceptation formelle de la nouvelle machine.

## 7. Ordre de restauration

1. Windows Update, Git, Python, Node, PHP, MySQL, SQL Server 2022 Developer, SSMS, ODBC Driver 18 et IIS.
2. Cloner les dépôts et vérifier commits/branches.
3. Restaurer les bases dans des instances locales dédiées.
4. Restaurer les secrets depuis le coffre ou l'archive chiffrée.
5. Recréer les environnements virtuels à partir des requirements.
6. Recréer IIS et les runtimes locaux.
7. Restaurer médias et documents.
8. Lancer les contrôles de santé et fonctionnels.
9. Vérifier qu'aucun environnement local ne pointe vers une base ou un service de production en écriture.

## 8. Recette obligatoire de la nouvelle machine

| Projet | Validation minimale |
| --- | --- |
| Mining 360 | santé application/base, connexion, Business Overview parité/performance, Excellence Center, Reporting, Chatbot, Ressources |
| MiningProd | connexion locale, Sites 2405988, Equipment 45, CAT Price 2406027, écriture test puis rollback, absence d'accès production |
| Mayite | login, statiques, lecture DB, e-mail console, aucune migration implicite |
| DSTV | login, statiques, lecture DB, opérations de test sans effet externe |
| Pacdigitale | accueil desktop/mobile, médias, carrousel, validation formulaire, e-mail de test contrôlé |
| Marketing Digital | ouverture des preuves, cohérence des calculs, présence des exports bruts, aucune publication ou dépense pendant la restauration |
| MBA | ouverture Word/PDF, 15 pages pour la version de validation, liens et hashes disponibles |

## 9. Cadence

- Après chaque changement important : commit, documentation et backup ciblé.
- Chaque semaine de développement actif : manifeste et vérification des dépôts.
- Chaque mois : backup complet données/médias et test d'ouverture.
- Avant tout changement de machine ou intervention majeure : exercice complet de restauration.

Le script `scripts/dev_machine_manifest.py` génère l'inventaire non secret. Le script
`scripts/check_local_sql_iis.ps1` contrôle en lecture seule les instances SQL et les
composants IIS ; l'inventaire IIS complet peut demander une console administrateur.
Le script `scripts/export_committed_sources.ps1` produit des archives ZIP des fichiers
commités et un manifeste SHA-256. Il exclut volontairement les changements non
commités, bases, médias et secrets, qui exigent leurs sauvegardes dédiées.
Ces scripts ne sauvegardent ni données ni credentials et ne remplacent pas les
backups natifs.
