# Parts Orders & Sales Fulfillment — mémoire de reprise

Consolidation du 14 novembre 2026. Projet : Mining360IA, dépôt canonique
`C:\Users\diagnepa\Documents\MBA\Mining360IA`. Cette intervention est documentaire.
Elle ne modifie ni modèle, mesure, requête applicative, permission, ni serveur.

## Ordre de lecture et portée des preuves

1. [Index du dossier intégré](parts-orders-sales-fulfillment/README.md).
2. [Guide complet fourni par l'utilisateur](parts-orders-sales-fulfillment/DOCUMENTATION_COMPLETE.md)
   : reconstitution des échanges Power BI du 10 au 13 novembre, avec ses niveaux
   « confirmé », « revérifié », « reconstitution », « à vérifier » et « proposé ».
3. [Registre d'intégration](parts-orders-sales-fulfillment/sources/REGISTRE_SOURCES.md)
   : fichiers réellement reçus, annexes absentes et provenance.
4. [Implémentation Mining360](PARTS_FULFILLMENT_IMPLEMENTATION_2026-11-13.md),
   [publication BODEFM](PARTS_FULFILLMENT_BODEFM_RELEASE_2026-11-13.md),
   [copie des visuels et adaptations ultérieures](PARTS_VISUAL_COPY_2026-11-14.md).

La lecture du guide ne constitue pas un nouvel audit live du modèle ni une
réexécution indépendante de ses contrôles Excel. Les observations applicatives
ci-dessous proviennent du code et des reçus de la session précédente, relus pour
cette consolidation. Les sources d'origine ne sont pas réécrites pour effacer
les écarts de dates, de vocabulaire ou de population.

## Règles à conserver

- Montants de CA : écritures MI / PARTS / hors INTERCO, en EUR. L'extraction
  documentée exclut les numéros de pièce vides ; elle n'est donc pas une preuve
  d'exhaustivité de toute la comptabilité générale.
- Grain final : `InvoiceKey_V2 × Date ecritures`, conservé de `PQ_AccountingSales`
  à `FactSalesAllocation`. Ne pas recopier le CA complet dans chaque ligne LLF.
- `PK_V2` : `NumeroCommande|Societe|SuccursaleCommande`, sans client ; LLF utilise
  `NLLF_SUCC`. `InvoiceKey_V2` : `Societe|Societe-SuccursaleFacturation|NumeroFacture`,
  sans client ; LLF utilise `NLLF_SUCCFAC`. Préserver les identifiants textuels.
- `Neg_llf_complete` et `OrderHeader History` préparent la bridge Power Query ;
  les factures à commande unique alimentent `PQ_SingleOrderInvoices`.
- La comptabilité pilote la jointure externe gauche vers cette correspondance.
  Les factures sans attribution exploitable, dont les multicommandes, restent
  dans le CA. Aucune répartition proportionnelle multicommande n'est implémentée.
- Les cohortes comparent les mois calendaires : `Current Month`, `Last Month`,
  `2+ Months`, `Unallocated`, `Future Order`. Unallocated ne signifie ni facture
  manquante, ni CA non opérationnel. Future Order reste un contrôle distinct.
- Relation finale documentée : `Date[Date] → FactSalesAllocation[Date ecritures]`,
  active, simple, `1:*`. Ne pas confondre fusion Power Query et relation de modèle.
- Order Intake porte sur les commandes créées durant le mois, facturées ou non.
  Il n'est pas reconstruit à partir des seules écritures de CA.
- Aucun filtre Customer / Site. Les filtres de cohorte limitent les détails et
  ne changent pas les dénominateurs des KPI. L'absence de filtre client n'élargit
  jamais les droits.

## Mesures et champs

La correspondance est relue dans [parts_fulfillment_service.py](../reports/parts_fulfillment_service.py).
Le guide importé utilise le nom documentaire `[CA 2+ Months]` ; le nom réellement
résolu et utilisé par le service est **`[CA +2 Months]`**. Ne pas renommer le modèle
pour aligner la prose historique.

| Agrégat | Mesure existante consommée |
| --- | --- |
| Nouvelles commandes | `[Order Intake EUR]` |
| CA comptable | `[CA Comptable EUR]` |
| Commandes du même mois | `[CA Current Month]` |
| Commandes du mois précédent | `[CA Last Month]` |
| Commandes d'au moins deux mois | `[CA +2 Months]` |
| Sans attribution exploitable | `[CA Unallocated]` |
| Commande d'un mois ultérieur | `[CA Future Order]` |
| Contrôle source | `[CA Reconciliation Difference]` |

Les détails lisent `FactSalesAllocation` : `AccountingCA_EUR`, `Date ecritures`,
`InvoiceKey_V2`, `PQ_SingleOrderInvoices.Order Date`,
`PQ_SingleOrderInvoices.PK_V2`, `SalesCohort`.
Le backend ne recalcule ni ces clés, ni les bridges, ni les attributions.

## Application et dernière publication vérifiée

Page : `/business-review/parts-fulfillment/`. Endpoints existants sous
`/api/business-review/parts-fulfillment/` : `summary/`, `details/`, `export/`.
Le registre du rapport fournit le workspace et le modèle. Le transport configuré
Power Automate reste côté serveur ; aucun secret n'appartient à la documentation.

Deux colonnes par mois : commandes bleues et CA empilé par cohorte, avec historique
de 12 mois. Le bandeau secondaire de trois KPI a été supprimé à la demande de
l'utilisateur. Seul le libellé de légende `Sales — Future Order` a été retiré : le
montant reste dans les piles, tooltips, détails et réconciliation. Les actions
Copier le visuel utilisent l'export PNG partagé de Business Overview. Le lien
d'accès est jaune, à texte bleu marine et aligné avec les autres actions.

Dernier correctif applicatif vérifié :
`59eac66e80a711fadf98f1f2c4d0fedebd7dfde7`, branche
`feature/parts-fulfillment-20261113`.
Sauvegarde : `D:\Mining360Backups\PartsFulfillment_20261113_204810_59eac66e`.
La date du nom de sauvegarde est celle du serveur ; la consolidation est datée
du 14 novembre selon le poste de travail.

Reçus privés relus : `.runlogs/parts_fulfillment_deploy/deployment-result-59eac66e.json`
et `post-verification-59eac66e.json`. Installation réussie ; application et base
`ok` ; page authentifiée, Overview, assets, synthèse et quatre contextes de détail
HTTP 200. Test d'alignement local Edge à 1440, 1024, 390 et 320px : réussi. Le reçu
serveur n'atteste pas une nouvelle capture navigateur distante.

## Références financières et validation

Octobre 2026, comparaison des instantanés au centime :

| Mesure | Guide fourni / capture historique | Dernier reçu applicatif relu |
| --- | ---: | ---: |
| Order Intake | environ 124,49 M€ ; valeur arrondie | 94 157 590,12 € |
| CA Comptable | 20 100 153,90 € | 20 100 153,90 € |
| Current Month | 8 416 346,36 € | 8 416 346,36 € |
| Last Month | 4 817 567,64 € | 4 817 567,64 € |
| 2+ Months | 6 047 941,69 € | 6 047 941,69 € |
| Unallocated | 818 298,21 € | 818 298,21 € |
| Future Order | 0,00 € | BLANK source, présenté à 0 dans ce contexte valide |
| Réconciliation | 0,00 € | 0,00 € après arrondi |

L'écart d'Order Intake n'est pas expliqué par une définition inspectée ; ne pas
forcer le service à reproduire une ancienne capture. Toutes ces valeurs sont des
relevés datés, jamais des constantes applicatives.

Le guide rapporte 60 115 lignes uniques facture/date et 468 038 287,09 € conservés
entre les deux feuilles d'Exports N.xlsx, avec neuf montants vides. Ces contrôles
restent attribués au dossier fourni : ils n'ont pas été relancés ici. Sa capture
2026 couvre le 1er janvier au 1er novembre inclus ; ne pas la qualifier d'année
complète. Une réconciliation arithmétique n'approuve pas toutes les attributions.

## Points restant à vérifier

- Expression exacte et périmètre de `[Order Intake EUR]`, montant de ligne EUR
  (`Montant_EU_lines` / `MontantEU_Lines`), change, HT/TTC, annulations et code
  complet final de `OrderLineItems History`. Les essais de métadonnées précédents
  n'ont pas fourni ces définitions ; aucun nouveau code live n'est affirmé ici.
- Rôles RLS effectivement appliqués à la table finale et catalogue exhaustif
  des relations publiées. Le backend réserve actuellement les lectures globales
  aux administrateurs sans restriction, avec rapport configuré Global ; les
  autres comptes reçoivent `SCOPED_QUERY_NOT_CONFIGURED` jusqu'à validation d'une
  identité déléguée. Ce verrou ne prouve pas un audit RLS du modèle.
- Le ratio Current Month / Order Intake reste non validé tant que les bases EUR,
  fiscales et de périmètre ne sont pas confirmées. Ne pas le confondre avec
  Current Month / CA Comptable ; le bandeau qui l'affichait n'est plus rendu.
- Clés incomplètes, collisions, dates d'en-tête contradictoires, couverture du
  calendrier et branche de garde en cas de date comptable invalide dans la formule
  historique. Les motifs fins d'Unallocated ne sont pas des colonnes confirmées.
- L'écart historique de 2 816 741,34 € entre vues comptables demeure signalé dans
  le guide, sans cause définitivement démontrée. Les anciens totaux de populations
  différentes ne doivent pas être comparés sans aligner leurs filtres.
- Les annexes absentes et les références `[S…]` / `[T…]` non résolues sont recensées
  dans le [registre](parts-orders-sales-fulfillment/sources/REGISTRE_SOURCES.md).

## Reprise et maintenance

Conserver séparément le flux final et les essais V1/V2/V3/V4. Ne pas réintroduire
de dépendance Power Query parent → dérivée → parent, de sélection arbitraire de
commande sur facture multicommande, ni de jointure qui multiplie le CA. Les règles
Revenue, permissions et procédures BODEFM restent protégées par AGENTS.md.
Une intégration documentaire n'autorise aucun déploiement ou changement de modèle.
