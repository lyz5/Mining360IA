# Standard de développement local et promotion en production

Version du 15 octobre 2026.

## Principe directeur

Tous les développements des projets actifs suivent désormais le même flux :

> **Développement local → tests locaux → validation documentée → sauvegarde/rollback → autorisation de promotion → production → validation post-déploiement**

Le mémoire MBA n'a pas d'environnement applicatif. Il suit un flux documentaire séparé : sources locales → rédaction → contrôle Word/PDF → validation académique → soumission autorisée.

Une validation locale ne vaut pas autorisation automatique de déployer. Chaque cible distante conserve son propre point d'approbation et son propre retour arrière.

## Matrice des environnements

| Projet | Développement local | Test local | Production | État au 15 octobre 2026 |
| --- | --- | --- | --- | --- |
| Mining 360 | Application Django locale | SQL Server 2022 local à créer pour parité BODEFM ; SQLite conservé comme source de transition/contrôle | BODEFM, SQL Server `Mining360App` | Application locale opérationnelle ; SQL Server 2025 installé mais version non alignée |
| MiningProd | Code et configuration locaux à constituer | Clone local `Miningprod_test`, IIS et SQL Server isolés à créer | `/Miningprod` sur BODEFM | Clone distant de test opérationnel ; clone local absent |
| Mayite | Django + MySQL local, port 8012 | Même environnement avec données locales et e-mails console | PythonAnywhere | Opérationnel localement |
| DSTV | Django + MySQL local, port 8011 | Même environnement avec données locales | PythonAnywhere | Opérationnel localement |
| Site Pacdigitale | WordPress + MySQL + PHP local, port 8020 | Thème testé localement sur desktop/mobile | WordPress LWS | Opérationnel localement |
| Mémoire MBA | Sources, notes, Word et PDF locaux | Contrôles pagination, références, confidentialité et relecture | Soumission académique | Aucun runtime requis |

## Définition de « prêt pour production »

Un changement est prêt seulement si les éléments suivants sont réunis :

1. périmètre et projet identifiés ;
2. branche ou copie de travail connue ;
3. état initial et fichiers touchés enregistrés ;
4. tests fonctionnels pertinents réussis en local ;
5. contrôles sécurité, permissions et confidentialité réussis ;
6. comparaison de données effectuée lorsque le changement touche des calculs ou migrations ;
7. capture ou preuve d'interface produite pour les changements visuels ;
8. sauvegarde et procédure de retour arrière préparées ;
9. limites et risques résiduels documentés ;
10. autorisation explicite obtenue pour la cible de production concernée.

## Règles par type de changement

### Code et interface

- Modifier le dépôt canonique local.
- Vérifier syntaxe, tests ciblés, desktop et mobile selon le projet.
- Versionner les assets statiques lorsque le cache peut conserver une ancienne interface.
- Committer une unité cohérente avant promotion.

### Base de données

- Utiliser une base locale dédiée ; ne jamais développer directement dans la production.
- Tester migration, reprise, volumes, contraintes et rollback sur une copie contrôlée.
- Produire un backup vérifié avant une migration distante.
- Comparer totaux, comptages et empreintes métier avant/après.

### Secrets et connexions

- Les valeurs restent hors Git, hors documentation et hors logs.
- Les fichiers secrets ne sont jamais copiés dans un livrable non chiffré.
- Les environnements locaux utilisent des identités distinctes de la production dès que possible.
- Une application de test ne doit pas pouvoir envoyer de messages réels, lancer des paiements ni écrire dans une base de production.

### Déploiement

- Le package contient seulement les fichiers attendus et un manifeste SHA-256.
- La cible est inventoriée juste avant copie pour détecter une modification concurrente.
- Le service arrêté doit être identifié par son nom, son chemin et son propriétaire ; aucun arrêt global opportuniste.
- Le contrôle post-déploiement reprend les mêmes cas que la validation locale et ajoute santé, journaux, permissions et performance réelle.

## Frontières d'autorisation

Les promotions suivantes sont indépendantes :

- Mining 360 vers BODEFM ;
- MiningProd vers la production `/Miningprod` ;
- Miningprod_test distant ;
- Mayite vers PythonAnywhere ;
- DSTV vers PythonAnywhere ;
- thème Pacdigitale vers LWS ;
- transmission du mémoire MBA.

## Conservation des preuves

Chaque intervention importante doit laisser :

- une note de changement datée ;
- les fichiers modifiés ;
- les tests exécutés et leurs résultats ;
- les captures utiles ;
- le statut de déploiement exact : local, test, production ou non déployé ;
- le backup et le rollback lorsqu'il existe ;
- les points restant à confirmer.

La mémoire portefeuille `PROJECT_PORTFOLIO_MEMORY_2026-10-15.md` est mise à jour lorsqu'un objectif, un dépôt, un environnement, une dépendance ou un statut de déploiement change.
