# État des environnements locaux de développement

Contrôle du 15 octobre 2026.

## Résultat global

Le modèle de travail retenu est : **développement local → tests locaux → validation documentée → sauvegarde et rollback → autorisation explicite → production → contrôle post-déploiement**.

| Projet | Environnement local | État contrôlé | Prochaine étape |
| --- | --- | --- | --- |
| Mining 360 | Application locale sur `127.0.0.1:8001` | endpoint de santé HTTP 200 ; SQLite encore utilisé pour la base locale courante | installer une instance SQL Server 2022 Developer conforme, migrer vers `Mining360App_Dev`, vérifier parité et performance |
| MiningProd | À construire localement sous IIS | le clone distant `Miningprod_test` ne remplace pas un environnement local | restaurer application et base dans IIS/SQL locaux, isoler les intégrations, exécuter la recette browsers |
| Mayite | `127.0.0.1:8012` | HTTP 200 ; guide de passation versionné et poussé | préserver les changements locaux existants, compléter backup DB/médias |
| DSTV | `127.0.0.1:8011` | redirection login puis HTTP 200 ; guide versionné et poussé | préserver les changements locaux existants, compléter backup DB/médias |
| Pacdigitale | `127.0.0.1:8020` | HTTP 200 ; guide versionné et poussé | compléter export WordPress, médias et inventaire plugins |
| Mémoire MBA | fichiers locaux | pas d'environnement applicatif requis | sauvegarde versionnée/chiffrée des livrables, sources et hashes |

## Socle de données

- MySQL 8.0.46 est installé et le service `MySQL80` a été observé actif.
- SQL Server 2025 Enterprise Developer `17.0.1000.7`, instance `MSSQLSERVER`, a été installé.
- La preuve disponible pour BODEFM indique SQL Server 2022 Developer 16.x et une compatibilité 160 pour `Mining360App`.
- Les connexions locales à l'instance 2025 ont échoué au niveau SSL/package de sécurité ; aucune base Mining 360 ou MiningProd n'y a été créée.
- La version BODEFM n'a pas pu être relue le 15 octobre en raison de l'indisponibilité DNS/réseau.

**Décision de contrôle :** ne pas migrer de base applicative vers SQL Server 2025. Installer SQL Server 2022 Developer dans une instance nommée et dédiée après arbitrage du devenir de l'instance 2025.

## Continuité déjà sécurisée

- portefeuille humain et registre JSON créés ;
- standard local-first et runbook de changement de machine créés ;
- guides de passation Mayite, DSTV et Pacdigitale poussés vers leurs dépôts distants ;
- métadonnées Git de Mining 360 restaurées ;
- inventaire non secret automatisé par `scripts/dev_machine_manifest.py` ;
- plan de réconciliation Git créé pour le grand écart de la copie Mining 360 ;
- les emplacements de secrets sont inventoriés sans lire ni enregistrer leurs valeurs.

## Travaux restant avant une migration de poste complète

1. réconcilier et pousser les changements Mining 360 par lots contrôlés ;
2. créer des backups natifs vérifiés de chaque base et des médias autorisés ;
3. placer les credentials dans le coffre approuvé ou une archive AES-256 à mot de passe conservé séparément ;
4. installer/configurer SQL Server 2022 et IIS avec élévation administrateur ;
5. construire Miningprod_test local et exécuter sa recette ;
6. effectuer au moins un test réel de restauration sur un emplacement isolé.

Les checks automatiques de la machine ne constituent pas une sauvegarde. Une continuité complète exige un test de restauration et la conservation d'une copie chiffrée hors du poste.
