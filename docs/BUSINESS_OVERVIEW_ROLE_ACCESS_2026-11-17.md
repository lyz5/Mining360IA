# Business Overview — accès par rôle, correction locale du 17 novembre 2026

Statut : corrigé et activé sur `http://localhost:8016/` uniquement. Aucun push,
déploiement, redémarrage ou changement de configuration sur BODEFM.

Worktree : `.release-worktrees/mining-turnover-totals`, branche
`feature/mining-turnover-totals-20261117`. Les totaux développés précédemment
restent présents dans cette même instance locale.

## Changement

Les modes de lecture de Business Review et du Command Center passent par défaut
de `Admin Only` à `Production` : entrée du module, version V2, clients, pays,
key accounts, dernière visite, attention et présentation. `Production` est ici
la valeur du mécanisme de rollout ; elle ne signifie pas qu'un déploiement a eu lieu.
Une variable d'environnement explicite peut toujours fermer le module.

Les contrôles existants du rôle Business Overview et du périmètre Account/MineSite
restent appliqués. Un Admin sans rôle métier reste refusé. Aucun compte ni rôle
réel n'a été réattribué. Les modes d'export, d'écriture, de watchlist et de gestion
des mappings ne sont pas ouverts par ce correctif ; les options IA restent désactivées.
Aucun service Revenue, SQL, index, cache, montant ou mapping publié n'a été modifié.

## Vérification

- Huit tests sans base dans `reports.test_business_overview_rollout` : ouverture
  V2 avec le seul rôle métier, contrôle des autres rôles, profil inactif et anonyme,
  révocation explicite malgré d'anciens droits Django, intersection Account/MineSite,
  conservation des permissions sensibles et des rollouts explicites de fermeture.
- Contrôle système Django réussi ; `git diff --check` réussi.
- Runtime local relancé uniquement via son lanceur avec vérification du propriétaire.
  L'identité Windows complète est nécessaire pour la connexion SQL intégrée ; le
  lancement initial sous sandbox a été remplacé par le lancement local autorisé.
- Santé HTTP 200 et ouverture HTTP 200 du vrai tableau de bord local avec un compte
  existant non Super Admin autorisé. Session de contrôle supprimée ensuite.
- Copie SQL ciblée : `localhost\MSSQL_IA / Mining360App_BODEFM_Local_20261116`.
  Quatre profils non Super Admin sont éligibles et quatre restent non éligibles.
  Ce contrôle HTTP ne constitue pas une recette exhaustive des graphiques ni de
  tous les comptes. La base et les sources de production n'ont pas été consultées.

Preuve privée : `.runlogs/business-overview-access-20261117/validation.json` à la
racine historique. Aucun cookie ni identifiant de session n'est conservé dans le reçu.

## Retour arrière et promotion

Restaurer uniquement les neuf valeurs de rollout dans `Mining360IA/settings.py`,
puis relancer l'instance locale identifiée. Aucun rollback de base nécessaire.
Une promotion BODEFM reste distincte : commit ciblé, revue des variables effectives,
recette des périmètres autorisés et Go explicite de l'utilisateur, le soir uniquement.
