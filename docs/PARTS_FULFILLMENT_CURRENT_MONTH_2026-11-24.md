# Parts Fulfillment : mois courant et comparaison mensuelle

**Mise à jour : livré et validé sur BODEFM après Go le 24 novembre.** Voir
[le reçu](PARTS_CURRENT_BODEFM_RELEASE_2026-11-24.md). Les états locaux ci-dessous
conservent l'historique de préparation.

24 novembre 2026 : **implémenté et testé localement, non déployé**. Worktree
`.release-worktrees/pf-current`, branche
`feature/parts-fulfillment-current-month-20261124`, basé sur `6113e1f`.
Prévisualisation : `http://localhost:8016/business-review/parts-fulfillment/`.
Un nouveau Go est requis ; celui du 22 novembre concernait une autre livraison.

## Comportement

L'utilisateur demande le mois courant par défaut avec Actual vs Last Month.
Auparavant, le service sélectionnait le dernier mois civil terminé et masquait
les variations du mois en cours.

- Sans paramètre `month` : mois courant Django. S'il n'a pas de données, état vide
  explicite ; aucun retour silencieux à octobre.
- Une sélection explicite telle que `?month=2026-10` conserve son sens. Le bouton
  **Current month** revient au défaut et retire ce paramètre. L'ouverture par
  défaut, Refresh et l'actualisation automatique ne figent plus le mois dans l'URL.
- Les KPI gardent leurs valeurs réelles et présentent la valeur précédente,
  la variation et les dates exactes de comparaison.
- Commandes : `[Order Intake EUR]` du 1er au jour courant contre le même intervalle
  du mois précédent. Couverture physique des commandes non fournie ; aucune date
  inventée ou déduite des factures. INFO.VIEW a confirmé les noms des mesures et
  DATECOMMANDE, sans exposer les expressions des mesures.
- CA : `[CA Comptable EUR]`, comparaison arrêtée au dernier jour comptable connu
  dans le mois courant, contre le même jour du mois précédent.
- Mois historiques : mois complet contre mois précédent complet.
- Dénominateur nul, absent ou négatif, comparaison en erreur ou jour inexistant
  dans le mois précédent : pourcentage N/A explicite, jamais un zéro substitué.

La comparaison temporelle du CA ne désigne pas la mesure `[CA Last Month]`, qui
reste une cohorte de commandes. Clés, attributions, relations, mesures Power BI
et contrôles de sécurité restent inchangés. Historique réel de 12 mois conservé,
aucun filtre Customer/Site ajouté. Quatre fichiers applicatifs changent : service,
template, JS, CSS. Aucun schéma SQL ni import de données nécessaire.

## Validation

41 tests ciblés passent sur SQL Server local jetable, trafic externe bloqué :
mois courant/historique/vide, couverture comptable, février et année bissextile,
décembre/janvier, avoirs, valeurs absentes, panne de comparaison, cache et scheduler.
Compilation Python, `node --check` et `git diff --check` réussis.

Edge sur l'instance isolée avec lectures réelles du modèle : largeurs 1600/1024/390,
aucun débordement de page ni exception JavaScript. Retour à octobre, bouton courant,
Refresh sans figer l'URL et historique complet validés. Session temporaire du seul
propriétaire local supprimée ; aucun e-mail ni modification BODEFM.

Relevé réel du 24 novembre, jamais codé en dur :

| KPI | Actuel EUR | Précédent MTD EUR | Variation | Périodes |
| --- | ---: | ---: | ---: | --- |
| Commandes | 17 774 111,89 | 11 343 585,70 | +56,69 % | 1–24 novembre / 1–24 octobre |
| CA comptable | 9 942 490,01 | 12 139 292,43 | −18,10 % | 1–23 novembre / 1–23 octobre |

Octobre reste à 20 100 153,90 EUR de CA. Les cohortes et la tolérance de
réconciliation sont conservées. Les relevés peuvent évoluer avec la source.

## Instance locale et future livraison

Le profil standard interdit les connexions externes. Un adaptateur privé hors Git,
dans `.runlogs/parts-current-month-20261124/`, relie les seules lectures DAX à
l'identité Global déjà autorisée du connecteur du poste. Les contrôles applicatifs
admin/Global/account/site restent appliqués et les identifiants de modèle doivent
correspondre. Aucun secret de production n'est copié dans le clone. Échanges
temporaires locaux, garde-fous socket/ODBC conservés, refresh automatiques et
workers toujours désactivés. Aucune fraîcheur Power BI n'est inventée.

Le helper est séparément identifié dans `read-bridge-process.json`. Le runtime
utilise le lanceur et l'arrêt standard ; le contrôleur privé `start_preview.py`
vérifie PID, création et chemins. Captures et `browser-check.json` restent privés.

Après Go seulement : vérifier les hashes de BODEFM, sauvegarder les quatre fichiers
et leurs assets/mappings statiques, annoncer la bascule, appliquer et vérifier
montants, droits et affichage. Ne pas réutiliser l'opérateur d'import Sales → Parts.
