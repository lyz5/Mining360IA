# Mining360 — rafraîchissement quotidien Revenue / Business Overview

Date de rédaction : 26 octobre 2026.
Environnement concerné : production Mining360 à `https://mining360.neemba.com/`.

Ce document décrit le mécanisme applicatif vérifié dans le code et son
interprétation opérationnelle. Il ne déclenche aucun refresh, ne modifie aucun
paramètre de production et ne remplace pas la consultation du statut live.

## État observé le 26 octobre

L’interface Business Overview a affiché :

```text
Published Mapping v9
Revenue through 26 Oct 2026 · Refreshed 26 Oct 2026, 00:01
Currency EUR
Data Confidence High
```

Interprétation : le dernier run Revenue réussi connu par l’interface s’est
terminé le 26 octobre à 00:01, les lignes Revenue actives ont pour date métier
maximale le 26 octobre, la version de mapping consommée reste la v9 publiée, et
la couverture/mapping calculée par l’interface est qualifiée `High`. Ce statut
ne publie pas un nouveau mapping et ne confirme pas à lui seul l’actualisation
des détails Machines ou Pièces.

## Déclenchement

Le scheduler est démarré par le processus WSGI Mining360, après la création de
l’application Django : `Mining360IA/wsgi.py` appelle
`start_revenue_scheduler()`.

Par défaut, `BUSINESS_REVENUE_AUTO_SYNC=true`. Le thread de fond s’exécute
toutes les 60 secondes et appelle `synchronize_if_due()`. Il ne s’agit donc pas
d’une tâche Windows à heure fixe : 00:01 est l’heure observée d’un succès, pas
une heure contractuelle de déclenchement.

Un import automatique est dû seulement lorsque :

1. le mécanisme est activé ;
2. aucun run Revenue n’est `Queued` ou `Running` ;
3. aucun import réussi n’a déjà été terminé le jour local courant ;
4. la dernière tentative ne se trouve pas dans le délai de reprise, de 60
   minutes par défaut (`BUSINESS_REVENUE_AUTO_SYNC_RETRY_MINUTES`).

Un verrou de fichier `.runlogs/revenue-auto-sync.lock` empêche deux schedulers
du même runtime d’importer simultanément. Un run automatique interrompu est
marqué en échec après récupération du verrou, puis peut être relancé selon la
règle de délai. Un échec conserve le dernier snapshot réussi : il ne vide pas
Business Overview.

## Ce que fait le run

Le scheduler utilise `BusinessMappingSourceSynchronizationService(user=None)`
et marque le run avec `automatic_revenue_sync=true`. Le service réutilise la
chaîne gouvernée de synchronisation Revenue : extraction depuis la source
autorisée, validation, remplacement transactionnel des lignes actives et
enregistrement d’un `MappingSynchronizationRun` avec les compteurs et le
contexte de source.

À la réussite, le contexte conserve notamment :

- l’identifiant du run (`source_sync_id`) ;
- `semantic_data_through`, calculé comme la date métier maximale des lignes
  Revenue reçues ;
- l’horodatage `snapshot_completed_at` ;
- le périmètre et les lignes métier configurés.

Après le commit seulement, SQL Server met à jour les statistiques ciblées de
l’index filtré Revenue actif. Cette maintenance ne peut pas annuler un import
données déjà validé ; une erreur de maintenance est journalisée sans exposer les
détails sensibles.

Le refresh n’altère pas automatiquement le Published Mapping, les calculs
Revenue, les droits/RLS ni les paramètres d’intégration. Les mappings restent
consommés uniquement lorsqu’ils sont publiés.

## Lecture de l’interface

| Champ | Signification |
| --- | --- |
| `Revenue through <date>` | Date métier maximale (`semantic_data_through`) du dernier snapshot Revenue réussi. Elle doit être distinguée de l’heure du run. |
| `Refreshed <date/heure>` | Horodatage du dernier run Revenue réussi connu par l’application. |
| `Published Mapping v9` | Version de mapping publiée utilisée par Business Overview, pas une preuve d’un changement lors du refresh. |
| `Data Confidence High` | Indicateur de couverture/calcul de confiance ; ce n’est pas une certification indépendante de toutes les factures sources. |

Une date métier future ou une ligne à zéro dans la source doit être investiguée
comme qualité de source : elle ne doit pas être interprétée automatiquement
comme du Revenue réalisé futur.

## Contrôle et refresh manuel

Les utilisateurs autorisés du Business Overview peuvent consulter :

```text
GET /api/business-review/command-center/sync-status/
```

La réponse expose l’activation, la nécessité éventuelle d’un refresh, le run en
cours, le dernier statut, le `source_sync_id`, la date cible de scheduler, la
date métier source et le dernier contrôle. Elle constitue la meilleure preuve
live à consulter avant toute conclusion sur la fraîcheur.

Le refresh manuel passe par le même endpoint en `POST`, avec contrôle d’accès.
Il réutilise la chaîne gouvernée et le verrou ; s’il existe déjà un run en cours,
il renvoie ce run au lieu de créer un doublon. Une demande manuelle ne donne pas
l’autorisation de publier un mapping.

## Limites à retenir

- La règle quotidienne concerne Revenue. Aucun refresh quotidien automatique
  Machines/Pièces n’a été créé par ce mécanisme.
- Une réussite le jour courant empêche un second import automatique ce même
  jour, même si la source amont est en retard ; la fraîcheur source reste
  affichée et doit être lue séparément.
- La date `target_date` du scheduler correspond normalement à la veille et est
  un objectif de contrôle ; elle ne remplace pas `semantic_data_through`.
- Le scheduler vit dans le runtime WSGI : si le runtime est arrêté, il ne peut
  pas exécuter de cycle. Le redémarrage contrôlé reste gouverné par la procédure
  BODEFM/Neemba existante.

## Références de maintenance

- `reports/revenue_auto_sync.py`
- `reports/business_mapping_source_service.py`
- `Mining360IA/wsgi.py`
- `docs/BODEFM_REVENUE_DAILY_2026-10-10.md`
- `docs/BUSINESS_OVERVIEW_BODEFM_GUIDE_2026-10-10.md`
- `docs/BODEFM_BUSINESS_OVERVIEW_PARITY_PERFORMANCE_2026-10-10.md`
