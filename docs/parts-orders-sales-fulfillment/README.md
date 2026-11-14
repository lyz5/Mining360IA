# Parts Orders & Sales Fulfillment — index documentaire

Intégration documentaire du 14 novembre 2026 dans le dépôt canonique Mining360IA.
Les deux documents transmis sont conservés intégralement, sans réécriture. Leur
import ne constitue ni un nouvel audit du modèle publié, ni une intervention sur
Power BI ou BODEFM.

Lire d'abord la [mémoire de reprise et les écarts avec l'application](../PARTS_FULFILLMENT_MEMORY_2026-11-14.md),
puis le [guide complet fourni](DOCUMENTATION_COMPLETE.md). La
[mission documentaire d'origine](CODEX_DOCUMENTATION_TASK.md) définit le périmètre.

## Parcours de lecture

| Besoin | Sections du guide complet | Complément dans le dépôt |
| --- | --- | --- |
| Objectif, dates et cinq cohortes | 1–2 | [Mémoire de reprise](../PARTS_FULFILLMENT_MEMORY_2026-11-14.md#règles-à-conserver) |
| Tables sources, grain et périmètres | 3–5 | [Registre des sources disponibles](sources/REGISTRE_SOURCES.md) |
| Clés PK_V2 et InvoiceKey_V2, succursales | 7–9 | Le code SQL complet des annexes reste absent |
| Préparation finale Power Query | 14–20 | Les blocs M présents dans le guide conservent leur statut confirmé ou reconstitué |
| Mesures DAX et dénominateurs | 21, 24 | [Nom de mesure réellement consommé](../PARTS_FULFILLMENT_MEMORY_2026-11-14.md#mesures-et-champs) |
| Grain, réconciliation et octobre 2026 | 22, 27 | [Références et limites de validation](../PARTS_FULFILLMENT_MEMORY_2026-11-14.md#références-financières-et-validation) |
| Détail et interactions Mining360 | 23, 25 | [Implémentation applicative](../PARTS_FULFILLMENT_IMPLEMENTATION_2026-11-13.md), [publication BODEFM](../PARTS_FULFILLMENT_BODEFM_RELEASE_2026-11-13.md) |
| Diagnostics et versions abandonnées | 6–13, 26 | Ne pas reprendre V1/V2/V3/V4 comme dépendances de la page finale |
| Sécurité et questions ouvertes | 28–29 | [Limites actuelles](../PARTS_FULFILLMENT_MEMORY_2026-11-14.md#points-restant-à-vérifier) |
| Reproduction technique | 30 | Exige les annexes et définitions originales manquantes |

## Architecture finale documentée

```text
Neg_llf_complete + OrderHeader History
  → PQ_BridgeCommandeFacture
  → PQ_SingleOrderInvoices (OrderCount = 1 ; au plus une ligne par facture)

Global CA Detailled (MI / PARTS / hors INTERCO)
  → PQ_AccountingSales (InvoiceKey_V2 × Date ecritures)
  → jointure externe gauche vers PQ_SingleOrderInvoices
  → FactSalesAllocation + SalesCohort
```

Ces flèches décrivent des dépendances Power Query. La relation finale de modèle
documentée est `Date[Date] (1) → FactSalesAllocation[Date ecritures] (*)`, active et
à filtrage simple. Le catalogue exhaustif des relations publiées reste à vérifier.
Les mesures de CA lisent la table de faits ; l'Order Intake doit conserver sa
propre logique de date de création, y compris les commandes non facturées.

## Guide historique et application actuelle

Le guide fourni reconstitue la création Power Query / Power BI. Ses affirmations
« application non inspectée » décrivent les limites de ce dossier d'origine.
L'implémentation et les vérifications Mining360 sont documentées séparément dans
les guides du dépôt. La [mémoire de reprise](../PARTS_FULFILLMENT_MEMORY_2026-11-14.md)
rapproche ces sources sans présenter les anciennes captures comme l'état courant.

En particulier, l'application utilise `[CA +2 Months]`, le bandeau des trois KPI
secondaires a été retiré à la demande de l'utilisateur, et le libellé de légende
`Sales — Future Order` a été retiré. La mesure Future Order reste dans le CA,
la pile, les contrôles et les détails. Aucun filtre Customer / Site n'est prévu.

## Disponibilité et provenance

Le [registre d'intégration](sources/REGISTRE_SOURCES.md) et le
[manifeste SHA-256](sources/manifest.json) distinguent les pièces reçues des pièces
annoncées. Seuls `DOCUMENTATION_COMPLETE.md` et `CODEX_DOCUMENTATION_TASK.md` ont
été transmis ici. Le README d'origine, le registre original, les fichiers SQL,
Power Query, DAX, validation et les quatre images de l'inventaire ne sont pas
présents dans le dossier source accessible.

Les deux images référencées dans le guide ne peuvent donc pas s'afficher. Leurs
liens sont conservés dans le document original, signalés comme manquants dans le
manifeste ; aucune capture de validation n'a été fabriquée ou substituée. Les
références `[S…]` / `[T…]` restent non résolues en l'absence du registre original.

Les blocs de code inclus dans le guide sont lisibles, mais ne remplacent pas les
annexes complètes et ne sont pas attestés comme exports du modèle publié. Les
chiffres restent des références d'instantanés. Aucun classeur, export de lignes,
secret, URL de flux signée ou fichier de credentials n'est intégré à ce dossier.
