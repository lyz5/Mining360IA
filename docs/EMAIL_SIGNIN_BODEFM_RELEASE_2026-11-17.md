# Connexion e-mail — livraison BODEFM du 17 novembre 2026

## Autorisation et périmètre

Après la recette locale et les deux envois réels, l'utilisateur a confirmé
« j'ai testé ça marche » puis demandé explicitement « déploie sur le bodefm ».
Le raccordement Outlook et la connexion locale sont donc validés par lui.
La livraison vise uniquement Mining360 sur BODEFM, `Mining360App`,
`https://mining360.neemba.com/`. Elle ne publie aucune ouverture anonyme.

Cette note prépare la promotion ; le reçu final précise son résultat effectif.
Le point de départ Git est `f81a3ad37e8b956f4a932a22db3320ab156095f5`.
Le worktree de recette reste distinct de la racine historique mélangée.

## Paquet et activation

`deployment/windows/deploy_email_signin.ps1` reprend les fonctions ciblées
d'arrêt, relance et restauration de la livraison UI existante. Les seuls fichiers
applicatifs installés sont ceux de la connexion et la ligne d'activation du
lanceur ; le CSS est ajouté au manifeste statique sans modifier les autres clés.
Le mode de recette local, sa base et sa politique réseau ne sont pas installés.

Le préparateur contrôle le serveur, la cible SSH approuvée et la clé épinglée,
les empreintes précédentes, les fichiers protégés, l'espace disque et les tâches.
Il sauvegarde les fichiers ciblés et fait un backup SQL COPY_ONLY, COMPRESSION,
CHECKSUM, vérifié par RESTORE VERIFYONLY. Les sauvegardes sont sur D: et leur
dossier est limité à SYSTEM/Administrators.

L'application est arrêtée par sa tâche de récupération existante. Seule la
migration additive `0150_email_code_signin` peut être exécutée. La configuration
du flow dédié passe en mémoire par stdin SSH et est chiffrée avec la clé serveur.
Aucun secret, utilisateur, rôle ou base de recette n'est importé sur BODEFM.
La variable machine `MINING360_EMAIL_CODE_LOGIN_ENABLED=1` active la page.
Le lien `/login/?method=password` conserve la connexion précédente.

## Contrôles et limites

Les 45 tests SQL locaux couvrent authentification, CSRF, expiration, concurrence,
droits, chiffrement et isolation de la recette. Huit anciens échecs AD/Users,
reproduits sur le point de départ, restent explicitement hors de cette évolution.
Les contrôles financiers regroupent les montants décimaux actifs par année,
division et LOB. Les empreintes des comptes/droits et des autres connexions,
l'index actif et la précision numérique sont comparés avant/après.

Le probe de livraison utilise les vues normales, le CSRF et un vrai code aléatoire
gardé en mémoire pour sa seule session de recette. Il envoie uniquement à
`papa.diagne@neemba.com`, vérifie sa consommation, puis supprime sa session.
Il ne lit pas la boîte Outlook et n'est pas un endpoint HTTP.

« Keep me signed in on this device » conserve la session 14 jours par défaut ;
sinon le cookie expire à la fermeture du navigateur. Le code reste valable dix
minutes et utilisable une fois. Les rôles et périmètres existants gouvernent
toutes les pages, y compris Config. Les contrôles anonymes ne certifient pas tous
les rôles, les périmètres Power BI ou les appareils physiques.

## Retour arrière

La phase `Rollback` utilise le manifeste et le dossier préparé de cette livraison.
Elle rétablit l'intégration Notification précédente, le drapeau et les seuls
fichiers sauvegardés, puis relance la tâche de runtime. Les nouvelles tables
d'authentification restent en place ; elles ne sont plus utilisées par l'ancienne
version. Aucun restore complet ne doit écraser l'activité métier ultérieure.
Les contrôles d'existence et de hash arrêtent la restauration si un fichier a
été modifié entre-temps.
