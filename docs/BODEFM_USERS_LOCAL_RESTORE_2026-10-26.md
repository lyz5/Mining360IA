# Restauration Users locale pour BODEFM — 26 octobre 2026

## Portée

Le commit de restauration reprend les fichiers de la section Users présents dans le code local : template, JavaScript, CSS, options et validation d’accès, rôles Chatbot et profils de site Focus. Le cache des ressources passe à `20261026-users-local-restore-v4` afin que le navigateur demande les nouveaux fichiers.

Les routes de l’ancienne IA (`/ai/`, `/api/ai/`) restent séparées des routes M360 Chatbot (`/codex-chatbot/`). Aucun compte, rôle attribué, scope, secret ou donnée de base n’est modifié par le déploiement des fichiers.

## Livraison

- Source : worktree Git propre `release/users-tabs-fix-20261026`, basé sur `origin/main`.
- Les fichiers sont revus et ajoutés individuellement ; aucun staging global.
- La promotion BODEFM doit sauvegarder chaque cible avant copie et vérifier les empreintes SHA-256 après copie.
- Le manifeste statique doit être régénéré avant validation de la page.
- Le redémarrage reste soumis au garde-fou Control Center `CodexRun` et aux contrôles du runtime.
- Aucun test n’est relancé dans le cadre de cette reprise ; les validations documentées antérieures sont dans `FOCUS_SITE_USER_ACCESS_2026-10-11.md`.

## Statut

Le statut Git et le résultat de promotion sont établis par le commit et le journal de déploiement. La réussite n’est acquise qu’après vérification du rendu Users authentifié, des deux onglets et des API sur BODEFM.