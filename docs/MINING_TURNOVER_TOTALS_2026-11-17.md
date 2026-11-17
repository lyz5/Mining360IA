# Mining Turnover — totaux du tableau Performance vs Last Year

Statut : **implémenté et vérifié en local uniquement**. Aucun contact avec
BODEFM, push Git ou déploiement pendant cette évolution.

Worktree : `.release-worktrees/mining-turnover-totals`, branche
`feature/mining-turnover-totals-20261117`, basée sur `bb4710f` (sources applicatives
de la dernière livraison BODEFM). La racine historique mélangée n'est pas utilisée.

## Comportement

Route : `/business-review/command-center/?view=turnover`.

- Une colonne Total additionne les pays affichés pour chaque activité.
- Une ligne Total additionne les activités affichées pour chaque pays.
- La cellule en bas à droite donne le total du tableau affiché.
- Les comparaisons annuelles sont recalculées sur les montants cumulés, jamais
  par addition ni moyenne des pourcentages. Les règles existantes pour bases
  nulles, négatives ou non significatives restent identiques aux cellules.
- La colonne Total reste visible pendant le défilement horizontal.
- Une note précise que les totaux couvrent les pays et activités affichés :
  la limite existante de dix pays et les quatre activités restent en place.
  Ces sommes ne remplacent pas le Revenue certifié du périmètre complet.

Modifications applicatives : JS, CSS et template `business_command_center_v2`.
Les versions des URLs des deux assets sont mises à jour. Les contrôles du
navigateur existant vérifient la présence des totaux. Aucun service, requête SQL,
modèle, filtre, mapping, calcul financier source ou permission n'est changé.

## Vérification locale

Neuf contrôles Edge réussis : totaux et évolutions sur la copie SQL réelle,
filtre d'un pays, largeurs 1440/1024/390 sans débordement du document, puis
fixtures de recette isolées pour pourcentages pondérés, avoir, base de comparaison
négative, valeurs nulles, onze pays dont seuls dix sont affichés et liste vide.
Zéro exception JavaScript ; session temporaire supprimée et aucun e-mail envoyé.

Le contrôle de pondération vérifie notamment 100 000 / 20 000 : +400,0 %, et
non la moyenne des évolutions par pays. Les fixtures restent dans le seul contexte
du navigateur de recette, sans écriture SQL ni données fictives dans le produit.

Instance : `http://localhost:8016/`, base isolée
`localhost\MSSQL_IA / Mining360App_BODEFM_Local_20261116` (snapshot du 15 novembre).
Le runtime local sert maintenant ce worktree ; les lanceurs privés Start/Stop
restent dans `.runlogs/email-code-signin-20261116/local-instance/`.
Preuves : `.runlogs/mining-turnover-totals-20261117/validation.json`, script de
contrôle et captures privées `real-matrix-1440.png`, `real-matrix-390.png`.

## Règle de promotion

L'utilisateur a interrompu les premiers tests pour confirmer qu'aucun déploiement
n'avait lieu pendant l'utilisation de la plateforme. Le runtime local seul a été
arrêté. Il a ensuite autorisé explicitement la reprise locale et établi la règle :
**déploiements BODEFM le soir**, après Go pour la version préparée.
Cette règle est enregistrée dans `AGENTS.md` et le standard local-first.
Le soir ne vaut pas accord et aucune tâche automatique n'est créée.
