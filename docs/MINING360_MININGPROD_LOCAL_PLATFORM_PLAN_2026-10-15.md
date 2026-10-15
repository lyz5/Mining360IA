# Plateforme locale SQL Server pour Mining 360 et MiningProd

Version du 15 octobre 2026.

## Décision d'architecture

Le poste doit héberger deux environnements locaux distincts sur une instance SQL Server Developer de développement :

- Mining 360 avec une base applicative SQL Server locale représentant BODEFM ;
- Miningprod_test avec son application IIS locale et une base restaurée dédiée.

Les identités, bases, fichiers, journaux, cookies, URLs et backups restent séparés. Aucun environnement local ne doit pouvoir écrire dans `Mining360App`, `MiningProd` ou `Miningprod_test` sur BODEFM.

## Version SQL cible

La dernière preuve serveur disponible indique :

- SQL Server **2022 Developer**, major version **16.x** ;
- observation historique : `16.0.1000.6` RTM au 6 août 2026 ;
- compatibilité `Mining360App` : 160 au 10 octobre 2026 ;
- compatibilité historique `MiningProd` : 110.

Le fichier initialement téléchargé était `SQL2025-SSEI-EntDev.exe`. SQL Server **2025 Enterprise Developer Edition** `17.0.1000.7` et le service `MSSQLSERVER` ont été observés actifs pendant l'audit. Une action de désinstallation a ensuite été lancée le 15 octobre à 11:48 puis annulée par l'installateur avant la désinstallation complète. Au contrôle suivant, le service et la clé d'instance n'étaient plus visibles tandis que `setup.exe` restait actif. Cet état doit être réparé ou finalisé avant d'installer SQL Server 2022. Aucune base applicative n'avait été créée dans l'instance 2025.

Pour la parité demandée, une instance **SQL Server 2022 Developer** reste nécessaire après une nouvelle lecture de `SERVERPROPERTY('ProductVersion')` sur BODEFM. Cette lecture a été tentée le 15 octobre mais BODEFM n'était pas joignable depuis le réseau courant ; aucune modification distante n'a eu lieu.

L'installeur officiel SQL Server 2022 Developer a ensuite été téléchargé sous
`C:\Users\diagnepa\Downloads\SQL2022-SSEI-Dev.exe`. Contrôles effectués : produit
`Microsoft Sql Server Installer`, version `16.2211.5693.3`, signature Authenticode
valide de Microsoft Corporation et SHA-256
`5D9D277DCCEF80F2395F915664BD8E63FE7496B7B9C005C2F0C78A3C70D03813`.
Le téléchargement ne constitue pas l'installation de l'instance `DEVSQL2022`.

## État local observé

- installation SQL Server 2025 `MSSQLSERVER` observée, puis désinstallation annulée ; service et enregistrement d'instance absents au dernier contrôle, état à stabiliser ;
- `sqlcmd` 17.0 installé sous les outils ODBC mais absent du PATH ;
- ODBC Driver 18 for SQL Server disponible dans l'environnement Python ;
- MySQL 8.0.46 installé et service `MySQL80` observé actif ;
- Windows x64, environ 1 To de disque dont environ 676 Gio libres à l'observation ;
- installeur SSMS présent ;
- IIS existe sur le disque, mais les fonctionnalités Windows exactes exigent un inventaire UAC administrateur avant configuration ;
- les premiers essais de connexion intégrée locale ont échoué au niveau SSL/package de sécurité. Aucune base applicative n'a été créée. Résoudre cette connexion avant toute migration.
- bootstrapper officiel SQL Server 2022 Developer téléchargé et signé ; installation de l'instance nommée encore à réaliser.

## Installation SQL Server 2022 Developer

### Composants nécessaires

- Database Engine Services ;
- Full-Text uniquement si une dépendance MiningProd le confirme ;
- outils clients séparés : SSMS et `sqlcmd` ;
- authentification Windows privilégiée pour l'administration locale ;
- TCP/IP local seulement au départ, pare-feu fermé au réseau sauf besoin approuvé.

### Configuration initiale proposée

- Instance nommée : `DEVSQL2022`, afin d'éviter toute confusion avec une future instance système.
- Répertoires dédiés : `C:\DevData\SQL2022\Data`, `Log`, `Backup`, `TempDB`.
- Comptes applicatifs distincts pour Mining 360 et Miningprod_test.
- `CHECKSUM` pour les nouvelles bases et backups avec checksum.
- Max server memory à définir après inventaire RAM réel ; ne pas recopier aveuglément les 4 Gio de BODEFM.
- MAXDOP et Query Store reproduits au niveau base seulement lorsqu'ils sont utiles au test ; les contraintes matérielles ne sont pas une configuration fonctionnelle.

## Migration locale Mining 360

1. Installer et patcher SQL Server 2022 Developer.
2. Créer une identité applicative locale dédiée sans droits sysadmin.
3. Créer/restaurer une base locale `Mining360App_Dev` avec compatibilité 160.
4. Utiliser les migrations Django sur une base vide ou le processus de transfert contrôlé existant pour reprendre le snapshot SQLite.
5. Comparer volumes, montants Revenue annuels, Machines, Pièces, flotte et mapping publié.
6. Vérifier l'index filtré Business Overview et la précision `numeric(28,10)`.
7. Exécuter les tests permissions, périodes, précision et performance.
8. Basculer la configuration locale seulement après réussite, en conservant un retour vers SQLite pour diagnostic jusqu'à validation finale.

La base locale porte un suffixe `_Dev` pour éviter une confusion opérationnelle. Les scripts qui exigent historiquement `Mining360App` doivent recevoir une configuration explicite plutôt qu'un renommage implicite.

## Constitution de Miningprod_test local

### Prérequis IIS

- IIS Web Server ;
- ASP.NET 4.x et .NET Extensibility ;
- ISAPI Extensions/Filters ;
- Static Content ;
- console IIS ;
- pool dédié `Miningprod_test_local`, CLR v4.0, pipeline Integrated.

### Source applicative

Utiliser une copie vérifiée du clone distant `D:\Miningprod_test\app`, pas les fichiers de `/Miningprod` directement. Calculer un manifeste SHA-256 avant/après transfert. Conserver le package source chiffré si des configurations sensibles sont présentes.

### Base

1. Produire sur le serveur un backup COPY_ONLY avec COMPRESSION et CHECKSUM de `Miningprod_test`.
2. Vérifier le backup sur le serveur.
3. Transférer par canal approuvé avec SHA-256.
4. Restaurer localement sous `Miningprod_test_Local`.
5. Conserver le niveau de compatibilité source, attendu à 110 tant que la lecture distante ne confirme pas autre chose.
6. Créer un login applicatif local dédié, non sysadmin, sans accès aux autres bases.
7. Désactiver `TRUSTWORTHY` et `DB_CHAINING` sauf preuve de dépendance indispensable.

### Configuration locale de l'application

- URL proposée : `http://localhost/Miningprod_test/`.
- `web.config` local hors Git ou modèle sans secret.
- connexion uniquement à `Miningprod_test_Local`.
- chemins temporaires, exports et logs locaux.
- SMTP redirigé vers un pickup local ou désactivé.
- intégrations externes bloquées ou simulées jusqu'à validation.
- cookies distincts de la production et du clone distant.
- ACL limitées au compte de pool et aux administrateurs locaux.

### Recette initiale

1. page de connexion ;
2. accueil desktop/mobile ;
3. Sites, MetaFormID 2405988 ;
4. Equipment Browser, MetaFormID 45 ;
5. CAT - Part List Price, MetaFormID 2406027 ;
6. contrôle des colonnes et pagination ;
7. création d'un enregistrement de test autorisé puis rollback ;
8. vérification que l'application locale ne peut pas atteindre les bases de BODEFM ;
9. journaux IIS et application sans erreur critique ;
10. mesure des temps de chargement de référence.

## Ordre de réalisation

1. Confirmer la version SQL exacte de BODEFM dès que le réseau est disponible.
2. Décider proprement du devenir de l'instance SQL Server 2025 installée : retrait avant données, ou conservation parallèle clairement nommée. Ne pas y migrer Mining 360 entre-temps.
3. Installer SQL Server 2022 Developer 16.x, SSMS/sqlcmd adaptés et vérifier la configuration.
4. Construire et valider Mining 360 SQL local.
5. Activer les composants IIS requis.
6. Transférer le clone Miningprod_test et sa base vers le poste.
7. Appliquer l'isolation locale et exécuter la recette.
8. Documenter les baselines, backups et restaurations.
9. Seulement ensuite reprendre les développements MiningProd en local.

## Limites

- La version SQL Server BODEFM n'a pas pu être relue le 15 octobre en raison d'une indisponibilité DNS/réseau vers BODEFM.
- SQL Server 2025 a été installé puis une désinstallation a été lancée et annulée par le processus utilisateur ; les contrôles de ce plan n'ont lancé ni installation ni désinstallation et n'ont créé aucune base applicative.
- Aucun backup de base distante ni fichier MiningProd n'a été transféré.
- Le volume final des backups et la RAM réelle disponible doivent être vérifiés avant restauration.
