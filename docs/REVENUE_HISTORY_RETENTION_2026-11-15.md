# Rétention des versions d’import Revenue — trois jours

L’utilisateur a autorisé le 15 novembre 2026 la suppression des versions d’import
de plus de trois jours, après explication de leur rôle et de la distinction avec
les dates des ventes. Cette règle s’applique aux copies inactives de
`bm_revenue_source_snapshot` de Mining360 sur BODEFM, pas aux factures opérationnelles,
aux autres bases ou aux sauvegardes SQL.

## Contrat de conservation

- Conserver tout le jeu actif, avec toutes ses dates métier, même si son import
  est ancien. Une seule ligne active protège la totalité de sa version d’import.
- Conserver les versions dont `completed_at` date de moins de 72 heures ou est
  exactement à la limite. La comparaison est faite en UTC, à durée écoulée.
- Conserver les lignes revues plus récemment (`source_last_seen_at`), les imports
  sans date, échoués, en cours, d’une autre source ou explicitement protégés par
  `source_context_json.revenue_retention_hold`.
- `--protect-run UUID` à l’activation conserve également les versions identifiées
  dans les manifestes de rollback de données ; ces identifiants restent dans la
  politique privée et sont réappliqués à chaque passe.
- Conserver les versions référencées par `BusinessReviewSnapshot`. Les en-têtes
  d’import, références des visites, audits, mappings publiés et rapprochements
  restent en place. Les montants, permissions et calculs ne sont pas modifiés.
- Refuser le nettoyage si une relation entrante SQL ou un trigger non revu cible
  les lignes Revenue. Les références textuelles hors contrat doivent être
  protégées explicitement par le drapeau de conservation.

## Exécution et protection de charge

Un thread WSGI distinct vérifie chaque minute un registre privé sous
`C:\Mining360\shared\revenue-history-retention`. Aucun nettoyage ne se produit
tant que la politique n’a pas été activée par la commande administrateur.

Une passe traite au plus 5 lots de 1 000 lignes et vise une durée maximale de
5 secondes, vérifiée entre les lots. La fin d’un lot ou d’une sauvegarde du journal
peut dépasser cette durée. Cette cadence a été réduite après les premières mesures
réelles pour préserver la performance interactive de Business Overview.
Le backlog reprend à la minute suivante ; une passe complète sans reste est
revérifiée au plus tard une heure après. Un verrou de fichier exclut deux
travailleurs simultanés. Une synchronisation Revenue en attente/en cours met
le nettoyage en pause ; son propre verrou et son importeur ne sont pas modifiés.

Les lots SQL utilisent une transaction distincte, un prédicat `active=0`, la
version et l’horodatage des lignes, `DELETE TOP` et `OUTPUT DELETED.id`. Le délai
d’attente des verrous est borné à cinq secondes puis restauré. Les empreintes
des agrégats actifs sont comparées avant/après chaque passe réussie.

La purge s’arrête si C: passe sous 5 Gio libres. À 50 % d’utilisation du journal,
elle effectue une sauvegarde normale `BACKUP LOG ... COMPRESSION, CHECKSUM` sous
`D:\Mining360Backups\RevenueRetentionLogs`. Si D: passe sous 5 Gio libres, ou
si le journal ne redevient pas réutilisable, elle se met en pause. Elle conserve
le mode FULL et chaque fichier `.trn` ; aucun backup n’est supprimé. Le suivi de
capacité et la rétention générale des sauvegardes restent un sujet distinct.

L’état atomique conserve les nombres de lignes supprimées, reprises, horaires et
codes génériques ; les erreurs fournisseurs et secrets n’y sont pas enregistrés.
Un processus arrêté ne nettoie pas ; le redémarrage reprend depuis les lignes
restantes. Les fichiers de données SQL ne sont pas réduits : l’espace libéré
devient réutilisable dans la base et ne revient pas automatiquement à C:.

## Activation et contrôle

Commande sans option : lecture seule de la politique et du dernier résultat.
`--plan` estime les versions éligibles sans compter/parcourir toutes leurs lignes.

```powershell
& 'C:\Mining360\venv\Scripts\python.exe' 'C:\Mining360\app\manage.py' revenue_history_retention --plan
& 'C:\Mining360\venv\Scripts\python.exe' 'C:\Mining360\app\manage.py' revenue_history_retention --activate --backup-file 'D:\Mining360Backups\Mining360App_PreDowntimeChecking_20261113-r8.bak'
& 'C:\Mining360\venv\Scripts\python.exe' 'C:\Mining360\app\manage.py' revenue_history_retention
```

L’activation est limitée à BODEFM/Mining360App. Elle exige une sauvegarde complète
avec checksums, un seul jeu dans le fichier, débutée depuis moins de trois jours,
et exécute `RESTORE VERIFYONLY ... CHECKSUM, STOP_ON_ERROR`. Cette vérification
établit la lisibilité et les checksums du backup ; elle ne remplace pas un test
de restauration. La sauvegarde initiale couvre les imports déjà expirés ; les
copies futures supprimées sont expirées selon la politique autorisée.

`--disable` désactive les passes futures. Il peut être nécessaire d’attendre la
fin du lot/passe propriétaire du verrou avant de le relancer. `--apply` permet
une passe bornée de contrôle avec `--max-batches` et `--seconds`.

## Retour arrière

Le rollback de code arrête l’automatisation et conserve les fichiers de preuve.
Il ne restaure pas les lignes déjà supprimées. Pour récupérer une version expirée,
restaurer le backup concerné dans une base distincte, vérifier les données puis
réimporter uniquement cette version. Éviter une restauration complète de la base
active qui écraserait les opérations métier postérieures.

## Validation

Vingt tests de rétention vérifient la frontière de 72 heures, les dates de vente
anciennes, les montants négatifs, les versions actives/protégées/référencées,
les en-têtes/audits conservés, lots, reprise après erreur, concurrence, pauses et
désactivation. Ils sont exécutés sur SQLite et sur une base SQL Server 2022 locale
dédiée, créée puis détruite. La syntaxe réelle `DELETE TOP ... OUTPUT` est exercée.

La livraison doit enregistrer séparément les empreintes installées, la sauvegarde
vérifiée, l’activation, les premiers lots et les contrôles financiers/performance
sur BODEFM. Aucun reçu ne doit confondre espace SQL réutilisable et espace libre
sur C:, ou prétendre le backlog terminé avant observation.
