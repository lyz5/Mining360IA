# Parts Orders & Sales Fulfillment
## Documentation fonctionnelle et technique — réalisation pas à pas

**Application cible :** Mining360 → Business Overview  
**Modèle sémantique :** Mine Logistics Report  
**Périmètre demandé :** pièces, division Mine, montants en EUR ; CA hors INTERCO  
**État documenté :** solution Power Query / Power BI réalisée dans les échanges des 10–13 novembre 2026  
**Date de constitution du dossier :** 14 novembre 2026  
**Destinataire :** Codex et équipe de maintenance Mining360 / reporting  
**Statut :** reconstitution documentée, avec contrôles indépendants des exports fournis ; ce n’est pas un audit du modèle publié actuel.

---

## Mode d’emploi pour Codex

Cette documentation explique **comment le résultat a été obtenu**, et non seulement comment reproduire l’apparence du dashboard. Lire d’abord les sections 1 à 5 et 15 à 22 pour comprendre l’état final. Les sections 6 à 14 expliquent les diagnostics, les corrections et les versions abandonnées.

Les fichiers `sql/`, `powerquery/` et `dax/` sont classés et commentés. Une définition marquée **historique** n’est pas nécessairement à remettre en production. Une définition marquée **reconstitution** traduit les étapes confirmées dans les échanges ; elle ne doit pas être présentée comme un export exact du code actuellement publié.

**Ne pas modifier le modèle, remplacer les mesures existantes ou supprimer les anciens objets pour simplement intégrer cette documentation au dépôt.** Le modèle final de consommation de cette page utilise `FactSalesAllocation`, et non les anciennes mesures `Sales … V3/V4`.

### Niveaux de preuve utilisés

| Marqueur | Signification |
|---|---|
| **Confirmé** | Code fourni dans la conversation, action explicitement confirmée ou valeur visible dans une capture. |
| **Revérifié** | Valeur recalculée à partir d’un fichier joint relu pour constituer ce dossier. |
| **Reconstitution** | Code documentaire reconstruit à partir d’étapes UI confirmées et des colonnes réellement exportées. |
| **À vérifier** | Élément non fourni ou non inspectable dans le modèle live. |
| **Amélioration proposée** | Recommandation de maintenance, non présentée comme déjà déployée. |

Les références `[S…]` désignent les sources du projet ; `[T…]` les documents techniques officiels utilisés pour clarifier certains comportements. Le registre complet se trouve dans `sources/REGISTRE_SOURCES.md`.

---

## Sommaire

1. Objectif métier et résultat obtenu
2. Les trois temporalités et les cinq catégories
3. Architecture finale, grain et chemins de données
4. Inventaire des tables et des versions
5. Périmètres, montants, devises et limites de couverture
6. Situation de départ et problèmes rencontrés
7. Correction des clés de commande
8. Correction des extractions et validation des PK
9. Construction et validation d’InvoiceKey_V2
10. Bridges V1, V2, V3, V4 et dimension facture
11. Relations intermédiaires et rôle du calendrier
12. Diagnostic des factures multicommandes
13. Essais DAX, résultats et limite de performance
14. Décision de pré-calculer dans Power Query
15. Création de PQ_BridgeCommandeFacture
16. Création de PQ_AccountingSales
17. Création de PQ_SingleOrderInvoices
18. Création de FactSalesAllocation
19. Calcul de SalesCohort
20. Chargement et relation finale à Date
21. Mesures DAX finales
22. Résultats vérifiés et réconciliation
23. Détail des commandes et factures
24. Order Intake : ce qui est connu et ce qui manque
25. Intégration Mining360 et contrat de données
26. Historique des erreurs et enseignements
27. Contrôles de non-régression et exploitation
28. Sécurité, performance et évolution SQL/ETL
29. Limites restantes et travail documentaire Codex
30. Inventaire des annexes et procédure de reproduction

---

## 1. Objectif métier et résultat obtenu

Le besoin initial était un dashboard mensuel **Parts Order Intake vs. Sales Fulfillment** permettant de comparer :

- la valeur des nouvelles commandes de pièces reçues pendant le mois ;
- le chiffre d’affaires comptabilisé pendant ce mois ;
- l’origine de ce CA selon le mois de création des commandes associées.

L’objectif n’était pas de ventiler le montant théorique des commandes selon une date de facture, mais bien de **partir des écritures comptables réelles**, puis de retrouver la commande d’origine pour classifier les ventes.

L’image de référence proposait une barre de commandes et une barre de ventes empilées par mois. Ses valeurs étaient illustratives. Les captures finales utilisent les données réelles de `Mine Logistics Report`. L’interface Mining360 a ensuite été spécifiée pour `Business Overview`, **sans filtre Customer / Site**, conformément à la décision finale de l’utilisateur. [S1, S6, S7]

### Ce qui a permis d’aboutir

La progression décisive a été :

1. séparer la clé de commande de la clé de facture et retirer la dépendance au client lorsque les contrôles le permettaient ;
2. normaliser les composants de `PK_V2` et supprimer un filtre d’extraction qui dépendait encore du numéro client ;
3. disposer de l’historique des en-têtes de commande pour retrouver les dates anciennes ;
4. partir du CA détaillé par date comptable et conserver les écritures non rapprochées ;
5. déplacer les jointures répétées des mesures DAX vers une préparation Power Query ;
6. conserver un grain **facture × date comptable** et réserver l’attribution directe aux factures à commande unique ;
7. calculer une catégorie par ligne de faits, puis utiliser des sommes DAX simples.

### Ce qui est réellement validé

La table finale est chargée, liée activement à `Date`, et les cinq catégories réconcilient le CA dans les captures finales. La relecture d’`Exports N.xlsx` confirme la conservation du grain et des montants entre la préparation comptable et la fusion finale. [S2, S6]

La réalisation du frontend Mining360 par Codex, son API, ses routes, ses tests de sécurité et son déploiement **ne sont pas attestés par les sources de ce dossier**. La dernière partie décrit donc un contrat d’intégration, pas une implémentation déjà inspectée.

---

## 2. Les trois temporalités et les cinq catégories

### 2.1 Date de commande

`OrderHeader / OrderHeader History[DATECOMMANDE]` décrit la création de la commande. Elle permet de calculer l’Order Intake et l’ancienneté de la commande lorsqu’une vente est comptabilisée.

### 2.2 Date comptable

`Global CA Detailled[Date ecritures]`, puis `FactSalesAllocation[Date ecritures]`, détermine le mois dans lequel le CA est analysé.

Une facture peut produire plusieurs écritures à des dates différentes. Il faut conserver les différentes dates comptables : utiliser uniquement une date d’en-tête de facture ne répond pas au besoin.

### 2.3 Date de facture opérationnelle

`NFAC_DATEFAC` participe à l’extraction historique des factures opérationnelles. Ce n’est pas la date de référence du graphique comptable.

**Formulation à utiliser :** « CA comptabilisé pendant le mois et attribué à des commandes de telle ancienneté ». Éviter « facturé pendant le mois » lorsque l’on parle réellement de date d’écriture.

### 2.4 Catégories finales

| SalesCohort | Définition par rapport au mois comptable |
|---|---|
| `Current Month` | Commande créée dans le même mois civil. |
| `Last Month` | Commande créée dans le mois civil précédent. |
| `2+ Months` | Commande créée au moins deux mois civils auparavant. |
| `Unallocated` | Pas de date de commande exploitable après la fusion vers les factures à commande unique. |
| `Future Order` | Commande créée dans un mois civil postérieur au mois comptable. |

Exemple pédagogique, non issu d’une transaction réelle : pour une écriture comptable d’octobre 2026, une commande d’octobre est `Current Month`, une commande de septembre est `Last Month`, une commande d’août ou antérieure est `2+ Months`, et une commande de novembre est `Future Order`.

Une commande du 25 octobre et une écriture du 10 octobre restent dans `Current Month` : le calcul compare les **mois**, pas l’ordre exact des jours.

`Unallocated` n’est pas synonyme de « facture absente », de « vente non opérationnelle » ou d’« anomalie comptable ». La catégorie regroupe les cas non attribués par la procédure courante. [S1]

---

## 3. Architecture finale, grain et chemins de données

### 3.1 Préparation des données

```text
SNOWFLAKE
  A_BRONZE_IE_NEG_ENT  ──> OrderHeader History ──────────────┐
                                                         │ PK_V2 → date
  A_BRONZE_IE_NEG_LLF ──> Neg_llf_complete ──> PQ_BridgeCommandeFacture
                                                         │
                                                         │ OrderCount = 1
                                                         ▼
                                              PQ_SingleOrderInvoices
                                                         │
                                                         │ au plus une ligne / facture
SQL SERVER                                               │
  ana_f_ecriture_analytique                               │
            │                                            │
            ▼                                            │
  Global CA Detailled                                    │
            │ MI / PARTS / hors INTERCO                   │
            ▼                                            │
  PQ_AccountingSales ─────────── LEFT OUTER JOIN ──────────┘
  grain facture × date comptable
            │
            ▼
  FactSalesAllocation
  + PK de commande, date de commande, SalesCohort
```

### 3.2 Consommation dans Power BI

```text
Date[Date] (1)
      │ relation active, filtrage simple
      ▼
FactSalesAllocation[Date ecritures] (*)
      │
      ├── CA Comptable EUR
      ├── CA Current Month
      ├── CA Last Month
      ├── CA 2+ Months
      ├── CA Unallocated
      ├── CA Future Order
      └── CA Reconciliation Difference
```

Pour cette page, `FactSalesAllocation` est volontairement liée **uniquement à `Date`**. Les associations commande–facture sont déjà matérialisées dans ses colonnes. Les autres tables peuvent rester dans le rapport pour leurs usages propres, mais ne doivent pas créer un nouveau chemin temporel vers cette table sans analyse.

Une relation active supplémentaire depuis un `OrderHeader` lui-même filtré par le même calendrier pourrait imposer à la fois le mois de création et le mois comptable, et éliminer les commandes anciennes. Ce risque explique le choix final ; ce n’est pas une interdiction générale d’utiliser une dimension Commande dans tout modèle. [S1 ; clarification technique T1, T2]

### 3.3 Grain exact

| Objet | Grain voulu |
|---|---|
| `OrderHeader History` | Une ligne par commande identifiée par `PK_V2`, après contrôle. |
| `Neg_llf_complete` | Lignes opérationnelles, plusieurs lignes possibles par facture et commande. |
| `PQ_BridgeCommandeFacture` | Couple distinct `PK_V2`–`INVOICEKEY_V2`, enrichi de la date et du nombre de commandes. |
| `PQ_SingleOrderInvoices` | Au plus une ligne par `INVOICEKEY_V2`. |
| `PQ_AccountingSales` | Une ligne par `InvoiceKey_V2` et `Date ecritures`. |
| `FactSalesAllocation` | Même grain que `PQ_AccountingSales`, avec une attribution unique ou non attribuée. |

**Le nom `FactSalesAllocation` ne signifie pas qu’une allocation proportionnelle multicommande a été implémentée.** La version réalisée attribue 100 % du montant à l’unique commande lorsqu’elle est éligible ; elle laisse les autres cas dans la population non attribuée.

---

## 4. Inventaire des tables et des versions

| Table / requête | Rôle | État documentaire |
|---|---|---|
| `OrderHeader` | En-têtes initialement limités à 2025 et suivants, puis modifiés. | Plusieurs versions dans les échanges. |
| `OrderHeader History` | Source d’en-têtes utilisée dans la fusion Power Query finale. | Nom exact confirmé dans le code M. |
| `OrderLineItems` | Lignes, références pièces, quantités et statuts. | SQL historique fourni intégralement. |
| `OrderLineItems History` | Historique élargi annoncé par l’utilisateur. | Code final intégral non fourni. |
| `Neg_llf_complete` | Lignes facture/livraison, source des associations. | SQL et évolution des clés disponibles. |
| `Neg_FAC_complete` | En-têtes facture ; pas de numéro de commande exploité ici. | SQL disponible. |
| `Global CA Detailled` | Écritures comptables détaillées et date d’écriture. | Source du CA final. |
| `Global CA Aggregated` | CA regroupé par clé facture V1, client inclus. | Conservé pour l’ancien modèle ; pas source mensuelle finale. |
| `Global CA Detailled (2)` | Copie de diagnostic de couverture/calendrier. | Pas une nouvelle vérité métier. |
| `Mining Customer New` | Clients dont `tie_bu_code='MI'`. | Liaison ancienne ; nouvel en-tête déclaré non lié. |
| `BridgeCommandeFacture` | Couples ancienne PK + InvoiceKey V1. | Diagnostic / ancien modèle. |
| `BridgeCommandeFacture_V2` | Ancienne PK + InvoiceKey_V2. | Diagnostic. |
| `BridgeCommandeFacture_V3` | PK_V2 + InvoiceKey_V2. | Diagnostic ayant permis de valider le rapprochement. |
| `BridgeCommandeFacture_V4` | V3 + date de commande par LOOKUPVALUE. | Essai de performance ; non source Power Query. |
| `DimFacture` / `DimFacture_V2` | Dimensions utilisées dans les modèles intermédiaires. | Non nécessaires aux sommes finales sur FactSalesAllocation. |
| `PQ_BridgeCommandeFacture` | Associations pré-calculées + date + OrderCount. | Préparation finale. |
| `PQ_InvoiceOrderCount` | Comptage créé séparément au début. | Remplacé dans le flux principal par un comptage local dans la bridge. |
| `PQ_AccountingSales` | Agrégation facture × date comptable. | Préparation finale. |
| `PQ_SingleOrderInvoices` | Factures à commande unique. | Préparation finale. |
| `FactSalesAllocation` | Comptabilité enrichie et catégorisée. | Table finale de consommation. |

Les noms de requêtes Power Query et les noms du modèle ne sont pas supposés identiques par principe. Utiliser les références réellement présentes dans le fichier. Ne pas remplacer aveuglément `OrderHeader` par `OrderHeader History` dans toutes les expressions archivées.

---

## 5. Périmètres, montants, devises et limites de couverture

### 5.1 CA comptable

La requête SQL Server applique :

```sql
WHERE a.feca_taf_code = 'CA'
  AND a.feca_tps_ak_date_ecriture_comptable >= 20250101
  AND a.feca_bu_code = 'MI'
  AND UPPER(LTRIM(RTRIM(a.feca_lob_code))) = 'PARTS'
  AND NULLIF(
        LTRIM(RTRIM(CONVERT(nvarchar(100),
            a.feca_num_piece_ecriture_comptable))), N''
      ) IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM NMBEPM.dbo.v_epm_canaux_distributions AS canal_interco
      WHERE canal_interco.cdt_sk = a.feca_cdt_sk
        AND UPPER(LTRIM(RTRIM(canal_interco.cdt_lib_canal_distribution))) = 'INTERCO'
  )
```

Le montant est calculé comme :

```sql
SUM(a.feca_montant_credit_consolidation_analytique
  - a.feca_montant_debit_consolidation_analytique) AS [CA euro]
```

Le code complet figure dans `sql/04_Global_CA_Detailled_sqlserver.sql`.

**Limite importante :** ce « total comptable » est le total de l’extraction définie ci-dessus. Les écritures sans numéro de pièce sont exclues. Il ne faut donc pas l’assimiler sans contrôle à l’ensemble absolu de toutes les écritures CA Mine/Parts de la comptabilité générale.

Le `NOT EXISTS` exclut les canaux reconnus comme INTERCO. Il ne démontre pas à lui seul que chaque écriture restante possède un canal renseigné et classifié.

### 5.2 Sources opérationnelles plus larges

L’historique `OrderHeader History` a été conservé sans borne inférieure de date de création, afin de retrouver les dates des commandes qui ont produit le CA analysé. Les sources LLF/FAC ne portent pas nécessairement elles-mêmes le filtre MI/PARTS.

Cela est acceptable pour une **table de correspondance** : le montant final provient toujours des écritures SQL déjà filtrées. Cela ne suffit pas, en revanche, à garantir le périmètre de l’**Order Intake**, qui doit compter aussi les commandes encore non facturées.

### 5.3 Statuts, exclusions de lignes et périmètre Parts

Le SQL historique `OrderLineItems` exclut certains constructeurs et une longue liste de références ; il requiert aussi des valeurs renseignées pour société, succursale, contre-marque et référence. La liste complète reçue est conservée dans `sql/06_OrderLineItems_source_historique_snowflake.sql`.

Leur signification métier n’a pas été fournie ligne par ligne. Ne pas les décrire comme une règle universelle « toutes les pièces », ni en supprimer une partie sans validation. Une contre-marque vide exclue peut, par exemple, changer la population de lignes ; son caractère légitime pour l’Order Intake reste à vérifier.

### 5.4 Devise et taxe

`NENT_CDETTC AS Order_amount`, `nlig_pxvteht AS AmountNet` et `Montant_EU_lines` ne sont pas interchangeables. Le premier nom suggère TTC ; le second désigne un prix HT ; la formule complète de conversion et de quantité de `Montant_EU_lines` n’a pas été transmise.

**Aucune formule de conversion EUR n’est inventée dans ce dossier.** La mesure `[Order Intake EUR]` existe dans la capture finale, mais son expression exacte reste à extraire du modèle pour achever sa documentation.

---

## 6. Situation de départ et problèmes rencontrés

Le premier modèle utilisait `OrderHeader`, `OrderLineItems`, LLF, FAC, une bridge, `DimFacture`, le CA agrégé et le CA détaillé. Le rapport mélangeait plusieurs chemins de dates et de filtres.

Les premiers résultats présentaient notamment :

- des factures multicommandes ;
- des dates de commande vides dans les associations ;
- des clés de commande non retrouvées ;
- une relation comptable au calendrier inactive dans l’état montré à cette étape ;
- un CA limité par les filtres opérationnels ;
- des totaux de cohortes qui ne réconciliaient pas la référence comptable utilisée ;
- des mesures longues à afficher.

Les valeurs successives de 51 M€, 54 M€, 168–173 M€, 215–220 M€, 314 M€ et 466–468 M€ ne sont **pas des variantes d’un même total dans un contexte invariant**. Elles correspondent à des filtres, périodes, actualisations ou périmètres de rapprochement différents. La comparaison n’est valable qu’après alignement de la date comptable, des sources et de la sélection. [S1, S4]

### Pourquoi il ne fallait pas copier le CA dans LLF

Une facture peut avoir de nombreuses lignes LLF. Copier son CA complet dans chacune de ces lignes et sommer produirait une multiplication. Le même danger existe si une facture est reliée à plusieurs commandes et si tout son CA est attribué à chacune.

La solution finale commence donc par une agrégation comptable et impose une correspondance au plus un-à-un vers la table d’attribution simple.

---

## 7. Correction des clés de commande

### 7.1 Ancienne construction

LLF utilisait initialement :

```sql
l.NLLF_NUMCDE
|| l.NLLF_NUMCLI
|| TRY_TO_NUMBER(l.NLLF_SOC)
|| TRY_TO_NUMBER(l.NLLF_SUCC)
```

L’en-tête utilisait une concaténation texte comprenant également le client. Les conversions de société/succursale n’étaient pas identiques entre les deux côtés.

Deux problèmes indépendants existaient : la présence du client comme composant obligatoire, et les variations de format des composants.

### 7.2 Client manquant

L’utilisateur a signalé environ 270 000 lignes LLF avec numéro client vide. Un test ultérieur sur une population brute plus large a identifié 578 744 lignes. Ces deux chiffres ne portent pas sur une extraction démontrée identique ; ils ne doivent pas être présentés comme une contradiction résolue.

Dans Snowflake, une concaténation contenant NULL renvoie NULL ; une chaîne vide n’est pas la même chose. Un client NULL pouvait donc empêcher la création de la PK, tandis qu’un client vide pouvait produire une clé partielle différente de celle de l’en-tête. [S1 ; T3]

### 7.3 Décision métier

Les contrôles sur le triplet numéro de commande–société–succursale n’ont pas retourné de combinaison répétée dans le test exécuté. Le client a été retiré de la clé de commande et conservé comme attribut.

Une absence de résultat dans un `HAVING COUNT(*) > 1` est un résultat de contrôle, pas une erreur d’exécution.

### 7.4 Clé normalisée retenue

En-tête :

```sql
TRIM(TO_VARCHAR(nent_numcde))
|| '|'
|| TO_VARCHAR(TRY_TO_NUMBER(nent_soc))
|| '|'
|| TO_VARCHAR(TRY_TO_NUMBER(nent_succ)) AS PK_V2
```

LLF :

```sql
TRIM(TO_VARCHAR(l.NLLF_NUMCDE))
|| '|'
|| TO_VARCHAR(TRY_TO_NUMBER(l.NLLF_SOC))
|| '|'
|| TO_VARCHAR(TRY_TO_NUMBER(l.NLLF_SUCC)) AS PK_V2
```

La structure devient `NumeroCommande|Societe|SuccursaleCommande`. Les séparateurs rendent les frontières explicites. Le numéro de commande reste textuel ; seuls société et succursale sont normalisés numériquement conformément au test de rapprochement retenu.

`TRY_TO_NUMBER` peut renvoyer NULL si une conversion échoue. Le fait que le composant brut ne soit pas NULL ne garantit pas la validité de la PK résultante. Ne pas remplacer automatiquement une conversion invalide par zéro. [T4]

### 7.5 Ne pas confondre les deux succursales

`NLLF_SUCC` identifie la succursale de **commande** et entre dans `PK_V2`.

`NLLF_SUCCFAC` identifie la succursale de **facturation** et entre dans `InvoiceKey_V2`.

Les intervertir produit des clés syntaxiquement plausibles mais des rapprochements métier incorrects.

---

## 8. Correction des extractions et validation des PK

### 8.1 Historique des commandes

L’extraction initiale limitait `nent_datecde >= '2025-01-01'`. La borne inférieure a été retirée pour permettre de retrouver des commandes plus anciennes liées à des écritures récentes.

Le retrait de cette borne, isolé dans les comparaisons montrées, n’a récupéré qu’un faible nombre de clés : 291 217 non retrouvées devenaient 291 208 à cette étape. L’historique n’était donc pas l’unique problème. [S1]

### 8.2 Filtre client résiduel

Même après retrait du client de la PK, la requête gardait :

```sql
CAST(nent_numcde AS STRING)
|| CAST(nent_numcli AS STRING)
|| CAST(nent_soc AS STRING)
|| CAST(nent_succ AS STRING) <> ''
```

Cette condition dépendait encore du client. Elle a été remplacée par des conditions sur numéro de commande, société et succursale. La version suivante a conservé `nent_natop <> 'DEV'` et une limite haute de date. Une variante incluant `nent_datecde IS NULL` a été utilisée pour le diagnostic.

Il faut distinguer **absence de borne inférieure** et **absence de tout filtre** : les devis et certains cas invalides restaient exclus. `nent_natop <> 'DEV'` exclut aussi les valeurs NULL de ce champ dans la logique SQL habituelle ; ce cas doit être documenté si important.

### 8.3 Contrôle indépendant par composants

Le fichier `Untitled 31_2026-11-12-1133.csv`, relu pour ce dossier, contient :

| Contrôle global Snowflake | Résultat |
|---|---:|
| TOTAL_LLF_KEYS | 380 551 |
| MATCHED_KEYS | 380 549 |
| MISSING_KEYS | 2 |

La requête comparait les trois composants séparément, sur les sources brutes. Elle ne démontrait pas que toutes ces commandes étaient Mine, ni que toutes appartenaient au périmètre exact de l’extraction LLF Power BI. [S3]

### 8.4 Résultat final du rapprochement V3

Les captures finales du contrôle ont montré :

| Indicateur | Résultat |
|---|---:|
| Clés de commande retrouvées | 330 066 |
| Clés non retrouvées | 21 |
| Total de la population de contrôle | 330 087 |
| Taux calculé | Environ 99,9936 % |

Ce sont des **clés distinctes de commande**, pas des factures, des lignes LLF, ni un pourcentage de CA. [S1, captures de contrôle]

### 8.5 NULL n’est pas un doublon

La vérification Snowflake a d’abord affiché 387 788 lignes et 387 787 clés distinctes. Un premier commentaire a interprété l’écart comme un doublon ; la requête de recherche n’en a retrouvé aucun.

Le contrôle correct a ensuite distingué les NULL :

| Champ du CSV relu | Valeur |
|---|---:|
| TOTAL_ROWS | 387 788 |
| PK_NULL | 1 |
| DISTINCT_PK | 387 787 |
| REAL_DUPLICATES | 0 |

`COUNT(DISTINCT PK_V2)` exclut les NULL. Le résultat établit l’unicité des clés non NULL dans cette extraction, pas la présence d’un doublon. [S3 ; T5]

La ligne à PK vide a été filtrée dans Power Query, puis l’utilisateur a confirmé que la relation commande–bridge était acceptée en plusieurs-vers-un, équivalente à un-vers-plusieurs dans le sens en-tête → bridge.

### 8.6 Comptages DAX contradictoires

Des cartes ont affiché un nombre de valeurs distinctes supérieur au nombre de lignes supposé de la même table, puis un « nombre de doublons » négatif. Ces résultats sont conservés comme des **diagnostics non validés**.

La cause précise n’a pas été démontrée par un audit du modèle chargé. Ne pas enseigner à partir de ces cartes que les tables étendues rendent normalement possible un distinct count supérieur au nombre de lignes de la même population. Les noms de tables remplacées, contextes, versions et expressions réellement évaluées auraient dû être inspectés. La vérification SQL a fourni le contrôle exploitable.

---

## 9. Construction et validation d’InvoiceKey_V2

### 9.1 Différence avec PK_V2

`PK_V2` relie les commandes à leurs en-têtes. `InvoiceKey_V2` relie les factures opérationnelles aux écritures comptables. Modifier une clé n’apporte pas automatiquement une amélioration sur l’autre rapprochement.

### 9.2 Formats initiaux

| Source | InvoiceKey V1 documentée |
|---|---|
| LLF | Société \| Société-SuccursaleFacturation \| NuméroFacture \| Société-Client |
| FAC | Société numérique \| Succursale numérique \| NuméroFacture \| NuméroClient brut |
| CA détaillé | Code société \| Code agence financier \| Numéro de pièce \| Code client financier |

Le code client financier inclut déjà une contextualisation société ; il n’est pas interchangeable avec le numéro client Irium brut. Les formats V1 n’étaient donc pas uniformes.

### 9.3 Format V2

```text
Societe | Societe-SuccursaleFacturation | NumeroFacture
```

Exemple de structure : `32|32-01|40075644`.

Dans LLF, le composant agence est construit avec `NLLF_SOC` et `NLLF_SUCCFAC`. Dans les écritures comptables, `feca_agc_code` fournit déjà le code de type `32-01` dans les exemples retournés.

Les expressions exactes sont dans les fichiers SQL 02 à 05. Elles conservent les règles de format communiquées ; elles ne prouvent pas que toutes les valeurs sources sont normalisées. Une succursale `1` côté FAC et `01` côté LLF reste un cas à surveiller.

### 9.4 Contrôles de collisions

Le contrôle LLF n’a pas retourné de combinaison associée à plusieurs clients renseignés. Le contrôle SQL Server a retourné deux combinaisons :

| Société | Succursale | Pièce | Clients | Écritures | CA net EUR |
|---|---|---|---:|---:|---:|
| 32 | 32-01 | FAEM02/26 | 6 | 16 | 0,00 |
| 27 | 27-01 | Réconciliation Fret | 2 | 9 | 10 059,05 |

Un test de recherche dans LLF n’a pas retourné ces références avec les conditions utilisées. Ce n’est pas une preuve générale d’absence si les formats de succursale diffèrent. Un CA net nul ne supprime pas le risque de compensations ou de rapprochement erroné. [S1]

### 9.5 Résultat de la comparaison V1/V2

Les tests financiers V1, V2 et V2 isolé ont donné des montants identiques sur les périodes comparées dans les exports intermédiaires. La suppression du client de la clé facture n’a donc **pas démontré de gain de CA rapproché dans ces tests**.

Le gain important ultérieur provient du rapprochement des **commandes** et de leur date, pas d’un gain financier V1→V2 établi.

### 9.6 Limites de validité

Une clé V2 non vide telle que `societe|agence|` peut rester incomplète. Les filtres `NOT ISBLANK` et `<> ""` sur la chaîne composée ne valident pas chaque composant.

Le numéro de pièce comptable n’est pas toujours une facture opérationnelle au sens métier. Une réutilisation du même numéro selon exercice, journal ou type de document doit être contrôlée si elle existe dans les sources. La validation réalisée est circonscrite aux données et tests montrés.

---

## 10. Bridges V1, V2, V3, V4 et dimension facture

### 10.1 Pourquoi une bridge

LLF contient plusieurs lignes par couple commande–facture. Une projection distincte des deux clés permet d’obtenir les associations sans répéter chaque pièce.

Les variantes successives ont été :

```text
V1 : PK historique + InvoiceKey avec client
V2 : PK historique + InvoiceKey_V2
V3 : PK_V2 + InvoiceKey_V2
V4 : V3 + OrderDate via LOOKUPVALUE
```

La bridge V3 a permis de vérifier les 330 066 commandes retrouvées et les 21 exceptions. Les expressions DAX sont archivées dans `dax/02_tables_diagnostic_archive.dax`.

### 10.2 Distinct d’un couple ≠ facture unique

Une bridge peut être unique sur `(PK_Commande, InvoiceKey)` et contenir plusieurs lignes pour une même facture. C’est normal lorsqu’une facture concerne plusieurs commandes.

Une relation bridge→LLF en `1:*` sur une clé de couple est différente d’une relation sur la seule facture. Une relation sur `InvoiceKey` seule peut être `*:*` dans ce contexte.

### 10.3 Table calculée versus mesure

Les expressions `SELECTCOLUMNS`, `EXCEPT`, `ADDCOLUMNS` ou `NATURALINNERJOIN` peuvent retourner une table. Un résultat tabulaire doit être créé comme **Nouvelle table**, pas Nouvelle mesure. Pour une carte, une mesure doit retourner un scalaire, par exemple `COUNTROWS(...)`.

Plusieurs erreurs « multiple values / multiple columns cannot be converted to a scalar » ont été rencontrées pendant ce diagnostic.

### 10.4 V4 ne devient pas automatiquement une requête Power Query

`BridgeCommandeFacture_V4` était une table calculée DAX. La préparation Power Query ne peut pas la considérer comme une requête source existante. Le flux final a donc reconstruit la bridge à partir de `Neg_llf_complete` et `OrderHeader History`, qui sont des requêtes Power Query.

### 10.5 DimFacture_V2

La dimension a été créée à partir d’un `UNION` distinct des clés du CA détaillé, de FAC et de LLF. L’ancien CA agrégé possède un historique commençant avant celui du détail ; si on le relie à cette dimension, il faut contrôler les clés de sa période supplémentaire.

Cette dimension a servi au modèle intermédiaire. Elle ne doit pas être reconnectée automatiquement à `FactSalesAllocation` pour la page finale, dont l’attribution a déjà été préparée.

---

## 11. Relations intermédiaires et rôle du calendrier

L’architecture intermédiaire validée par l’utilisateur comportait notamment :

```text
OrderHeader[PK_V2] (1) ──> (*) BridgeCommandeFacture_V3[PK_Commande]
DimFacture_V2[InvoiceKey_V2] (1) ──> (*) BridgeCommandeFacture_V3[InvoiceKey_V2]
DimFacture_V2[InvoiceKey_V2] (1) ──> (*) Global CA Detailled[InvoiceKey_V2]
```

Avec filtrage simple, le chemin commande→bridge ne remonte pas automatiquement vers `DimFacture_V2`. C’est pour cela que les essais DAX transféraient explicitement les listes de factures.

Le passage d’une liaison bidirectionnelle à une liaison simple a fait apparaître un total toutes périodes répété chaque mois dans un ancien visuel : le calendrier ne filtrait plus le CA par le chemin indirect précédent, et la relation comptable directe était inactive à cette étape.

Ce comportement a permis d’identifier la nécessité d’un filtre explicite sur la date comptable, puis d’une relation active dédiée dans le modèle final. Il ne justifie pas de réactiver un chemin indirect par la date de commande.

**Important :** `REMOVEFILTERS()` efface un contexte de filtre ordinaire ; il ne supprime pas physiquement les relations et ne neutralise pas la sécurité. Une dimension contenant uniquement des clients MI ne transforme pas, par sa seule présence, chaque jointure en filtre physique des lignes sources. [T2, T6]

Le catalogue actuel complet des relations du rapport n’a pas été exporté après toutes les modifications. Cette section décrit les relations de travail confirmées, pas la totalité du modèle publié.

---

## 12. Diagnostic des factures multicommandes

Une première version avait identifié 29 factures multicommandes. Après évolution des clés et de la population, V3 en a identifié 11. Ces chiffres appartiennent à des versions distinctes : ne pas les présenter comme une suppression prouvée de 18 anomalies sur une population constante.

Pour V3, deux contrôles 2026 ont donné 0,00 € :

- somme nette du CA associé aux factures multicommandes ;
- somme de `ABS([CA euro])` au grain des lignes de la table comptable importée.

Ce second contrôle rend moins probable une compensation entre lignes importées. Il ne prouve pas l’absence de mouvements bruts internes qui auraient déjà été compensés en amont dans une agrégation. Il ne garantit pas non plus le comportement des autres années ou des actualisations futures.

### Décision retenue

La version finale **n’alloue pas arbitrairement le montant d’une facture multicommande**. Elle filtre `OrderCount = 1` dans une table d’attribution dédiée. Les autres factures restent dans la table comptable de départ, grâce à la jointure externe gauche, et apparaissent non attribuées si elles n’ont pas de correspondance exploitable.

Ne pas choisir `MIN(PK)` ou `MAX(DateCommande)` pour forcer une commande. Ne pas diviser par le nombre de commandes sans règle métier approuvée. Une future répartition devrait utiliser une base facturée documentée et conserver les coefficients, les montants et les contrôles de somme.

---

## 13. Essais DAX, résultats et limite de performance

### 13.1 Logique testée

Les mesures dynamiques sélectionnaient d’abord les commandes d’un mois, puis les factures associées via la bridge, puis les écritures comptables du mois à l’aide de `TREATAS`.

Le total multi-mois était calculé avec :

```dax
SUMX (
    VALUES ( 'Date'[Year Month] ),
    [Sales Current Month V3 Base]
)
```

Cette construction avait remplacé un total qui reprenait seulement le premier mois avec `MIN(Date[Date])`.

### 13.2 Pourquoi les anciennes valeurs étaient provisoires

Les premières mesures utilisaient encore d’anciennes clés, des contextes différents et des suppressions de filtres non homogènes entre Current, Last et 2+ Months. Elles ne constituaient pas une définition finale commune du périmètre.

Certaines cartes ont affiché tout le CA rapproché à la place du Current Month. Des tests sur octobre ont ensuite isolé :

| Contrôle octobre 2026 | Valeur observée |
|---|---:|
| Commandes créées pendant le mois | 7 685 |
| Factures associées, toutes dates comptables | 6 825 |
| CA comptabilisé en octobre, commandes d’octobre | 8 416 346,36 € |

Les deux comptages opérationnels ne sont pas automatiquement des comptages Mine/PARTS : le filtre comptable final détermine le périmètre du montant CA. [S1]

### 13.3 Blocage d’affichage

Le test d’un mois fixe a abouti, mais les mesures généralisées ont produit des chargements prolongés. Ajouter `OrderDate` dans une V4 calculée n’a pas résolu le blocage observé.

La cause précise de performance n’a pas été mesurée avec une trace moteur ou Performance Analyzer dans les pièces fournies. Il faut donc écrire « lenteur observée dans cette implémentation », et non « TREATAS est intrinsèquement lent » ou « REMOVEFILTERS empêche les autres filtres de fonctionner ».

### 13.4 Règles à ne pas réintroduire

Ne pas rétablir les anciennes mesures V3/V4 comme dépendances du dashboard final. Ne pas sommer une mesure de rapprochement toutes périodes sur chaque mois. Ne pas comparer une carte 2026 à une carte sans filtre de dates.

Le test comptable V3 toutes périodes donnait 314 144 282,03 €, et le test limité à 2026 donnait 172 920 123,99 € au relevé concerné. Ces valeurs ne sont pas contradictoires en elles-mêmes.

---

## 14. Décision de pré-calculer dans Power Query

Le choix réalisé a été de préparer les associations et la cohorte **à l’actualisation**, puis de faire exécuter aux visuels de simples agrégations.

La logique n’est plus : « retrouver toutes les commandes et factures à chaque clic ». Elle devient : « filtrer les lignes d’une table comptable déjà enrichie ».

Power Query a été retenu dans le rapport pour rapprocher Snowflake et SQL Server sans mettre en place immédiatement un nouvel entrepôt. Une préparation SQL/ETL commune a été évoquée comme évolution possible, mais **n’a pas été démontrée déployée**.

Cette décision ne garantit pas une durée d’actualisation faible : les sources, le query folding, les accès réseau et les volumes doivent être suivis. Aucun benchmark chiffré de rafraîchissement n’a été fourni.

### Ordre de dépendance final

```text
Neg_llf_complete + OrderHeader History
  → PQ_BridgeCommandeFacture
  → PQ_SingleOrderInvoices

Global CA Detailled
  → PQ_AccountingSales

PQ_AccountingSales + PQ_SingleOrderInvoices
  → FactSalesAllocation
```

Ce graphe ne doit pas contenir de boucle.

---

## 15. Étape 1 — Créer PQ_BridgeCommandeFacture

### 15.1 Opérations réalisées

Dans Power Query : référence de `Neg_llf_complete`, conservation de `PK_V2` et `INVOICEKEY_V2`, suppression des doublons de couple, puis fusion gauche avec `OrderHeader History` sur `PK_V2`.

Seule la colonne `DATECOMMANDE` de l’en-tête est développée, puis renommée `Order Date`.

Le comptage des commandes distinctes par facture est calculé dans la même requête et rejoint à la bridge.

### 15.2 Code confirmé

Le fichier `powerquery/01_PQ_BridgeCommandeFacture.pq` reproduit le code fourni et suivi d’une confirmation « Done » :

```powerquery
let
    Source = Neg_llf_complete,
    #"Removed Other Columns" =
        Table.SelectColumns(Source, {"PK_V2", "INVOICEKEY_V2"}),
    #"Removed Duplicates" = Table.Distinct(#"Removed Other Columns"),
    #"Merged Queries" = Table.NestedJoin(
        #"Removed Duplicates", {"PK_V2"},
        #"OrderHeader History", {"PK_V2"},
        "OrderHeader History", JoinKind.LeftOuter
    ),
    #"Expanded OrderHeader History" = Table.ExpandTableColumn(
        #"Merged Queries", "OrderHeader History", {"DATECOMMANDE"},
        {"OrderHeader History.DATECOMMANDE"}
    ),
    #"Renamed Columns" = Table.RenameColumns(
        #"Expanded OrderHeader History",
        {{"OrderHeader History.DATECOMMANDE", "Order Date"}}
    ),
    #"Distinct Order Invoice" = Table.Distinct(
        #"Renamed Columns", {"PK_V2", "INVOICEKEY_V2"}
    ),
    #"Invoice Order Counts" = Table.Group(
        #"Distinct Order Invoice", {"INVOICEKEY_V2"},
        {{"OrderCount", each List.Count(List.Distinct([PK_V2])), Int64.Type}}
    ),
    #"Merged Order Counts" = Table.NestedJoin(
        #"Distinct Order Invoice", {"INVOICEKEY_V2"},
        #"Invoice Order Counts", {"INVOICEKEY_V2"},
        "InvoiceCounts", JoinKind.LeftOuter
    ),
    #"Expanded Order Counts" = Table.ExpandTableColumn(
        #"Merged Order Counts", "InvoiceCounts", {"OrderCount"}, {"OrderCount"}
    )
in
    #"Expanded Order Counts"
```

### 15.3 Pourquoi le comptage a été intégré

Une méthode précédente proposait de créer `PQ_InvoiceOrderCount` comme référence de `PQ_BridgeCommandeFacture`, puis de fusionner ce résultat dans sa requête parente. Si la dépendance est construite ainsi, elle devient :

```text
PQ_BridgeCommandeFacture → PQ_InvoiceOrderCount → PQ_BridgeCommandeFacture
```

C’est un cycle de dépendance à éviter. Les captures montraient un refus de fusion et une absence de prévisualisation ; elles ne fournissaient pas un message confirmant explicitement cette cause. Le code intégré a supprimé la dépendance inverse et a été confirmé fonctionnel. Il ne s’agissait donc pas simplement de « forcer » un Merge interdit par l’interface.

### 15.4 Préconditions et points de contrôle

`OrderHeader History[PK_V2]` doit être unique sur les lignes retenues. Une fusion qui multiplie les lignes avant la déduplication indique un problème à investiguer.

Le `Table.Distinct` après développement de la date conserve un seul couple, mais ne garantit pas de sélectionner la bonne date si un même couple possède plusieurs dates contradictoires. La documentation officielle précise que la ligne conservée par déduplication n’est pas nécessairement déterministe. Ne pas utiliser cette étape pour dissimuler un conflit d’en-têtes. [T7]

La formule de `OrderCount` compte les valeurs distinctes de PK telles qu’elles existent. Elle ne remplace pas un contrôle de validité des composants ; une PK nulle/incomplète doit être traitée explicitement avant de considérer une facture comme attribuable.

---

## 16. Étape 2 — Créer PQ_AccountingSales

### 16.1 Source et colonnes

Créer une référence de `Global CA Detailled` dans Power Query. Conserver :

```text
InvoiceKey_V2
Date ecritures
CA euro
```

Conserver les montants négatifs. Ne pas filtrer les dates/commandes à ce stade autrement que selon le périmètre source retenu.

### 16.2 Regroupement avancé

Dans **Group By → Advanced** :

| Paramètre | Valeur |
|---|---|
| Première clé | InvoiceKey_V2 |
| Deuxième clé | Date ecritures |
| Nouvelle colonne | AccountingCA_EUR |
| Opération | Sum |
| Colonne | CA euro |

La date doit rester au grain jour comptable. Ne pas regrouper uniquement par facture, car une facture peut avoir des écritures sur plusieurs mois. [S1 ; T8]

### 16.3 Traduction M documentaire

```powerquery
let
    Source = #"Global CA Detailled",
    Selected = Table.SelectColumns(
        Source, {"InvoiceKey_V2", "Date ecritures", "CA euro"}
    ),
    Typed = Table.TransformColumnTypes(Selected,
        {{"InvoiceKey_V2", type text},
         {"Date ecritures", type date},
         {"CA euro", type number}}),
    Grouped = Table.Group(
        Typed, {"InvoiceKey_V2", "Date ecritures"},
        {{"AccountingCA_EUR", each List.Sum([CA euro]), type number}}
    )
in
    Grouped
```

C’est une reconstitution des étapes UI confirmées, pas un export brut de l’éditeur final. Le fichier associé est `powerquery/02_PQ_AccountingSales_reconstitution.pq`.

### 16.4 Conservation des montants

Le regroupement doit préserver la somme de `CA euro`. La conservation à ce niveau ne démontre pas que toutes les jointures SQL d’origine sont sans duplication : ce contrôle amont reste distinct.

Ne pas arrondir chaque ligne au centime avant agrégation. Les exports contiennent davantage de décimales et certaines cellules présentent les artefacts habituels d’une représentation flottante. L’affichage au centime n’est pas une modification du montant stocké.

---

## 17. Étape 3 — Créer PQ_SingleOrderInvoices

Créer une référence de `PQ_BridgeCommandeFacture`, filtrer `OrderCount = 1` et conserver :

```text
PK_V2
INVOICEKEY_V2
Order Date
```

Traduction documentaire :

```powerquery
let
    Source = PQ_BridgeCommandeFacture,
    Single = Table.SelectRows(Source, each [OrderCount] = 1),
    Selected = Table.SelectColumns(
        Single, {"PK_V2", "INVOICEKEY_V2", "Order Date"}
    )
in
    Selected
```

**Invariant obligatoire :** au plus une ligne par `INVOICEKEY_V2`. Le filtre `OrderCount = 1` ne dispense pas de contrôler cet invariant sur le résultat chargé.

Une date de commande absente n’est pas inventée. Une facture avec une commande unique mais sans date restera non classifiable lors du calcul des cohortes.

La table n’a pas vocation à exclure les factures multicommandes du CA total : elle les exclut seulement de la **correspondance d’attribution directe**.

---

## 18. Étape 4 — Créer FactSalesAllocation

### 18.1 Sens de la jointure

Créer une référence de `PQ_AccountingSales`, renommer `FactSalesAllocation`, puis effectuer la fusion :

| Élément | Valeur |
|---|---|
| Table gauche | PQ_AccountingSales |
| Clé gauche | InvoiceKey_V2 |
| Table droite | PQ_SingleOrderInvoices |
| Clé droite | INVOICEKEY_V2 |
| Jointure | Left Outer |
| Colonnes développées | PK_V2, Order Date |

La casse des noms est importante dans le code M. Les captures LLF montrent `INVOICEKEY_V2`, tandis que l’export comptable porte `InvoiceKey_V2`. Ce sont des noms distincts à utiliser explicitement, pas des valeurs à transformer.

### 18.2 Colonnes confirmées dans Exports N.xlsx

| Colonne | Usage |
|---|---|
| InvoiceKey_V2 | Identifiant de rapprochement facture. |
| Date ecritures | Date de reconnaissance comptable retenue. |
| AccountingCA_EUR | CA agrégé de la facture à cette date. |
| PQ_SingleOrderInvoices.PK_V2 | Commande attribuée si disponible. |
| PQ_SingleOrderInvoices.Order Date | Date de la commande attribuée si disponible. |

`SalesCohort` est ajoutée ensuite. L’export de contrôle précède cette colonne.

### 18.3 Pourquoi Left Outer

La table comptable pilote la population. Toute écriture présente dans la préparation comptable doit subsister, même si aucun numéro de commande exploitable n’est retrouvé.

Une jointure interne aurait supprimé les montants non rapprochés et aurait empêché d’expliquer le résiduel. Une jointure directe à la bridge multicommande aurait pu multiplier les montants. [S1 ; T9]

### 18.4 Attribution, pas duplication

`AccountingCA_EUR` n’est pas recopié sur toutes les lignes LLF. Une seule attribution est possible à droite, ou aucune. Le grain de la table finale reste facture × date comptable.

Il n’a pas été nécessaire de créer une nouvelle colonne `AllocatedCA_EUR` pour la version réalisée : les mesures finales somment `AccountingCA_EUR` selon `SalesCohort`. Le nom `AllocatedCA_EUR` évoqué au début du projet désignait une architecture envisagée, pas une colonne finale attestée.

---

## 19. Étape 5 — Calculer SalesCohort

### 19.1 Formule historique utilisée

Dans **Ajouter une colonne → Colonne personnalisée**, nommer la colonne `SalesCohort` et utiliser :

```powerquery
let
    AccountingDate = try Date.From([Date ecritures]) otherwise null,
    OrderDate = try Date.From([PQ_SingleOrderInvoices.Order Date]) otherwise null,
    MonthDifference =
        if AccountingDate = null or OrderDate = null
        then null
        else
            (Date.Year(AccountingDate) - Date.Year(OrderDate)) * 12
            + Date.Month(AccountingDate) - Date.Month(OrderDate)
in
    if OrderDate = null then "Unallocated"
    else if MonthDifference < 0 then "Future Order"
    else if MonthDifference = 0 then "Current Month"
    else if MonthDifference = 1 then "Last Month"
    else "2+ Months"
```

Cette formule reproduit le code fourni et confirmé utilisé. La différence en mois est calculée par année et mois, et non par un nombre de jours divisé par 30.

### 19.2 Précondition non couverte par cette formule

La formule ne traite pas explicitement une **date comptable absente ou invalide alors que la date de commande existe**. Il ne faut pas en déduire une classification correcte pour ce cas. Une branche de garde explicite ou un contrôle bloquant est une amélioration de maintenance à définir, pas une correction à appliquer silencieusement au modèle existant.

Les `Date ecritures` de l’export analysé sont exploitables ; la reconstruction des catégories y retrouve les totaux affichés. Les conversions d’Order Date en erreur seraient transformées en null par le `try`, donc absorbées dans `Unallocated` : conserver un contrôle séparé des erreurs source permettrait de les distinguer des vraies absences de date.

### 19.3 Pourquoi conserver Future Order

Le tableau final présente 4 320,95 € en février et 415,33 € en mai, soit 4 736,28 € sur la période de validation. Ces montants ne sont pas déplacés artificiellement vers une autre cohorte. Ils restent visibles et détaillables pour vérifier dates et rapprochement. [S2, S6]

### 19.4 Sous-catégories Unallocated non encore déployées

La version finale ne dispose pas d’une raison fine confirmée pour chaque ligne non attribuée. Une évolution pourrait ajouter `AllocationStatus` distinguant absence de bridge, multicommande, commande introuvable, date absente et clé invalide. Cela nécessite une jointure de contrôle supplémentaire vers les comptes de facture ; ce n’est pas une colonne existante attestée.

---

## 20. Étape 6 — Charger la table et relier Date

Dans Power Query, activer le chargement de `FactSalesAllocation`, puis **Fermer et appliquer**.

Dans le modèle :

| Paramètre | Valeur finale confirmée |
|---|---|
| Côté 1 | Date[Date] |
| Côté plusieurs | FactSalesAllocation[Date ecritures] |
| Cardinalité | 1:* |
| Filtrage croisé | Simple, de Date vers la table de faits |
| Relation active | Oui |

`Date[Date]` doit être unique et couvrir toutes les dates comptables à afficher. Une date comptable hors du calendrier ne sera pas représentée correctement par les mois de ce calendrier.

Le calendrier a été décrit comme généré avec Bravo. Son expression exacte, sa couverture finale et ses colonnes de tri ne sont pas fournies ici. Pour les visuels, `Date[Year Month]` est le champ utilisé ; il doit être trié chronologiquement, avec l’année incluse.

**Aucune liaison directe supplémentaire n’a été demandée entre FactSalesAllocation et la bridge, LLF, le CA détaillé ou OrderHeader pour cette page.** Les liens de préparation Power Query ne sont pas des relations de modèle.

La sécurité de la nouvelle table doit néanmoins être vérifiée dans le rapport publié : être reliée uniquement à `Date` ne garantit pas qu’un ancien rôle RLS basé sur une dimension client s’y propage. L’absence de filtre client dans l’interface n’est jamais une autorisation de contourner les droits. [T2]

---

## 21. Étape 7 — Mesures DAX finales

Créer chaque mesure séparément via **Nouvelle mesure**. La table d’accueil peut être `FactSalesAllocation` pour faciliter la lecture du modèle ; cette table d’accueil ne définit pas à elle seule la source d’une mesure.

```dax
CA Comptable EUR =
SUM ( FactSalesAllocation[AccountingCA_EUR] )
```

```dax
CA Current Month =
CALCULATE (
    [CA Comptable EUR],
    FactSalesAllocation[SalesCohort] = "Current Month"
)
```

```dax
CA Last Month =
CALCULATE (
    [CA Comptable EUR],
    FactSalesAllocation[SalesCohort] = "Last Month"
)
```

```dax
CA 2+ Months =
CALCULATE (
    [CA Comptable EUR],
    FactSalesAllocation[SalesCohort] = "2+ Months"
)
```

```dax
CA Unallocated =
CALCULATE (
    [CA Comptable EUR],
    FactSalesAllocation[SalesCohort] = "Unallocated"
)
```

```dax
CA Future Order =
CALCULATE (
    [CA Comptable EUR],
    FactSalesAllocation[SalesCohort] = "Future Order"
)
```

```dax
CA Reconciliation Difference =
COALESCE ( [CA Comptable EUR], 0 )
    - COALESCE ( [CA Current Month], 0 )
    - COALESCE ( [CA Last Month], 0 )
    - COALESCE ( [CA 2+ Months], 0 )
    - COALESCE ( [CA Unallocated], 0 )
    - COALESCE ( [CA Future Order], 0 )
```

### 21.1 Ce qui a disparu du calcul courant

Les KPI de CA n’ont plus besoin de parcourir les en-têtes, retrouver les factures avec `TREATAS`, puis réitérer sur les mois. Le total mensuel et le total multi-mois proviennent de la somme des lignes de faits filtrées par le calendrier.

### 21.2 Contexte de cohorte et contrôle de réconciliation

La mesure de réconciliation ci-dessus a été validée dans un tableau **sans filtre restreignant SalesCohort**. Les mesures nommées de cohorte appliquent leur propre filtre de catégorie. Si un slicer filtre directement `SalesCohort`, le total de base et les cinq mesures peuvent ne plus avoir le même contexte de catégorie.

Pour la page finale, limiter la sélection de cohorte au détail, comme demandé dans le contrat UI, ou concevoir explicitement une mesure de contrôle hors filtre de cohorte. Ne pas interpréter un écart apparu uniquement sous ce slicer comme une preuve de duplication des données.

### 21.3 KPI dérivés

`Sales from Older Orders = CA Last Month + CA 2+ Months`.

`Same-Month Sales Realization = CA Current Month / Order Intake EUR`, sous réserve de comparabilité des périmètres, devises et bases fiscales.

`Part Current Month dans le CA = CA Current Month / CA Comptable EUR`.

Ces deux ratios ont des dénominateurs différents. Le premier n’est pas un taux opérationnel de pièces livrées ou de commandes intégralement satisfaites.

Les définitions complémentaires sont fournies séparément dans `dax/04_kpi_derives_proposes.dax`, marquées comme propositions documentaires.

---

## 22. Étape 8 — Résultats vérifiés et réconciliation

### 22.1 Vérification du grain sur Exports N.xlsx

Le classeur contient les feuilles `PQ_AccountingSales` et `FactSalesAllocation`. Une lecture indépendante des cellules a produit :

| Contrôle | PQ_AccountingSales | FactSalesAllocation |
|---|---:|---:|
| Lignes de données | 60 115 | 60 115 |
| Couples facture–date distincts | 60 115 | 60 115 |
| Lignes en doublon sur ce grain | 0 | 0 |
| Montants vides, mêmes clés dans les deux feuilles | 9 | 9 |
| Total CA, arrondi au centime | 468 038 287,09 € | 468 038 287,09 € |

Le rapprochement des deux feuilles **par facture et date** n’a trouvé ni clé manquante ni différence de montant supérieure à 0,000001 €. Neuf lignes ont un montant vide dans chacune des deux feuilles, sur les mêmes clés ; ce statut vide est préservé et contrôlé séparément. Ces blancs sont exclus des sommes, pas qualifiés de ventes réellement nulles. Ce contrôle est plus précis que la seule égalité du total global. [S2]

| Attribution dans l’export | Lignes |
|---|---:|
| Avec PK et date de commande renseignées | 51 361 |
| Sans PK/date développées | 8 754 |

Le CA avec attribution présente dans l’export totalise **314 328 467,13 €**, toutes dates de cet export. Le reste totalise **153 709 819,96 €**. Il ne s’agit pas des seuls montants 2026.

### 22.2 Période de la capture de validation finale

Le sélecteur de la capture de réconciliation va du **1er janvier au 1er novembre 2026 inclus**. La ligne novembre est donc partielle ; ce n’est pas le mois complet ni une période allant au 11 novembre.

La reconstruction des catégories à partir de l’export retrouve, avant arrondi, les sommes correspondant à la capture :

| Mesure | Total affiché / arrondi au centime |
|---|---:|
| CA Comptable EUR | 216 366 493,75 € |
| CA Current Month | 72 629 036,03 € |
| CA Last Month | 41 902 663,05 € |
| CA 2+ Months | 54 590 529,70 € |
| CA Unallocated | 47 239 528,69 € |
| CA Future Order | 4 736,28 € |
| CA Reconciliation Difference | 0,00 € |

La somme des trois cohortes principales est **169 122 228,78 €** après affichage au centime. Les différences éventuelles d’un centime entre sommes de valeurs déjà arrondies et total calculé avant arrondi doivent être distinguées d’un défaut de jointure.

### 22.3 Cas de référence — octobre 2026

| Mesure | Valeur |
|---|---:|
| CA Comptable EUR | 20 100 153,90 € |
| CA Current Month | 8 416 346,36 € |
| CA Last Month | 4 817 567,64 € |
| CA 2+ Months | 6 047 941,69 € |
| CA Unallocated | 818 298,21 € |
| CA Future Order | 0,00 € |
| Réconciliation | 0,00 € |

Le résultat Current Month est le même que le test d’octobre qui avait permis de valider le parcours commande→facture→CA avant la généralisation Power Query.

Les parts affichées sont environ 41,87 %, 23,97 %, 30,09 % et 4,07 %. L’Order Intake apparaît ensuite à **124,49 M€** dans la capture du dashboard ; cette dernière valeur est arrondie et sa formule n’a pas été fournie. Il ne faut pas la transformer en 124 490 000,00 € exacts dans des tests de données.

### 22.4 Portée de la validation

La conservation du grain et la réconciliation des cinq catégories sont démontrées pour l’export et les captures examinés. Elles ne prouvent pas à elles seules :

- l’absence de collision métier de toutes les clés facture à l’avenir ;
- l’absence de duplication dans les jointures SQL avant l’export ;
- la pertinence de chaque date de commande ;
- le périmètre ou la conversion de l’Order Intake ;
- la sécurité RLS et le bon fonctionnement de l’application publiée.

Les fichiers `validation/verification_Exports_N.json` et `validation/reconciliation_mensuelle_export.csv` contiennent les résultats détaillés de la revérification. Le contrôle est reproductible avec `python validation/verify_exports.py "Exports N.xlsx" --out verification.json` ; le classeur original doit être fourni séparément. Ce script a été exécuté sur le fichier joint et son résultat est dans `validation/verification_reproductible.json`.

![Validation des cinq catégories, du 1er janvier au 1er novembre 2026](assets/02_reconciliation_2026.png)

---

## 23. Étape 9 — Détail des commandes et des factures

Le détail est accessible depuis la table de faits sans rétablir les chemins complexes du modèle de diagnostic.

### 23.1 Table de détail comptable

Afficher :

| Champ affiché | Champ source |
|---|---|
| Date comptable | FactSalesAllocation[Date ecritures] |
| Clé commande | FactSalesAllocation[PQ_SingleOrderInvoices.PK_V2] |
| Date commande | FactSalesAllocation[PQ_SingleOrderInvoices.Order Date] |
| Clé facture | FactSalesAllocation[InvoiceKey_V2] |
| Cohorte | FactSalesAllocation[SalesCohort] |
| CA comptable EUR | [CA Comptable EUR] |

Filtrer par mois comptable et par cohorte. `Unallocated` doit conserver les lignes où le champ commande est vide.

### 23.2 Table de synthèse par commande

Pour une ligne par commande et cohorte dans le contexte affiché, retirer facture et date comptable du regroupement, conserver PK, date de commande, cohorte et mesure de CA.

Une même commande peut apparaître dans plusieurs cohortes si l’utilisateur sélectionne plusieurs mois comptables. Ce n’est pas automatiquement un doublon : sa catégorie dépend de chaque date comptable.

### 23.3 Identifiants lisibles

`PK_V2` est une clé composée. L’appeler « Numéro de commande » sans précision serait trompeur. Le numéro lisible peut être récupéré dans un champ fiable ou extrait du premier composant après validation du format. Conserver la clé complète pour audit.

Ne pas convertir les identifiants en nombres, ni sommer le montant initial de commande à chaque facture. Le CA du détail est un montant attribué, pas le montant initial de la commande.

### 23.4 Future Order et Unallocated

Pour `Future Order`, afficher les deux dates côte à côte. Pour `Unallocated`, afficher au minimum clé facture, date comptable et montant ; une ligne non attribuée ne doit pas disparaître d’un export faute de numéro de commande.

---

## 24. Order Intake : ce qui est connu et ce qui manque

### 24.1 Besoin métier

L’Order Intake est le montant des **commandes créées pendant chaque mois**, y compris les commandes non encore facturées. Il ne peut pas être déduit uniquement de `FactSalesAllocation`, qui commence par les écritures comptables.

### 24.2 Éléments disponibles

L’utilisateur a indiqué que `OrderLineItems` contient `Montant_EU_lines` ; une capture antérieure affiche `MontantEU_Lines`. La mesure finale `[Order Intake EUR]` est visible sous `FactSalesAllocation` dans le volet des champs, puis affiche 124,49 M€ pour octobre dans le dashboard.

Le SQL fourni pour les lignes expose `nlig_pxvteht AS AmountNet`, des quantités et plusieurs statuts, mais pas l’expression complète de ce montant EUR.

### 24.3 Éléments non fournis

La documentation ne dispose pas de :

- la formule DAX exacte de `[Order Intake EUR]` ;
- la formule et le nom final exact du montant de ligne EUR ;
- la règle de taux de change et sa date d’application ;
- la confirmation HT/TTC au niveau de la mesure finale ;
- la liste exacte des filtres de la nouvelle requête `OrderLineItems History` ;
- le chemin final de filtrage Mine / PARTS / hors INTERCO pour les commandes ;
- la politique d’annulation, d’avenant ou de modification rétrospective des montants de commande.

Codex doit récupérer ces définitions dans le modèle accessible, ou laisser une section « à compléter » explicite. Ne pas substituer une formule plausible du type prix × quantité × taux sans preuve.

### 24.4 Liaison temporelle

Le mois appliqué à l’Order Intake doit porter sur la création de commande, et non sur la date comptable. Une même dimension de reporting peut filtrer deux tables indépendantes selon leurs dates propres, mais il faut éviter un chemin qui impose simultanément la date de commande à la table de ventes déjà cohortée.

Le filtre client a été retiré de la spécification UI finale. **Cela ne signifie pas que les commandes de toutes les divisions doivent être incluses.** Le périmètre métier doit être maintenu indépendamment de l’absence de sélecteur client.

---

## 25. Intégration Mining360 et contrat de données

### 25.1 Emplacement et objectif visuel

```text
Mining360 → Business Overview → Parts Orders & Sales Fulfillment
```

Titre : `Parts Orders & Sales Fulfillment`  
Sous-titre : `From Parts Orders to Sales — Monthly Performance`

La maquette retenue est un dashboard clair avec bandeau bleu marine, grandes cartes, ventilation horizontale et graphique mensuel. **Ne pas reproduire le filtre Customer / Site présent dans l’image de référence.** La décision finale est : filtre temporel et sélection des cohortes pour le détail uniquement.

![Maquette de référence — valeurs illustratives, filtre client à retirer](assets/01_maquette_reference.png)

### 25.2 Cartes principales

`New Parts Orders This Month` utilise `[Order Intake EUR]`.

`What We Sold This Month` utilise `[CA Comptable EUR]`, y compris les catégories non attribuées et Future Order.

`Where This Month’s Sales Came From` ventile les cinq catégories. Ne pas cacher Unallocated pour faire correspondre la somme de trois segments au total comptable.

### 25.3 Bandeau secondaire

`Sales from New Orders` : `[CA Current Month]`.

`Same-Month Sales Realization` : `[CA Current Month] / [Order Intake EUR]` si les bases sont comparables.

`Sales from Older Orders` : `[CA Last Month] + [CA 2+ Months]`.

Le mot « Filled » de la maquette ne doit pas être interprété comme preuve de livraison complète. Le système réalisé mesure du CA comptabilisé, pas directement les quantités servies.

### 25.4 Graphique mensuel

Pour chaque mois : une colonne Order Intake, et à côté une colonne comptable empilée par cohorte. Ne pas juxtaposer le CA total et ses composantes comme s’il s’agissait de montants indépendants à additionner.

Les ventes doivent conserver les montants négatifs. Si une période en comporte, prévoir un affichage signé adapté ; une barre de parts toutes positives ne doit pas masquer les avoirs.

### 25.5 Temporalité et interactions

Le sélecteur du haut pilote le mois des KPI. Le graphique peut montrer une fenêtre historique terminant sur ce mois. Ne pas laisser le même filtre réduire involontairement la tendance à un seul mois.

Une sélection de cohorte ouvre le détail sans changer silencieusement les dénominateurs des cartes. Les mois partiels doivent être explicités. Le dernier mois disponible n’est pas automatiquement clôturé ou validé.

### 25.6 Contrat minimal d’accès

La page doit consommer les mesures existantes du modèle, via l’intégration déjà présente dans Mining360. Les identifiants workspace/dataset, l’API, l’authentification, le backend et les routes réelles n’ont pas été fournis dans cette conversation.

Ne pas inventer un endpoint. Ne pas télécharger toutes les écritures pour calculer les cartes dans le navigateur. Charger d’abord les agrégats mensuels ; charger le détail à la demande, avec pagination et export conformes aux droits.

La page applicative reste à distinguer de la réalisation Power BI déjà attestée.

---

## 26. Historique des erreurs et enseignements

| Symptôme rencontré | Traitement / interprétation retenue | À ne pas conclure |
|---|---|---|
| `unexpected ';'` en requête native Snowflake | Retrait du point-virgule terminal dans le contexte du connecteur utilisé. | Que toute requête Snowflake interdit un point-virgule. |
| UNION : attendu 79 colonnes, reçu 78 | Ajout de PK_V2 dans chaque SELECT, au même emplacement. | Que UNION aligne les colonnes par leur nom par défaut. |
| Table DAX créée comme mesure | Utiliser Nouvelle table ; pour une carte retourner COUNTROWS. | Qu’un EXCEPT est nécessairement invalide. |
| NATURALINNERJOIN : types/lineage incompatibles | Essai remplacé par TREATAS ; flux final en Power Query. | Que renommer deux colonnes suffit à garantir une lineage commune. [T10] |
| Carte BLANK affichée `--` | COALESCE pour l’affichage, puis contrôle du jeu de clés. | Qu’un zéro après COALESCE prouve des correspondances valides. |
| Factures/commandes non rapprochées | Revoir PK, format, client résiduel, dates et population source. | Que toute absence d’en-tête est une facture manquante. |
| Total de cohorte reprenant janvier | Ancien MIN(Date) ne définissait qu’un mois au total ; SUMX provisoire, puis pré-calcul final. | Que le SUMX de diagnostic reste nécessaire dans la solution finale. |
| Total comptable toutes périodes répété chaque mois | Calendrier non propagé au fait comptable dans ce chemin ; filtrage direct puis relation finale Date. | Que la valeur répétée est un total mensuel. |
| 314 M€ comparés à 172 M€ | Aligner périodes ; l’un était global, l’autre limité à 2026. | Qu’un montant plus élevé prouve une duplication. |
| Doublons DAX négatifs | Résultats non cohérents, contrôle SQL séparant NULL et duplicats. | Que les relations expliquent à elles seules l’impossibilité arithmétique. |
| 387 788 lignes / 387 787 distinctes | Une PK NULL, zéro doublon non NULL dans le contrôle SQL. | Qu’une différence de 1 est toujours un doublon. |
| Merge parent / requête dérivée refusé | Comptage intégré localement, évitant une dépendance inverse. | Que l’interface Merge est incapable de joindre ces clés. |
| Visuels en chargement prolongé | Matérialiser les associations et cohortes en Power Query. | Que toutes les mesures TREATAS sont nécessairement lentes. |
| Relier seulement une dimension clients Mine | Contrôler le contexte et les correspondances effectivement appliqués. | Que la seule existence d’une relation réalise une jointure interne permanente. |
| Reconciliation = 0 | Partition exhaustive du CA dans le contexte testé. | Que chaque attribution métier ou chaque jointure source est forcément correcte. |

### Rectification importante sur REMOVEFILTERS

Une explication antérieure attribuait les filtres d’octobre ignorés au seul `REMOVEFILTERS()` dans le même CALCULATE. Cette causalité n’a pas été établie. CALCULATE accepte des modificateurs et des filtres explicites ; la présence de REMOVEFILTERS n’implique pas, à elle seule, que tous les filtres explicites sont annulés. Conserver l’observation du dysfonctionnement dans les mesures testées, mais pas cette explication comme règle du langage. [T6]

### Rectification sur les relations et le double comptage

Une relation en modèle tabulaire propage des filtres ; elle ne matérialise pas automatiquement une multiplication de lignes comme une jointure SQL. Les erreurs de double comptage du projet venaient du grain, de l’attribution d’une facture à plusieurs commandes ou de jointures physiques potentielles. Les chemins ambigus peuvent néanmoins modifier la population calculée. [T2]

---

## 27. Contrôles de non-régression et exploitation

Les contrôles suivants constituent un **plan de maintenance proposé**. Ceux marqués comme revérifiés ont été recalculés dans ce dossier sur les exports ; leur exécution automatisée dans le service Power BI n’est pas attestée.

### 27.1 Contrôles avant jointure

| Test | Attendu / action |
|---|---|
| PK en-tête non nulle et unique | Isoler les invalides ; ne pas choisir arbitrairement une date. |
| Validité des composants de PK/InvoiceKey | Une chaîne composée non vide ne suffit pas. |
| Couples distincts de bridge | Zéro duplication d’un même couple. |
| Factures multicommandes | Compter et suivre les montants, même si le test 2026 initial était nul. |
| Plusieurs dates pour une même PK | Alerte explicite avant déduplication. |
| Cohérence succursale commande/facture | Ne pas mélanger SUCC et SUCCFAC. |

### 27.2 Contrôles après préparation

| Test | Attendu |
|---|---|
| Unicité de PQ_SingleOrderInvoices par facture | Au plus une ligne. |
| Unicité de PQ_AccountingSales facture/date | Une ligne par couple. |
| Lignes avant/après fusion finale | Identiques. |
| Total CA avant/après | Identique à précision conservée. |
| Comparaison montant par facture/date | Pas d’écart non expliqué. |
| Catégories distinctes | Seulement les cinq catégories définies dans la version actuelle. |
| Date comptable valide | Tous les montants visualisés rattachables au calendrier. |
| Réconciliation sans filtre de cohorte | Écart nul avant arrondi, tolérance documentée à l’affichage. |

### 27.3 Contrôles de détails

Pour octobre 2026 / Current Month, la somme du détail doit retrouver 8 416 346,36 € **dans l’instantané de référence**, sans prendre cette valeur comme constante pour des actualisations futures.

Un export doit préciser période, cohorte, devise et grain. Il doit conserver les identifiants en texte. Une pagination ne doit pas faire passer une page visible pour un export complet.

### 27.4 Rafraîchissement

Le flux dépend de deux systèmes. Des actualisations décalées peuvent temporairement changer le nombre de factures non attribuées. Documenter date d’extraction, date de rafraîchissement et période couverte quand elles sont disponibles.

Une modification de date de commande ou une écriture antidatée peut changer une cohorte historique lors d’un rafraîchissement complet. Aucune politique de gel historique ou d’incrémental n’a été fournie ; ne pas en supposer une.

---

## 28. Sécurité, performance et évolution SQL/ETL

### 28.1 Sécurité

Aucun mot de passe, jeton ou secret n’est inclus dans les scripts. Les noms de bases et tables sont des références techniques internes, à conserver dans un dépôt autorisé.

L’agrégation facture/date ne conserve pas toutes les dimensions de l’écriture source. Une évolution vers des filtres Pays/Société/Client doit vérifier quelles clés sont conservées et comment les droits s’appliquent. Le simple ajout d’un slicer ne suffit pas.

La nouvelle table liée seulement à Date doit être contrôlée contre les rôles RLS du modèle publié. Le fonctionnement de RLS n’a pas été testé dans les fichiers fournis.

### 28.2 Performance

L’amélioration structurelle est de déplacer la recherche des correspondances à l’actualisation. Le temps de rafraîchissement, le pliage des requêtes et l’utilisation mémoire n’ont pas été chiffrés.

Ne pas ajouter `Table.Buffer` systématiquement. Réduire les colonnes, préserver les filtres en source et mesurer le comportement avant d’optimiser. Les fonctions de déduplication et de regroupement ne garantissent pas un ordre stable des lignes. [T7, T8]

Désactiver le chargement d’une requête de préparation peut réduire les objets chargés dans le modèle ; cela ne supprime pas son évaluation lorsqu’une requête finale en dépend. Cette optimisation reste à vérifier avant d’affecter d’autres pages.

### 28.3 Évolution vers une préparation SQL/ETL

Une architecture centralisée pourrait matérialiser :

```text
Mappings commandes historiques
+ Associations opérationnelles facture–commande
+ Comptabilité MI/PARTS
→ table de rapprochement au grain facture/date
→ table de faits cohortée
```

Cette évolution exige l’accès aux deux sources et une stratégie d’actualisation. Elle ne doit pas être présentée comme déjà réalisée ni comme automatiquement plus rapide sans mesure.

### 28.4 Évolution multicommande

Si des factures multicommandes deviennent significatives, créer une allocation contrôlée sur une base financière fiable. Le grain pourrait alors devenir facture × date comptable × commande, avec somme des poids égale à 1 pour chaque groupe attribué et conservation du montant d’origine dans un contrôle séparé.

Ce serait une **nouvelle version du modèle**, différente de la solution à commande unique documentée ici.

---

## 29. Limites restantes et travail documentaire demandé à Codex

### 29.1 À documenter à partir du modèle réel

| Élément | Pourquoi il reste ouvert |
|---|---|
| Expression exacte de Order Intake EUR | Visible comme mesure, non fournie sous forme de code. |
| Montant_EU_lines / MontantEU_Lines | Conversion et quantité non fournies. |
| Code final OrderLineItems History | L’élargissement historique est annoncé, le code final complet n’est pas copié. |
| Filtre Mine / PARTS de l’Order Intake | Le nouvel en-tête n’est plus lié à Mining Customer New selon l’utilisateur. |
| Modèle publié et relations actuelles exhaustives | Pas d’export final TMDL/DMV examiné pour ce dossier. |
| RLS / rôles / accès Mining360 | Non testés. |
| API / dataset / workspace / route frontend | À inspecter dans l’environnement autorisé, pas à inventer. |
| Écart historique de 2 816 741,34 € entre deux vues comptables | Signalé dans plusieurs captures ; explication définitive non démontrée. |
| Raisons fines Unallocated | Agrégation actuelle sans motif détaillé confirmé. |
| Gestion des dates comptables invalides | Formule historique de cohorte à compléter ou protéger explicitement. |
| Collisions métier InvoiceKey_V2 à long terme | Tests ponctuels, pas preuve universelle d’unicité métier. |
| Durées et SLA d’actualisation | Non fournis. |

L’écart historique entre deux vues comptables ne disparaît pas conceptuellement parce que la table finale se réconcilie avec elle-même. La conservation de l’export fournit un contrôle du traitement aval ; la référence comptable complète reste à rapprocher séparément si nécessaire.

### 29.2 Instructions à Codex

Intégrer cette documentation en distinguant :

- la solution Power Query / Power BI réalisée ;
- le journal des investigations ;
- les scripts historiques ;
- les traductions M reconstituées ;
- les limites de preuve ;
- les futures améliorations non implémentées.

Réutiliser les termes exacts du modèle. Ne pas ajouter une colonne supposée, une allocation supposée, un filtre client ou une intégration API fictive. Ne pas transformer les montants d’instantanés en valeurs codées en dur.

La priorité est de rendre la solution **compréhensible, reproductible et maintenable**, pas de masquer les essais ou de donner une certitude non établie sur les points encore ouverts.

---

## 30. Inventaire des annexes et procédure de reproduction

### 30.1 Dossier fourni

```text
DOCUMENTATION_COMPLETE.md
README.md
CODEX_DOCUMENTATION_TASK.md
sql/
  01_OrderHeader_History_snowflake.sql
  02_Neg_llf_complete_snowflake.sql
  03_Neg_FAC_complete_snowflake.sql
  04_Global_CA_Detailled_sqlserver.sql
  05_Global_CA_Aggregated_sqlserver.sql
  06_OrderLineItems_source_historique_snowflake.sql
  07_MiningCustomerNew_sqlserver.sql
  08_Controle_PK_V2_snowflake.sql
  09_Controle_jointure_composants_snowflake.sql
powerquery/
  01_PQ_BridgeCommandeFacture.pq
  02_PQ_AccountingSales_reconstitution.pq
  03_PQ_SingleOrderInvoices_reconstitution.pq
  04_FactSalesAllocation_reconstitution.pq
  05_SalesCohort_formule_historique.pq
dax/
  01_mesures_finales.dax
  02_tables_diagnostic_archive.dax
  03_controles_rapprochement_archive.dax
  04_kpi_derives_proposes.dax
validation/
  verification_Exports_N.json
  reconciliation_mensuelle_export.csv
  benchmarks_octobre_2026.json
  PLAN_DE_TESTS.md
  verify_exports.py
  verification_reproductible.json
sources/
  REGISTRE_SOURCES.md
assets/
  01_maquette_reference.png
  02_reconciliation_2026.png
  03_champs_final_fact.png
  04_dashboard_octobre.png
```

### 30.2 Ordre de reproduction technique

1. Dans un environnement de test, vérifier les tables sources, dialectes SQL et accès.
2. Reprendre les extractions sans changer silencieusement le périmètre des commandes ou du CA.
3. Construire `PK_V2` et `InvoiceKey_V2` de manière cohérente ; valider les composants et leurs conversions.
4. Contrôler l’unicité des PK et isoler les invalides ; contrôler la couverture des associations.
5. Construire `PQ_BridgeCommandeFacture` avec la bonne source historique d’en-têtes.
6. Contrôler la fusion des dates avant toute déduplication masquant une anomalie.
7. Grouper le CA détaillé par facture et date dans `PQ_AccountingSales`.
8. Filtrer les factures à commande unique dans `PQ_SingleOrderInvoices`.
9. Effectuer la jointure externe gauche depuis la comptabilité.
10. Contrôler ligne par ligne le grain et les montants avant/après.
11. Ajouter `SalesCohort` avec la règle de mois calendaires et un contrôle des dates valides.
12. Charger `FactSalesAllocation`, relier seulement sa date comptable à Date pour la page actuelle.
13. Créer les sept mesures finales et tester leur réconciliation hors filtre de cohorte.
14. Vérifier octobre 2026 sur l’instantané disponible ou documenter l’évolution après actualisation.
15. Compléter la définition de l’Order Intake depuis le modèle réel, puis sa comparabilité.
16. Alimenter la page Mining360 avec les mesures réelles ; ne pas réimplémenter les bridges dans le frontend.
17. Tester sécurité, détails, export, mois partiels et absence de régression.

**Conclusion :** le succès ne vient pas d’une nouvelle formule de somme, mais de la clarification des clés, des périmètres et du grain, puis de la préparation d’une table de faits comptable stable. La source des montants reste la comptabilité ; l’opérationnel fournit la commande et sa date ; Power Query matérialise l’association ; DAX expose les sommes ; Mining360 présente le résultat.
