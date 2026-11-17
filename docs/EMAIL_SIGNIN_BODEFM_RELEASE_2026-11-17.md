# Connexion e-mail — livraison BODEFM du 17 novembre 2026

## Autorisation et périmètre

Après la recette locale et les deux envois réels, l'utilisateur a confirmé
« j'ai testé ça marche » puis demandé explicitement « déploie sur le bodefm ».
Le raccordement Outlook et la connexion locale sont donc validés par lui.
La livraison vise uniquement Mining360 sur BODEFM, `Mining360App`,
`https://mining360.neemba.com/`. Elle ne publie aucune ouverture anonyme.

**Installé et actif sur BODEFM.** Le [reçu de livraison](../deployment/email-signin-20261117/validation.json)
consigne les contrôles et les limites ; le [manifeste](../deployment/email-signin-20261117/manifest.json)
identifie les vingt cibles et les six fichiers protégés.
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
dossier est limité à SYSTEM/Administrators. Seul le sous-dossier `database` donne
également accès au compte de service SQL Server pour écrire/vérifier le backup.

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


## Résultat effectif

- Commit applicatif installé : `020bc5f7de259b05c1f5f726e2b9ce1017b110c8`.
- Outil de recette HTTPS corrigé, sans changement applicatif : `5febc05eb8aa205ead71e87e9e94f24370a9b43c`.
- Sauvegarde : `D:\Mining360Backups\EmailSignIn_20261116_220815_020bc5f7`.
- Dossier de contrôle : `C:\Mining360\control\email-signin-020bc5f7`.
- Vingt empreintes installées et six empreintes protégées conformes après recette.
- Backup SQL de 848 151 040 octets, COPY_ONLY et checksum vérifié.
- Envoi Outlook réel accepté, connexion du compte existant, code consommé/effacé,
  session persistante de quatorze jours vérifiée. La session de recette a été supprimée.
- Treize contrôles Edge : Business Overview réel, six autres pages autorisées,
  login desktop/mobile, compte absent et refus de Config anonyme.
- Empreintes financières, des accès et des autres connexions identiques ; index
  actif et précision `numeric(28,10)` préservés. Aucun refresh demandé.
- Cœur Business Overview sans cache après : 1,125 / 1,047 / 1,032 s.
  Avant : 8,906 / 2,328 / 1,375 s. Navigations Edge initiales : 6,788 s avant,
  3,359 s après ; suivantes : 1,798 / 1,724 s avant et 1,783 / 1,183 s après.
  Ces observations dépendent de l'état des caches et ne certifient pas un gain.

Le wildcard Sectigo `*.neemba.com` actuellement lié à IIS a expiré le
16 novembre 2026 à 23:59:59 UTC. Le navigateur ordinaire échouait déjà avant
l'installation (`ERR_CERT_DATE_INVALID`). L'utilisateur a expressément reporté
ce sujet. Aucun certificat, binding, DNS, pare-feu, configuration TLS ou service
IIS/SQL n'a été changé. La recette fonctionnelle Edge utilise exclusivement la
clé publique exacte du certificat IIS, relue via le SSH à clé épinglée ; elle ne
constitue pas une validation HTTPS normale et aucune exception n'est installée
dans les navigateurs des utilisateurs. Le certificat doit être renouvelé séparément.

Le paquet opérateur `7b8597fe` a été arrêté avant installation pendant la lecture
CIM de la tâche Windows historique. Le paquet `020bc5f7` filtre la liste des tâches
et a réussi sauvegarde puis installation. Aucun ancien paquet n'a été installé
dans l'application. Les avertissements CIM restants ne sont pas
une modification de la tâche ; la tâche existante a été relancée normalement.

Retour arrière ciblé, dans PowerShell élevé sur BODEFM :

```powershell
& 'C:\Mining360\control\email-signin-020bc5f7\deploy_email_signin.ps1' -Manifest 'C:\Mining360\control\email-signin-020bc5f7\manifest.json' -Phase Rollback -BackupPath 'D:\Mining360Backups\EmailSignIn_20261116_220815_020bc5f7'
```

Le retour arrière interrompt brièvement Mining360 et doit rester une décision
opérateur. Aucun retour arrière n'a été nécessaire après l'installation réussie.
