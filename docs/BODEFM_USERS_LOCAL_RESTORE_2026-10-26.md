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