# Rattrapage ponctuel des copies Revenue expirées et espace C:

L’utilisateur demande explicitement de libérer les copies d’import de plus de
trois jours après l’activation de la rétention progressive. Le diagnostic du
15 novembre trouve encore environ 32 millions de lignes au total dans la table,
dont l’essentiel correspond à des versions inactives anciennes. La suppression
ligne par ligne maintient vingt et un index et mettrait plusieurs jours au rythme
de fond choisi pour préserver l’interface.

## Périmètre et conservation

L’opération reprend la politique de `revenue_history_retention` : âge UTC de
72 heures depuis la fin de l’import, versions actives, snapshots revus et deux
versions de rollback explicitement conservés. Une ligne vue récemment protège
ici toute sa version, par prudence. Les imports inconnus, autres sources,
échoués ou non datés restent conservés. Toutes les dates de ventes du jeu actif,
les identifiants, montants et fractions de centime restent identiques.

Les en-têtes d’import, audits, mappings, tables de détails, permissions et autres
bases restent conservés. Aucun changement de modèle Power BI, formule Revenue,
calendrier, cache, source, index ou schéma n’est déployé.

## Transaction ponctuelle

La commande `revenue_history_catchup --apply --reclaim-data` :

1. prend les verrous de rétention et de synchronisation pour éviter une autre
   intervention concurrente ; refuse un import déjà en cours ;
2. vérifie BODEFM/Mining360App, le schéma, l’absence de dépendances entrantes,
   triggers, réplication, CDC, temporalité, table mémoire et prédicats RLS ;
3. exige au moins 12 Gio libres sur C: et la place estimée pour un backup complet
   compressé avec marge sur D: ;
4. crée un backup SQL actuel COPY_ONLY/COMPRESSION/CHECKSUM et le vérifie par
   `RESTORE VERIFYONLY ... CHECKSUM, STOP_ON_ERROR` ; conserve la chaîne des logs ;
5. prend un verrou SQL exclusif sur la seule table Revenue. Les lecteurs doivent
   attendre cette transaction ; aucune table vide intermédiaire n’est visible
   aux lectures normales de l’application ;
6. copie les versions à garder dans des tables temporaires SQL en conservant les
   types et toutes les colonnes. Les autres versions, y compris nouvelles ou
   inconnues, sont conservées par complément de l’ensemble expiré ;
7. utilise TRUNCATE dans la transaction puis réinsère toutes les lignes à garder
   avec leurs identifiants d’origine et restaure la valeur de séquence d’identité ;
8. compare nombres, checksum de toutes les colonnes, somme SQL à dix décimales,
   signature des agrégats actifs, objet, colonnes et index avant de valider ;
9. après commit, sauvegarde le journal, attend la désallocation, puis réduit
   ponctuellement le fichier de données avec `WAIT_AT_LOW_PRIORITY` et
   `ABORT_AFTER_WAIT=SELF`. Aucune session bloquante n’est tuée ;
10. laisse au moins 12 Gio alloués au fichier de données, ou davantage selon les
    données réellement conservées et leur marge, puis actualise les statistiques.

Il n’y a ni DROP/renommage de la table source, ni désactivation d’index ou de
contrainte, ni modification d’ACL, de récupération FULL, de service SQL/IIS ou
de la routine quotidienne de cinq petits lots. Le même objet SQL et ses index
restent présents. Le checksum est un contrôle supplémentaire, pas une preuve
cryptographique indépendante : la copie et la restauration SQL typées se font
dans la même transaction, avec les contrôles métier et de structure indiqués.

En cas d’erreur avant commit, SQL Server annule l’opération et restaure aussi
les copies expirées. Après commit, une erreur de réduction de fichier n’annule
pas la purge validée ; le registre indique alors une reprise à examiner.
`catchup.json` conserve les phases, heures, nombres et tailles de fichiers,
sans montants métier ou secrets. Le backup actuel permet une restauration
isolée et une reprise ciblée si nécessaire ; VERIFYONLY n’est pas un test complet
de restauration. Les backups de cette intervention ne sont pas supprimés.

Références Microsoft : [TRUNCATE transactionnel](https://learn.microsoft.com/en-us/sql/t-sql/statements/truncate-table-transact-sql?view=sql-server-ver16),
[réduction à faible priorité](https://learn.microsoft.com/en-us/sql/t-sql/database-console-commands/dbcc-shrinkfile-transact-sql?view=sql-server-ver16).

## Validation et livraison

Les tests SQL Server 2022 locaux couvrent la conservation de toutes les colonnes,
dates anciennes, Unicode, zéros initiaux, valeurs négatives et fractions de
centime, l’identité, les index et le rollback d’une validation volontairement
échouée. Un test de 20 000 lignes complète ces contrôles. La réduction de fichier
est testée hors transaction, conformément à SQL Server.

La livraison ajoute seulement deux modules de commande. Elle est reliée à un
commit Git, vérifie les empreintes des sources protégées et ne redémarre pas
l’application. L’exécution est séparée de cette installation. Le reçu doit
enregistrer la sauvegarde actuelle, les vrais nombres supprimés/conservés,
l’espace C: avant/après, les totaux financiers et la performance ; il ne doit
pas annoncer d’espace disque rendu avant sa mesure.
