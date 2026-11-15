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
de restauration. [Référence Microsoft](https://learn.microsoft.com/en-us/sql/t-sql/statements/restore-statements-verifyonly-transact-sql?view=sql-server-ver16).
La sauvegarde initiale couvre les imports déjà expirés ; les
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

## Livraison et activation observées

- Source applicative poussée et installée : `c47ce306c9c31e81cdcc7fb4265279c2700a2fba`.
- Branche : `feature/responsive-desktop-protected-20261114`.
- Sauvegarde ciblée du code : `D:\Mining360Backups\RevenueRetention_20261115_030857_c47ce306`.
- [Manifeste des trois fichiers](../deployment/revenue-retention-20261115/manifest.json).
- [Reçu de validation](../deployment/revenue-retention-20261115/validation.json).
- Politique activée : 3 jours ; jeu actif et deux versions du rollback de données
  explicitement protégés. Les deux versions conservées sont celles du transfert
  de parité du 10 octobre et du jeu précédemment actif cité par son manifeste.
- Backup complet initial : `D:\Mining360Backups\Mining360App_PreDowntimeChecking_20261113-r8.bak`, vérifié avec checksums à
  `2026-11-15T11:13:21.478605+00:00` ; aucun nouveau backup complet de 11 Go n'a
  été ajouté sur D: pour cette opération.
- Dernière passe observée : `2026-11-15T11:50:38.932924+00:00`, 5000 lignes,
  5 lots, 5.157 s, état `More pending` et signature
  financière active inchangée. Compteur confirmé : 119091.
  Le backlog initial continue ; il n'est pas déclaré entièrement supprimé.

La première cadence (100 lots / 40 s) a été réduite à 5 lots / 5 s après observation
de la charge réelle. Les compteurs précédents pouvaient conserver un ancien
horodatage de fin pendant une nouvelle passe ; la version installée remet ces
champs à zéro et enregistre une pause si la restauration du contexte SQL échoue.
Les résultats ODBC des sauvegardes sont consommés avant une autre requête.

Une pause générique au garde-fou du journal a nécessité un diagnostic. Un essai
administrateur de la fonction déployée a ensuite réussi la sauvegarde normale
du journal dans le dossier autorisé, dont l'utilisation a été validée ; le
nettoyage automatique a repris. L'erreur initiale détaillée n'a pas été conservée
dans le registre générique et sa cause précise n'est donc pas affirmée ici.
Le journal est passé d'environ 50,06 % à
4.65 % utilisés ; le fichier `.trn`
compressé observé est conservé dans le reçu. Aucun mode SIMPLE, backup vers NUL,
changement de permission ou suppression de sauvegarde n'a été utilisé.

Vingt tests réussissent sur SQLite et vingt sur SQL Server 2022 local, y compris
la requête DELETE réelle. Une suite précédente de 83 tests (dont 14 premiers tests
de rétention) passe également. Les bases locales de test sont détruites après usage.
Trois empreintes installées et huit fichiers métier protégés sont conformes ; les
211 mappings statiques restent inchangés. Sept pages authentifiées et trois
redirections anonymes vers le login sont contrôlées. Les six comparaisons
financières Business Overview et les agrégats Parts d'octobre restent identiques.

Après les premiers lots, les six calculs sans cache sont entre
0.859 et 1.532 s.
Une première navigation Edge à 16,040 s n'a pas été reproduite dans la série de
contrôle suivante : 2,781 / 1,191 / 1,242 s, médiane 1,242 s. Sa cause transitoire
n'est pas établie avec certitude. Le profil suivant mesure notamment le temps
réseau et l'API ; il ne constitue pas un percentile terrain. Aucun changement de
requête Revenue ou allongement de cache n'a été appliqué pour obtenir ces temps.
Les dix cycles de format et six reprises profilées n'ont ni exception JavaScript
ni débordement. Les sessions temporaires sont supprimées.

Captures réelles privées :
`exports/Mining360_Revenue_Retention_2026-11-15/INDEX.html`.
Les quantités financières et images ne sont pas publiées dans Git.

Pour arrêter les passes futures, utiliser `revenue_history_retention --disable`,
puis vérifier `enabled=false`. Le rollback ciblé de code utilise :

```powershell
& 'C:\Mining360\control\revenue-retention-c47ce306\deploy_revenue_retention.ps1' -Manifest 'C:\Mining360\control\revenue-retention-c47ce306\manifest.json' -Rollback -BackupPath 'D:\Mining360Backups\RevenueRetention_20261115_030857_c47ce306'
```

Le rollback de code seul ne récupère pas les copies expirées déjà supprimées.
Les en-têtes et audits restent conservés ; une récupération de données doit être
ciblée depuis une base de restauration distincte. Aucune réduction physique des
fichiers SQL n'a été exécutée. La libération d'espace sur C: n'est pas revendiquée.
