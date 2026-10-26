# Restauration Users locale BODEFM — 26 octobre 2026

## Source et portée

Release construite sur `feature/downtime-checking-20261026` au commit `40526ed`, base qui conserve les fonctions déjà utilisées par BODEFM. Le paquet met à jour le template Users, son JavaScript, le service des options et validations Users, ainsi que le fournisseur des profils Focus. La feuille CSS en place sur BODEFM est déjà identique au code local et reste inchangée. Les règles d’accès Downtime et le traitement Chatbot déjà présents restent inchangés.

Les routes M360 Chatbot (`/codex-chatbot/`) et ancienne IA (`/ai/`, `/api/ai/`) restent séparées. Aucun utilisateur, périmètre, secret ou enregistrement de compte n’est modifié par la copie du code.

Le cache statique passe à `20261026-users-local-restore-v4`.

## Promotion

- Commit Git dédié sur une branche de release fondée sur le code déjà présent sur BODEFM.
- Paquet et manifeste limités aux fichiers Users ciblés, avec empreintes SHA-256.
- Sauvegarde code et assets avant copie ; contrôle Django, collectstatic, redémarrage protégé et vérification HTTP requis.
- Un essai précédent depuis `origin/main` a été annulé par `manage.py check` avant redémarrage, car cette base ne contenait pas le modèle Downtime utilisé par BODEFM. Les fichiers actifs ont été restaurés depuis `C:\Mining360\backups\users-local-restore-6dfcaad-20261026-093002`.
- Le garde-fou Control Center exclut désormais les états Codex terminaux `TIMED_OUT` et `PARTIALLY_SUCCEEDED`; il bloque toujours les états non terminaux.

## Validation

Confirmer le déploiement après santé application/base, contrôle Django, API Users/options HTTP 200, assets HTTP 200 et vérification authentifiée des deux onglets.
## Résultat BODEFM

- Code déployé : commit `8588c3d6577d0795b20c7012737965d9964def76`.
- Sauvegarde ciblée : `C:\Mining360\backups\users-runtime-restore-8588c3d-20261026-095927`.
- `manage.py check` : réussi. `collectstatic` : un fichier mis à jour, 210 inchangés, 568 post-traités.
- Redémarrage protégé : application `ok`, base `ok`, santé HTTPS publique `200`.
- JavaScript servi sous `reports/users_access.577246b1fd9e.js` : HTTP 200 ; feuille CSS : HTTP 200.
- Rendu authentifié de `/users/` : HTTP 200, cache v4, onglets Neemba et Mining360 présents.
- API Users : HTTP 200, 5 comptes Neemba et 6 comptes créés dans Mining360, 11 au total. API options : HTTP 200, 7 rôles et 25 profils Focus.
- Aucun compte ni droit utilisateur existant n’a été modifié par cette promotion.

La validation a été faite par rendu Django authentifié et appels API en lecture seule. Une capture Edge de la session utilisateur n’a pas été produite dans cette opération.