# Accueil et pied de page Parts — livraison BODEFM du 14 novembre 2026

L'utilisateur a demandé de remplacer « Mining Intelligence » par **Mining
Performance Suite**, puis de retirer le bloc technique en bas de Parts Orders
& Sales Fulfillment. Ces corrections de présentation prolongent la livraison
responsive autorisée et sont installées sur `https://mining360.neemba.com`.

- Commit applicatif poussé et installé : `3b4721204a4d1d75d92baae27b34a8ef3766b313`.
- Base applicative précédente : `8460c2d` ; le responsive reste en place.
- Branche : `feature/responsive-desktop-protected-20261114`.
- Sauvegarde vérifiée : `D:\Mining360Backups\UIPolish_20261114_143337_3b472120`.
- Dossier de contrôle : `C:\Mining360\control\ui-polish-3b472120`.
- [Manifeste des neuf cibles](../deployment/ui-polish-20261114/manifest.json).
- [Validation](../deployment/ui-polish-20261114/validation.json).

## Modification exacte

Trois textes sont remplacés dans `login.html` et l'accueil de repli de
`dashboard.html`. Le formulaire, le fond et les mécanismes d'authentification
restent inchangés. Dans `parts_fulfillment.html`, les deux éléments de pied de
page sont supprimés : badge « Reconciled », avertissement arithmétique et texte
long du modèle/périmètre/métadonnées. Les écritures JavaScript vers ces éléments
ont été retirées pour éviter une erreur sur des nœuds absents.

Le calcul de réconciliation, la ventilation signée, ses contrôles, les détails,
les erreurs et les états vides restent actifs. Aucun modèle, mesure DAX, montant,
filtre de données, droit ou secret n'est modifié.

## Vérifications

- Six rendus login locaux : Windows/local, 320, 390 et 1440 px ; aucune coupure.
- Huit contrôles Parts locaux : synthèse aux quatre largeurs, détails Unallocated,
  avoirs, mois vide et erreur de source ; aucune exception JavaScript.
- Syntaxe JavaScript et parseur PowerShell : réussite.
- Neuf fichiers installés et sept fichiers métier protégés vérifiés par SHA-256.
- Manifeste statique : 211 entrées, seul le mapping JavaScript Parts est actualisé.
  Variantes gzip régénérées ; quatre lectures HTTP de l'asset conformes.
- Sept pages authentifiées HTTP 200 ; application et base `ok`.
- Six comparaisons d'agrégats, même source, Mining/YTD, Mining/MTD et Parts/YTD :
  identiques avant/après ; index Revenue actif conservé.
- Edge depuis le poste sur la version BODEFM : login aux largeurs 320/390/1024/1440 ; Parts au cycle
  1440/390/1024/1440 avec données réelles ; aucun débordement ni exception JS.
- Les deux routes financières contrôlées sans session restent redirigées vers le login. Les sessions
  temporaires utilisées appartiennent au compte associé à l'identité SSH autorisée
  et ont été supprimées. Aucun mot de passe ou cookie n'est publié dans ce reçu.

L'authentification AD réelle et les téléphones physiques ne sont pas retestés.
L'accueil de repli est compilé localement ; aucun feature flag de production n'a
été modifié pour l'activer. Captures privées :
`exports/Mining360_UI_Polish_2026-11-14/INDEX.html`.

## Retour arrière ciblé

```powershell
& 'C:\Mining360\control\ui-polish-3b472120\deploy_ui_polish.ps1' -Manifest 'C:\Mining360\control\ui-polish-3b472120\manifest.json' -Rollback -BackupPath 'D:\Mining360Backups\UIPolish_20261114_143337_3b472120'
```

Le workflow conserve les sauvegardes vérifiées et refuse les changements
concurrents étrangers au paquet. Ce rollback interrompt brièvement Mining360 et
requiert une fenêtre autorisée. Aucun rollback n'a été nécessaire ici. SQL Server,
IIS, les connexions, les imports et les données métier n'ont pas été modifiés.
