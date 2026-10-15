# Réconciliation Git de Mining 360

Version du 15 octobre 2026.

## But

Rétablir une source versionnée fiable pour Mining 360 sans perdre les travaux réalisés depuis le dernier dépôt vérifié, sans publier de secrets, de bases, de médias ou d'archives, et sans mélanger des changements fonctionnels indépendants.

## État constaté

- les métadonnées Git de la racine ont été restaurées depuis le clone local vérifié `.migration-review/git-publish` ;
- branche de référence : `main` ;
- dernier commit de référence local : `e97f4a7` — *Preserve local Mining360 chatbot and Excellence Center updates* ;
- au contrôle du 15 octobre, la copie de travail contient **1 212 entrées** : 115 modifiées, 995 supprimées et 102 non suivies ;
- ces nombres décrivent l'écart avec le commit de référence. Ils ne prouvent pas que chaque suppression ou ajout est volontaire ;
- aucun ajout global, commit global ou push de cette copie de travail n'est autorisé avant la réconciliation.

## Règles de sécurité

1. Ne jamais exécuter `git add -A`, `git add .` ou un commit couvrant toute la racine.
2. Ne jamais versionner les bases, WAL, dumps, médias, exports, archives de cours, fichiers de credentials ou configurations locales contenant des secrets.
3. Comparer le `main` distant courant avec `e97f4a7` avant toute intégration.
4. Produire un inventaire avec chemins, statut Git, taille et SHA-256 pour les fichiers candidats.
5. Revoir les suppressions par famille ; une absence locale n'établit pas qu'un fichier doit être supprimé du dépôt.
6. Créer des commits thématiques petits et révisables, puis exécuter les tests concernés.
7. Préserver les comportements protégés définis dans `AGENTS.md`, en particulier Revenue, RLS, secrets, routes IA et déploiement BODEFM.

## Classement obligatoire

| Groupe | Traitement |
| --- | --- |
| Code applicatif Mining 360 | Diff ciblé, test, commit fonctionnel séparé |
| Business Overview | Relecture des guides de parité/performance, tests financiers et performance |
| Excellence Center / Chatbot / Reporting / Resources | Commits séparés par domaine et validation dédiée |
| Documentation et scripts de continuité | Revue de contenu secret, commit documentaire distinct |
| Suppressions suivies | Validation explicite fichier par fichier ou par dossier cohérent |
| Bases, WAL, médias et exports | Exclusion Git, sauvegarde chiffrée selon le runbook |
| Archives MBA et fichiers téléchargés | Hors dépôt applicatif sauf décision documentaire explicite |
| Configurations locales et credentials | Hors Git ; conservation dans le coffre ou paquet chiffré |

## Séquence de réconciliation

1. Capturer `git status --porcelain=v1`, la branche, le commit et les hashes des fichiers candidats.
2. Récupérer le `main` distant sans modifier la copie de travail, puis comparer l'ancêtre commun et les commits distants.
3. Créer une sauvegarde chiffrée de la copie de travail et un bundle Git avant mutation.
4. Établir la liste des fichiers réellement nécessaires pour chaque fonctionnalité livrée depuis le 1er octobre.
5. Réconcilier d'abord la documentation et les scripts non secrets.
6. Réconcilier ensuite chaque domaine applicatif sur une branche dédiée.
7. Tester localement avec la base locale appropriée ; ne pas utiliser la production comme environnement de développement.
8. Faire relire le diff et les résultats de test avant fusion dans `main`.
9. Pousser les commits validés, puis régénérer le manifeste de continuité.

## Critères de fin

- `main` distant contient tout le code et la documentation validés ;
- aucune donnée ou information secrète n'apparaît dans l'historique Git ;
- les suppressions sont expliquées et validées ;
- les tests critiques passent en local ;
- le statut Git restant ne contient que des éléments locaux volontairement exclus et documentés ;
- le commit restaurable de chaque fonctionnalité est enregistré dans le portefeuille.

## Limite actuelle

La restauration des métadonnées Git rend l'écart visible, mais ne réconcilie pas automatiquement les 1 212 entrées. Ce travail doit rester progressif afin de ne pas perdre les changements accumulés ni de publier des éléments confidentiels.
