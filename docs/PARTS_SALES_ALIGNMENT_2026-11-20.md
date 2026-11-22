# Sales → Parts : alignement de l'alimentation comptable

État du 20 novembre 2026 : développement et import réel **locaux uniquement**,
sur `feature/parts-sales-alignment-20261118`, issu du commit `755cab7`.
Aucun déploiement, redémarrage, changement de configuration ou de données métier
n'a été effectué sur BODEFM pour cette évolution. L'utilisateur exige une
notification et son Go explicite avant toute bascule.

## Problème vérifié

Sales → Parts Classification utilisait des détails dont la couverture s'arrêtait
au 2 octobre 2026, importés le 4 octobre. Les seuls en-têtes de rapprochement
présents dans la copie BODEFM étaient `Reference Only` / `Imported Reference` ;
ils ne fournissaient pas les buffers nécessaires à une relance de l'ancien import.
Le rafraîchissement quotidien de Revenue et celui des mesures Parts Fulfillment
ne reconstruisaient pas ce détail Pièces.

Le modèle actuel expose bien `FactSalesAllocation`, `Neg_llf_complete` et
`Global CA Detailled`, avec les colonnes utilisées vérifiées par métadonnées et
requêtes de lecture. Aucune mesure, relation ou table Power BI n'a été modifiée.

## Contrat de données

- Montant de référence : `[CA Comptable EUR]` et les lignes
  `FactSalesAllocation[AccountingCA_EUR]`, à la maille facture/date comptable.
- Identifiant : `INVOICEKEY_V2` fourni par le modèle, conservé comme texte.
  Il n'est pas reconstruit. Les anciennes bridges ne sont pas réintroduites.
- Client et dimensions comptables : `Global CA Detailled`, sous MI / PARTS /
  hors INTERCO. Le montant doit correspondre à celui de la facture/date. Un
  client absent ou non unique ne reçoit pas d'attribution arbitraire.
- Lignes pièces : `Neg_llf_complete`, limité aux clés de facture présentes dans
  le périmètre comptable. Aucun filtre sur la date de picking.
- Ventilation : quantité facturée signée × prix unitaire net réel
  (`NLLF_QTEFAC × NLLF_PXNREEL`). Les poids, dans la devise de la facture,
  répartissent son CA EUR ; ils ne servent pas de montant EUR autonome.
- Les dates comptables distinctes sont conservées. Les avoirs et les poids
  négatifs restent signés. Les valeurs nulles comptables ne deviennent pas des
  attributions. Une somme de poids nulle reste sans attribution aux lignes.
- La référence CAT existante reste la source de Major Class / Minor Class / PPC.
  Une absence totale du catalogue ne peut effacer une classification existante.

Les groupes stockés sont facture/date/pièce/constructeur. `source_line_count`
conserve le nombre de lignes sources. Le libellé **Invoice Line Allocations**
précise qu'une même ligne peut participer à plusieurs dates comptables : ce
compteur n'est ni une quantité physique vendue ni un nombre de commandes livrées.

Parts Fulfillment conserve son attribution aux commandes et ses cohortes.
Les taux de liaison aux lignes et aux commandes ne sont pas forcés à l'égalité.
Order Intake, ses règles de date et sa comparabilité fiscale ne sont pas changés.

## Contrôles et fonctionnement

L'import effectue des lectures paginées avec contrôles de cardinalité, de clés
dupliquées et de progression. Les totaux facture/date doivent réconcilier la
mesure comptable à 0,01 EUR. Des contrôles globaux avant/après détectent une
modification de la source pendant la collecte. Ils ne remplacent pas un audit
exhaustif des attributions métier ni une version transactionnelle du modèle.

Les données sont préparées dans un fichier temporaire privé avant activation.
L'écriture, le contrôle du total stocké et la désactivation du périmètre remplacé
sont transactionnels. Une erreur conserve les anciens détails actifs. Le fichier
temporaire est supprimé après l'opération ; le verrou OS empêche deux imports
simultanés. Les identifiants de stockage sont stables pour éviter les doublons.

Les montants Pièces sont stockés en `decimal(28,10)` ; la capacité entière
antérieure est conservée. L'insertion SQL Server utilise des paramètres avec
précision explicite et refuse une ancienne colonne monétaire à quatre décimales.
Les règles Revenue, l'index actif et son prédicat littéral ne sont pas modifiés.

Le scheduler réutilise l'heure, la minute et le fuseau de Business Overview
(configuration habituelle : 05:00 GMT), avec reprise après échec et verrou.
Il choisit seulement une identité administrative existante autorisée au rapport
Global ; il ne crée aucun compte ni droit. Les protections du connecteur et des
lectures de détail sont conservées. Tous les rafraîchissements automatiques
restent désactivés dans la prévisualisation locale.

L'écran distingue la date du dernier import de la couverture des données. Il
signale une couverture de détail antérieure au CA certifié et les plages plus
anciennes que l'import courant. Un import n'est pas présenté comme la date
d'actualisation du modèle Power BI. La notice Machines est masquée dans Parts.

## Recette sur données réelles

La copie SQL isolée est `localhost\\MSSQL_IA /
Mining360App_BODEFM_Local_20261116`. Sauvegarde COPY_ONLY compressée et contrôlée
par `RESTORE VERIFYONLY` avant les migrations Pièces. La base métier de BODEFM,
ses utilisateurs, ses rôles et ses intégrations n'ont pas été écrits.

Import du 19 novembre, couvrant le 1er janvier 2025 au 19 novembre 2026 :

- 60 289 groupes comptables ; CA source : 469 554 573,02260065 EUR.
- 316 529 groupes de lignes attribués ; 314 598 876,6815500002 EUR.
- Exceptions conservées : 8 862 groupes sans lignes, neuf sans client unique,
  deux avec une somme de poids nulle.
- Dernière date comptable observée : 16 novembre 2026.

Contrôle octobre 2026, avec un CA certifié local inchangé :

| Indicateur | Ancien détail | Après import réel et catalogue |
| --- | ---: | ---: |
| CA certifié | 20 100 153,90 EUR | 20 100 153,90 EUR |
| CA rapproché aux lignes | 344 699,93 EUR | 19 281 855,70 EUR |
| Couverture | 1,71 % | 95,93 % |
| CAT classifié | 330 581,01 EUR | 16 339 832,86 EUR |
| Autres marques | 4 764,12 EUR | 2 448 911,67 EUR |
| CA sans liaison aux lignes | 19 755 453,97 EUR | 818 298,21 EUR |
| Allocations de lignes | 876 | 21 081 |

Ce sont des relevés de contrôle, pas des constantes applicatives. Le premier
passage sans le catalogue avait laissé les nouvelles pièces CAT non classifiées ;
ce résultat n'a pas été déployé. La recette complète ci-dessus inclut le catalogue.

Le CA Revenue de la copie locale reste le snapshot BODEFM du 15 novembre.
Ses totaux YTD ne doivent pas être présentés comme ceux du serveur actuel.
L'accord au centime est établi ici pour octobre et pour les contrôles du modèle
utilisés par l'import ; les autres pages et montants Revenue locaux sont conservés.

87 tests SQL ciblés étaient réussis avant les derniers contrôles de nullité ;
le dernier passage complet de 89 tests est réussi le 20 novembre. Ils couvrent
notamment les dates multiples, avoirs, zéros initiaux, succursales différentes,
valeurs nulles, échecs, idempotence, droits, scheduler, catalogue et régressions BO.
Des essais intermédiaires ont échoué en préconnexion TCP sur le poste ; le passage
final utilise la mémoire partagée de l'instance SQL locale, sans changer le serveur.

Recette Edge finalisée le 22 novembre, sur la prévisualisation locale :

- Business Overview et Sales → Parts ouverts avec HTTP 200 ; chiffres d'octobre
  contrôlés sur la réponse réelle, puis affichés dans la page.
- Captures aux largeurs 1 600, 1 024 et 390 pixels, après disparition du loader ;
  aucun débordement horizontal de page ni exception JavaScript observés.
- Export PPC de 570 groupes vérifié alors que la vue demandait la page 2 avec
  cinq groupes par page : l'export contient bien tout le périmètre, avec le CA
  attribué et les 21 081 allocations de lignes réconciliés.
- Session temporaire du seul compte propriétaire local supprimée après le test ;
  aucun code de connexion ni e-mail envoyé. BODEFM inchangé.

Les captures et `browser-check.json` restent dans le répertoire privé de preuves.
L'ouverture locale observée à 1,14 seconde ne mesure pas la performance BODEFM ;
la vérification de performance distante reste à faire après un déploiement autorisé.

## Catalogue et première livraison

Le catalogue de la copie de test était vide. Les 960 789 références actives du
dernier import vérifié du poste ont été exportées et contrôlées avant leur copie.
Source : `Liste_pieces_CAT_S1_2026 (2).xlsb`, import terminé, SHA-256 d'origine
`c7b50592c52bd1599c9e051108d86d02363ab6c1c5154165a512bf2cca530710`.

L'archive privée `validated-cat-catalog.jsonl.gz` a le SHA-256
`f57102d26cbc2db59f6d9f1fcfb66c969eacdc301d631696cc53b4fbd80cc081`.
Elle n'appartient pas à Git. Le chargeur vérifie le checksum, les contrôles par
classe et le nombre de lignes ; il refuse d'écraser un catalogue existant.
La publication Business Mapping v9 n'est pas modifiée.

Après Go seulement : vérifier l'état réel de la cible, sauvegarder et vérifier
la base, identifier les anciennes lignes actives pour un rollback ciblé, contrôler
les hashes du code, appliquer `0151_parts_sales_model_source` puis
`0152_parts_sales_source_precision`, installer le catalogue s'il est absent,
réaliser l'import et les contrôles financiers, puis vérifier les pages, droits
et temps de réponse du serveur. Aucun redémarrage IIS/SQL global n'est requis.

Commande de l'import : `sync_parts_sales_model --username <identité existante
autorisée>`, avec bornes optionnelles `--start-date` / `--end-date`.
`PARTS_SALES_AUTO_SYNC` reprend par défaut le réglage de l'automatisme Revenue.
Le retour arrière doit conserver la précision SQL et restaurer uniquement le
périmètre Pièces sauvegardé ; ne pas restaurer toute la base après de nouvelles
activités métier. Un calendrier atteint ne vaut jamais autorisation de déployer.

Preuves privées : `.runlogs/parts-sales-alignment-20261118/` à la racine canonique.
Code et données de cette évolution restent locaux jusqu'à la revue de livraison.
