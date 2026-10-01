# Addendum du 26 septembre 2026 — Business Overview BODEFM

Le paquet conserve sa base Git 43ece51 et ses données locales du 25 septembre.
REVENUE_FIX_2026-09-26.patch ajoute ensuite le correctif déployé sur BODEFM le 26 septembre.
scripts/restore.py l'applique automatiquement après vérification du manifeste.
Le dépôt restauré aura donc DEUX fichiers suivis modifiés par ce correctif ; cet écart est attendu.
Aucun nouveau commit ni push n'a été effectué pour ce correctif à ce stade.

Cause : une synchronisation vide avait désactivé les lignes Revenue et vidé les pays dérivés.
Les synchronisations suivantes échouaient sur une collision de nom de groupe pays.
Correction : refus des données vides/incomplètes/invalides, calcul des groupes après les
pays issus des données courantes et noms uniques lors des changements successifs de pays.

Validation : 57 tests isolés réussis ; contrôles Django et migrations sur BODEFM OK.
Synchronisation terminée : 106371 lignes actives, données Power BI jusqu'au 24/09/2026.
Mining et All Divisions : API HTTP 200, ready=true, RECONCILED, écart=0.
Mappings publiés et configurations protégées inchangés ; HTTPS et Miningprod vérifiés.
Le contrôle initial de restauration au commit propre reste historique ; le test séparé
verification/revenue-fix-restoration.json confirme l'application de ce complément.

BODEFM : sauvegarde SQL et code avant correctif sous D:\Mining360Backups\.
Dossier final : revenue-repair-20260926-utf8.
L'espace faible sur C: reste un risque à traiter séparément, sans purge automatique.
Les données au 25 septembre ne sont pas annoncées disponibles : la source consultée s'arrête au 24.
