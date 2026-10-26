# Publication BODEFM — séparation des utilisateurs

Date : 26 octobre 2026.

## Portée publiée

La page de gestion des utilisateurs de Mining 360 sur BODEFM propose désormais
deux onglets : **Neemba users** et **System users**.

- `neemba` exclut les comptes dont `auth_source` vaut `local` ;
- `system` ne retourne que les comptes dont `auth_source` vaut `local`.

Les compteurs renvoyés par l'API distinguent également les deux populations.
Cette publication ne crée, ne modifie ni ne supprime aucun compte utilisateur.
Elle ne modifie pas les rôles, la RLS, les mappings, les données Revenue, la
base de données ou les migrations.

## Fichiers publiés

Les sept fichiers suivants ont été mis à jour, et seulement ceux-ci :

- `reports/templates/reports/users_access.html` ;
- `reports/user_access_service.py` ;
- `reports/user_access_views.py` ;
- `reports/static/reports/users_access.js` ;
- `reports/static/reports/styles.css` ;
- les deux copies servies depuis `C:\Mining360\shared\static\reports\`.

## Protection, validation et retour arrière

Avant la copie, chaque fichier de production et chaque fichier préparé a été
vérifié par SHA-256. Une sauvegarde ciblée a été conservée sur BODEFM dans :

`D:\Mining360Backups\release-20261026-users-audience-tabs\backup`

Le runtime contrôlé par la tâche `Mining360RuntimeServiceRecovery` a été arrêté
avant la copie puis relancé. Les contrôles réalisés après redémarrage sont :

- santé locale du runtime : HTTP 200 ;
- santé HTTPS publique `https://mining360.neemba.com/health/` : HTTP 200 ;
- présence confirmée des onglets et des filtres `neemba` / `system` dans les
  fichiers publiés.

La validation de l'affichage après connexion reste un contrôle fonctionnel à
effectuer par un utilisateur autorisé ; elle n'est pas déduite du contrôle de
santé technique.
