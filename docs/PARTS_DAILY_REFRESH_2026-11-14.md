# Parts — lecture automatique quotidienne à 5 h GMT

L'utilisateur a demandé un rafraîchissement à la même heure que Business Overview.
Le code reprend les paramètres existants `BUSINESS_REVENUE_AUTO_SYNC_HOUR`,
`BUSINESS_REVENUE_AUTO_SYNC_MINUTE` et `BUSINESS_REVENUE_AUTO_SYNC_TIME_ZONE` :
**05:00, Etc/GMT** sur BODEFM, où aucun override n'a été trouvé. L'ancien producteur
central de snapshots et sa tâche Windows sont désactivés ; ils ne sont pas réactivés.

## Fonctionnement

`Mining360IA/wsgi.py` démarre un thread Parts distinct du thread Revenue. Il vérifie
l'échéance toutes les 60 secondes, même sans navigateur connecté. Un processus
arrêté ne peut pas exécuter le travail ; un démarrage après l'heure prévue rattrape
le créneau du jour. Le traitement Revenue, ses requêtes, ses horaires et ses règles
d'import ne sont pas modifiés par cette fonctionnalité.

À l'échéance, les comptes actifs sont réévalués avec les contrôles existants :
accès financier Business Overview, Reporting et contrat global/unscoped actuel
de `LogisticsSource`. Aucun compte, rôle, permission, identité de service ou
contournement RLS n'est créé. Les comptes non compatibles ne lancent pas de requête.
Chaque lecture conserve sa clé de cache propre à l'utilisateur et au rapport.

Le service relit les mesures existantes de Mine Logistics Report en contournant
uniquement le cache de cette requête. Il ne modifie pas le modèle, les mesures,
les cohortes, les clés ou les données. Il ne déclenche pas l'actualisation du
dataset Power BI : les données amont doivent toujours être intégrées dans ce modèle.

Le cache habituel de 90 secondes, limité à 45 secondes lorsque l'historique de
refresh n'est pas disponible, reste inchangé. La page peut donc continuer à lire
des données plus récentes dans la journée. Il ne s'agit pas d'un gel des montants
jusqu'au lendemain ni d'un nouveau stockage de factures.

Une page ouverte reçoit un jeton de fin propre à son utilisateur via une route
GET privée `api/business-review/parts-fulfillment/sync-status/`. Cette route
réévalue les mêmes autorisations et lit uniquement le registre ; elle ne contacte
ni Power BI ni Power Automate. Le navigateur attend le créneau calculé par le
serveur, puis surveille la fin du travail et recharge le mois actuellement affiché
une seule fois par nouvelle réussite. Il reprend aussi quand un onglet redevient
visible. Un détail ou une copie de visuel en cours diffère ce rechargement.
Les erreurs de source restent explicites et permettent une nouvelle tentative.
Aucun bandeau technique supprimé par l'utilisateur n'est réintroduit.

## Reprises et surveillance

- Un verrou distinct empêche les doublons entre processus ; Revenue ne partage
  pas ce verrou et n'attend pas le succès de Parts.
- Une réussite satisfait le créneau du jour. En échec, la reprise utilise le délai
  existant `BUSINESS_REVENUE_AUTO_SYNC_RETRY_MINUTES` : 60 minutes par défaut.
- Les périmètres déjà réussis ne sont pas relus lors de la reprise d'un autre.
- Les erreurs ne deviennent pas des zéros et une erreur de transport ne supprime
  pas une réponse encore présente dans le cache existant.
- Le registre atomique ne contient que des empreintes de périmètres, horaires,
  compteurs et codes d'erreur génériques. Sur BODEFM il se trouve sous
  `C:\Mining360\shared\parts-fulfillment-refresh`; il n'est pas servi par HTTP.
- L'heure de réussite du traitement est une heure de lecture applicative ; elle
  ne remplace pas la date de couverture ou de refresh fournie par Power BI.

Commande de contrôle en lecture seule, dans l'environnement du runtime :

```powershell
& 'C:\Mining360\venv\Scripts\python.exe' 'C:\Mining360\app\manage.py' parts_fulfillment_sync_status
```

Cette commande n'effectue pas de lecture du modèle et ne force pas le travail.
`PARTS_FULFILLMENT_AUTO_SYNC=false`, transmis au processus Django, désactive le
planificateur Parts. Par défaut son activation suit la valeur environnementale de
`BUSINESS_REVENUE_AUTO_SYNC`. Le retour arrière de livraison reste un contrôle
distinct et restaure les fichiers du paquet sans changer les tâches Windows.

## Validation locale

25 tests spécifiques réussissent : frontière de 5 h, fuseau/minute partagés,
exécution unique, rattrapage, permissions réelles, verrou natif, thread distinct,
reprise partielle, erreurs sans données sensibles, conservation du cache et
identité des agrégats avec/sans lecture forcée, isolation du jeton, statut sans
lecture Power BI et ordre de capture du jeton avant les montants pour éviter
une course avec le traitement quotidien.

Six scénarios Edge avec des données de test explicitement isolées vérifient le
rafraîchissement après changement de jeton, l'absence de nouvelle lecture des
mesures si le jeton est inchangé, le mois conservé, les montants signés,
le report pendant la consultation d'un détail et la reprise après erreur.
Les largeurs 320, 390, 1024 et 1440 px ne débordent pas ; aucune erreur JavaScript.

La suite étendue a exécuté **147 tests : 145 réussis et deux échecs de précision
préexistants dans des tests du poste appliqués à la référence serveur**. Ces deux
tests attendent dix décimales, alors que le schéma SQLite construit depuis les
modèles de la référence en déclare deux. `reports/models.py` est strictement
identique au commit parent ; aucune modification de précision n'est incluse.
Cela n'établit pas la précision des colonnes SQL Server réellement installées.
Les tests de maintenance des statistiques du poste ne sont pas importables contre
cette référence, qui n'expose pas leur helper attendu. Ils ne sont pas déclarés
réussis ; aucun correctif Revenue étranger à la demande n'est ajouté.

Les 26 contrôles Parts existants du dépôt canonique et les contrôles disponibles
du prédicat Revenue actif ont été exécutés contre le code de cette branche, sans
les copier dans la livraison. Les empreintes de leurs sources externes sont
conservées dans les preuves privées. Les tests utilisent un schéma SQLite isolé
et des transports simulés ; ils ne certifient pas une migration SQL Server.

Le reçu de promotion doit établir séparément l'installation BODEFM, l'exécution
réelle de rattrapage et le prochain créneau. Les tests de l'horloge ne constituent
pas l'observation anticipée d'une exécution à 5 h le lendemain.

## Livraison BODEFM vérifiée

- Source applicative poussée puis installée : `8b22a1d7252e905067b3c7aa3cdc740185a83db2`.
- Branche : `feature/responsive-desktop-protected-20261114`.
- Sauvegarde vérifiée : `D:\Mining360Backups\PartsDailySync_20261114_155701_8b22a1d7`.
- [Manifeste des quatorze cibles](../deployment/parts-daily-refresh-20261114/manifest.json).
- [Reçu de validation](../deployment/parts-daily-refresh-20261114/validation.json).
- Rattrapage réellement observé : début `2026-11-14T23:57:13.126921+00:00`,
  fin `2026-11-14T23:57:44.462913+00:00`, état `Completed`, zéro échec.
- Créneau suivant confirmé : `2026-11-15T05:00:00+00:00`.
  Cette exécution future n'est pas présentée comme déjà observée.

Quatorze empreintes installées et sept fichiers métier protégés sont conformes.
Les 211 mappings statiques sont conservés ; seul le JavaScript Parts change.
Quatre lectures HTTP des assets, trois protections anonymes vers le login et sept
pages authentifiées passent. Les six comparaisons Business Overview ainsi que
les KPI et les douze mois historiques Parts d'octobre sont identiques avant/après.
L'index Revenue actif reste présent ; aucun import n'a été déclenché manuellement.

Edge sur données réelles vérifie dix cycles de format, dont trois navigations
Business Overview et Parts aux largeurs 390, 1024 et 1440 px : zéro exception,
zéro débordement et aucune requête de source provoquée par un redimensionnement.
Business Overview charge en médiane à **1.186 s**, première navigation
incluse. Le service sans cache reste entre
**0.906 et 1.469 s**
sur les six lectures contrôlées après livraison. Ces observations ne garantissent
pas les temps de tous les utilisateurs. Les sessions temporaires sont supprimées.

Les captures réelles restent privées sous
`exports/Mining360_Parts_Daily_Refresh_2026-11-15/INDEX.html` ; elles ne sont pas
publiées dans Git. Le modèle Power BI n'est ni rafraîchi ni modifié par cette
livraison : le traitement relit les mesures déjà disponibles dans ce modèle.

Retour arrière ciblé, seulement dans une fenêtre autorisée :

```powershell
& 'C:\Mining360\control\parts-daily-sync-8b22a1d7\deploy_parts_daily_sync.ps1' -Manifest 'C:\Mining360\control\parts-daily-sync-8b22a1d7\manifest.json' -Rollback -BackupPath 'D:\Mining360Backups\PartsDailySync_20261114_155701_8b22a1d7'
```

Cette procédure restaure les seules cibles du paquet après vérification des
empreintes et de l'absence de modification concurrente. Aucun rollback n'a été
nécessaire. Aucun redémarrage SQL Server/IIS, migration, modification de données,
permission, secret ou tâche de production supplémentaire n'est effectué.
