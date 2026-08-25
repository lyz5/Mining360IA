# MiningProd - Audit de performance des imports

Date de l'audit : 6 aout 2026
Perimetre : base SQL Server `MiningProd`, application .NET MiningProd et traitements concurrents
Mode d'intervention : diagnostic en lecture seule, aucun changement applique a la production

## 1. Conclusion executive

La lenteur des imports ne provient pas d'une cause unique. Elle resulte principalement de l'addition de quatre facteurs :

1. Le chemin d'ecriture traite les evenements ligne par ligne. Les triggers `INSERT_EVENT` et `UPDATE_EVENT` appellent `NCSCoreRebuildEventChain` pour chaque chaine concernee.
2. Les statistiques des grandes tables sont fortement obsoletes ou sous-echantillonnees. Certaines ont plusieurs centaines de pour cent de modifications depuis leur dernier calcul.
3. Des extractions BCP lisent simultanement jusqu'a 10 millions de lignes avec `SELECT *`, notamment sur `EVENTCHAIN`, `EVENTCHAINCMTVAL` et plusieurs vues.
4. La configuration SQL Server et le stockage ne sont plus adaptes au volume actuel : 4 Go de memoire SQL, fichiers data/log/tempdb sur `C:`, croissance en pourcentage et journal de 49 Go.

Le disque presente actuellement des latences acceptables. Ajouter uniquement du stockage plus rapide ne corrigera donc pas le coeur du probleme.

## 2. Architecture et volumetrie observees

### Plateforme

- SQL Server 2022 Developer RTM, version `16.0.1000.6`.
- Serveur : 3 processeurs logiques et 16 Go de RAM.
- Memoire maximale SQL Server : 4 096 Mo.
- Niveau de compatibilite MiningProd : `110` (SQL Server 2012).
- Query Store : desactive.
- Mode de recuperation : `FULL`.
- Verification des pages : `TORN_PAGE_DETECTION` au lieu de `CHECKSUM`.

### Tables principales

| Table | Lignes | Taille approximative |
|---|---:|---:|
| `AUDIT` | 34 681 725 | 4 864 Mo |
| `EVENTCHAINCMTVAL` | 16 201 989 | 1 816 Mo |
| `EVENTCHAIN` | 7 337 189 | 850 Mo |
| `EVENTCHAINATTVAL` | 2 426 997 | 200 Mo |
| `EVENT` | 2 305 419 | 291 Mo |

`AUDIT` est la table la plus volumineuse. Elle ne possede qu'un index cluster sur son identifiant et un index sur `CREATED_DATE`.

## 3. Chemin d'import et cout des triggers

### Traitement ligne par ligne confirme

Le code web appelle `RunMetaImport` depuis `NCS.Meta.Business.dll`. Le traitement SQL associe presente ensuite le comportement suivant :

- `INSERT_EVENT` copie les lignes, construit une table temporaire de chaines distinctes, puis execute une boucle `WHILE`.
- Pour chaque chaine, le trigger appelle `NCSCoreRebuildEventChain`.
- `UPDATE_EVENT` boucle sur chaque evenement mis a jour et rappelle la meme procedure.
- `NCSCoreRebuildEventChain` charge les regles, boucle sur chaque regle, appelle des regles dynamiques, puis insere ou met a jour les journaux et mappings.
- Plusieurs triggers appellent aussi `LOOKUP_USER_ID_FROM_WINDOWS`.
- Les triggers d'audit parcourent les colonnes avec une boucle et construisent du SQL dynamique pour chaque champ modifie.

Depuis le dernier redemarrage SQL, `NCSCoreRebuildEventChain` avait deja ete execute 59 338 fois et lu environ 977 180 pages logiques. `LOOKUP_USER_ID_FROM_WINDOWS` avait ete execute 24 548 fois.

### Impact

Un import de grande taille ne beneficie donc pas pleinement d'une ecriture en lot. Chaque ligne ou chaine declenche de nombreuses operations secondaires, ce qui multiplie :

- les recherches SQL ;
- les compilations et executions de procedures ;
- les ecritures de journal ;
- les verrouillages ;
- les mises a jour de tables derivees ;
- les traitements d'audit.

### Axe d'amelioration

Construire un nouveau pipeline en trois phases :

1. Charger le fichier dans des tables de staging par lots controles.
2. Valider les doublons, references et types de facon ensembliste.
3. Appliquer les insertions/mises a jour par lots, puis reconstruire chaque `EventChainID` distinct une seule fois.

Les triggers ne doivent pas etre desactives en production sans une analyse fonctionnelle complete. La cible est de deplacer progressivement leur logique vers des procedures set-based testables et transactionnelles.

## 4. Concurrence avec les extractions BCP

Des sessions du poste `BOD-PF58E444`, utilisateur `yassir`, executaient notamment :

- `SELECT TOP 10000000 * FROM dbo.EVENTCHAINCMTVAL WITH (NOLOCK)` ;
- `SELECT TOP 10000000 * FROM dbo.EVENTCHAIN WITH (NOLOCK)` ;
- des lectures equivalentes de `EVENT`, `vw_DPP` et `v_metaform84`.

Ces sessions ont dure plusieurs minutes et genere des attentes `ASYNC_NETWORK_IO` et de parallelisme. `NOLOCK` evite certains blocages mais n'evite ni les scans, ni la consommation CPU, ni les lectures disque, ni la pression sur le cache.

### Actions recommandees

- Interdire les extractions `SELECT * TOP 10000000` pendant les fenetres d'import.
- Passer a une synchronisation incrementale basee sur une cle stable et une date de modification.
- Paginer avec une condition de reprise, pas avec `OFFSET` sur des millions de lignes.
- Selectionner uniquement les colonnes necessaires.
- Affecter les exports lourds a une replique en lecture si l'infrastructure le permet.
- Ajouter un calendrier commun imports, sauvegardes, exports et maintenance.

## 5. Statistiques et plans d'execution

Les statistiques sont le probleme SQL immediat le plus important :

- plusieurs statistiques de `BUSINESS_UNIT` datent de 2016 a 2021 ;
- certaines statistiques d'`EQUIP` depassent 1 000 % de modifications ;
- plusieurs statistiques d'`EVENT` depassent 300 a 800 % ;
- certaines statistiques d'`EVENTCHAINCMTVAL` depassent 700 % ;
- les statistiques recentes des grandes tables sont parfois calculees sur moins de 2 % des lignes.

### Actions recommandees

1. Creer une fenetre de maintenance initiale pour recalculer les statistiques critiques avec un echantillon controle ou `FULLSCAN` selon la duree mesuree.
2. Mettre en place une maintenance reguliere basee sur le nombre de modifications, pas uniquement un calendrier fixe.
3. Activer Query Store apres validation sur Test afin de comparer les plans avant et apres.
4. Capturer un import representatif avant de creer de nouveaux index.

La liste des index manquants du DMV a ete influencee par les operations recentes de nettoyage. Elle ne doit pas etre appliquee automatiquement.

## 6. Index et fragmentation

### Constats

- `EVENTCHAIN` ne possede pas d'index couvrant clairement les acces par `EVENTCHAINTYPEID`.
- Le DMV indique un candidat `EVENTCHAIN(EVENTCHAINTYPEID) INCLUDE (LOAD_EQUIPID)` avec un impact estime eleve, a confirmer sur un import reel.
- `EVENTCHAINCMTVAL` presente environ 26 % a 54 % de fragmentation sur ses trois index principaux apres les suppressions recentes.
- `BUSINESS_UNIT` contient de nombreux index `_dta_` qui se chevauchent. Certains sont utilises, d'autres non.

### Actions recommandees

- Reorganiser ou reconstruire les index fragmentes de `EVENTCHAINCMTVAL` pendant une maintenance, puis recalculer les statistiques.
- Capturer les plans d'un import complet et tester les index candidats sur une copie de la base.
- Consolider les index `_dta_` uniquement apres une periode representative de collecte Query Store/index usage.
- Mesurer le cout d'ecriture de chaque index avant de l'ajouter : un index supplementaire accelere les recherches mais ralentit chaque import.

## 7. Contraintes et qualite des donnees

De nombreuses contraintes sont desactivees ou non approuvees (`is_not_trusted = 1`). Les relations `EVENTCHAIN -> EQUIP` et `EVENTCHAIN -> LOAD_EQUIP` contiennent deja des references orphelines.

Une contrainte non approuvee limite les optimisations du moteur et masque des problemes de qualite.

### Actions recommandees

1. Inventorier les references invalides par contrainte.
2. Definir la regle metier de correction ou d'archivage.
3. Corriger les donnees sur une copie puis en Test.
4. Reactiver avec verification complete (`WITH CHECK CHECK CONSTRAINT`).

Ne jamais forcer la confiance d'une contrainte sans corriger les donnees.

## 8. Memoire, CPU et parallelisme

SQL Server est plafonne a 4 Go alors que le serveur possede 16 Go et disposait d'environ 4,5 Go de memoire libre au moment de la mesure. Le cache de plans contient egalement 741 plans ad hoc a usage unique.

Les attentes de parallelisme sont importantes et le seuil de cout est encore a 5, valeur peu adaptee aux charges modernes. Aucun manque de grant memoire n'etait actif lors de la mesure et aucun spill n'etait present dans le cache courant.

### Actions recommandees

- Mesurer la consommation IIS et des autres services, puis tester une augmentation progressive de la memoire SQL vers 8 a 10 Go si la marge OS le permet.
- Activer `optimize for ad hoc workloads` apres validation.
- Revoir `cost threshold for parallelism` avec les plans reels, typiquement vers une valeur initiale plus elevee a tester.
- Conserver `MAXDOP 2` dans un premier temps, puis le reevaluer apres stabilisation des plans.
- Ne pas modifier plusieurs reglages simultanement.

## 9. Fichiers, journal et tempdb

### Constats

- Data, log et tempdb sont tous sur `C:`.
- Data : environ 10 Go, croissance de 10 %.
- Log : environ 49 Go, croissance de 10 %, alors que moins de 1 Mo etait actif au moment du controle.
- Espace libre de `C:` : environ 22,8 Go.
- Une croissance du log peut donc demander environ 4,9 Go en une seule operation.
- Le log contient 113 VLF, ce qui reste gerable, mais sa taille et sa croissance sont inadaptees.

### Actions recommandees

- Remplacer les croissances en pourcentage par des valeurs fixes validees.
- Pre-dimensionner data, log et tempdb selon les pics observes.
- Deplacer le log et, si possible, tempdb vers des volumes dedies.
- Confirmer des sauvegardes de journal frequentes et testees en mode `FULL`.
- Reduire le fichier log uniquement apres analyse de la cause de croissance et avec une taille cible durable ; ne pas planifier de shrink recurrent.

## 10. Audit et retention

La table `AUDIT` contient 34,7 millions de lignes et presque 4,9 Go. Les triggers d'audit utilisent une logique datant de 2015, interrogent les catalogues systeme et executent du SQL dynamique par colonne modifiee.

### Actions recommandees

- Definir une politique de retention fonctionnelle et legale.
- Archiver les anciennes donnees d'audit dans une base ou table historique.
- Envisager un partitionnement par date pour faciliter purge et archivage.
- Recrire les triggers d'audit de maniere set-based ou adopter un mecanisme d'audit moderne valide par l'IT.
- Indexer seulement les recherches d'audit reellement utilisees.

## 11. Configuration SQL Server et gouvernance

Axes complementaires :

- Mettre SQL Server 2022 sur un CU approuve par l'IT ; l'instance est encore en RTM.
- Tester le passage progressif du niveau de compatibilite 110 vers le niveau cible SQL Server 2022 avec Query Store et validation applicative.
- Passer `PAGE_VERIFY` a `CHECKSUM` lors d'une fenetre controlee.
- Activer la compression par defaut des sauvegardes si compatible avec la fenetre CPU.
- Mettre en place une maintenance SQL Agent pour statistiques, index, integrite et historique.
- Ajouter une alerte espace disque et croissance de journal.

Le code source archive contient une chaine de connexion SQL avec un credential en clair. Le secret concerne doit etre considere expose, remplace, retire de la configuration versionnee et gere par un mecanisme securise.

## 12. Plan d'execution priorise

### P0 - Sans changement de schema

1. Separer les horaires d'import et d'export BCP.
2. Remplacer les exports complets par des extractions incrementales.
3. Capturer un import de reference : duree, lignes/s, CPU, lectures, log genere et etapes.
4. Mettre en place Query Store en Test puis en Production apres validation.
5. Confirmer les sauvegardes de log et les alertes disque.
6. Faire tourner le credential SQL expose.

### P1 - Maintenance SQL controlee

1. Recalculer les statistiques des six tables critiques.
2. Traiter la fragmentation de `EVENTCHAINCMTVAL`.
3. Tester les index candidats sur une copie recente.
4. Remplacer les croissances en pourcentage par des tailles fixes.
5. Ajuster progressivement la memoire SQL.

### P2 - Refonte du moteur d'import

1. Introduire des tables de staging.
2. Valider et dedupliquer ensemblistement.
3. Inserer et mettre a jour par lots.
4. Executer `NCSCoreRebuildEventChain` une seule fois par chaine distincte.
5. Remplacer les boucles d'audit et de rebuild par des procedures set-based.
6. Ajouter reprise, idempotence, journal de lot et suivi de progression.

### P3 - Modernisation structurelle

1. Nettoyer et approuver les contraintes.
2. Archiver ou partitionner `AUDIT` et les historiques volumineux.
3. Migrer le niveau de compatibilite.
4. Separer les volumes data, log et tempdb.
5. Consolider les index redondants.

## 13. Mesures de succes

Chaque amelioration doit etre comparee au meme fichier et au meme serveur :

- lignes importees par seconde ;
- duree totale et par phase ;
- nombre d'appels a `NCSCoreRebuildEventChain` ;
- lectures logiques ;
- CPU SQL ;
- taille de log generee ;
- temps d'attente `WRITELOG`, `PAGEIOLATCH`, `ASYNC_NETWORK_IO` et parallelisme ;
- blocages et deadlocks ;
- impact sur les utilisateurs interactifs ;
- erreurs et doublons ;
- temps de reprise apres echec.

## 14. Regles de prudence

- Tester tous les changements sur une restauration recente de MiningProd.
- Ne pas desactiver les triggers ou contraintes pour accelerer un import sans remplacement fonctionnel valide.
- Ne pas appliquer automatiquement les recommandations d'index manquant.
- Ne pas reduire le journal avant d'avoir compris son pic historique.
- Ne pas cumuler changement de compatibilite, index, memoire et refonte import dans la meme mise en production.
- Conserver un plan de retour arriere et un benchmark avant chaque phase.

## 15. Suivi des actions P0 - 7 aout 2026

Les actions suivantes ont ete appliquees apres l'audit initial :

- L'ancien job `DailyBackupMiningProd`, expire et en echec depuis novembre 2025, a ete desactive.
- Le service SQL Server Agent a ete demarre et configure en demarrage automatique.
- Le job `Mining360_MiningProd_LOG_15min` a ete cree : sauvegarde compressee du journal avec checksum toutes les 15 minutes vers `D:\Mining360Backups`.
- Un lancement manuel puis un lancement planifie du job de journal ont reussi.
- Le job `Mining360_MiningProd_FULL_Daily` a ete cree : sauvegarde full quotidienne a 02:00, compressee, avec checksum et `RESTORE VERIFYONLY`.
- Le nouveau job full a ete execute et verifie avec succes en 29 secondes.
- Query Store a ete active en lecture/ecriture avec capture `AUTO`, retention 30 jours, intervalles de 30 minutes, nettoyage automatique et limite de 1 024 Mo.
- La session Extended Events `MiningProd_ImportBaseline` a ete activee au demarrage. Elle conserve au maximum quatre fichiers de 100 Mo et capture uniquement les batches/procedures MiningProd de plus d'une seconde.

Ces changements n'ont modifie ni les tables metier, ni les triggers, ni les donnees fonctionnelles de MiningProd.
