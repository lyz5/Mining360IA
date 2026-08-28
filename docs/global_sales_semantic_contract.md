# Global Sales semantic contract

Status: discovery in progress. This document records validated source facts and prevents Mining 360 from creating parallel financial logic.

## Source of truth

```text
NMBEPM analytical ledger
  -> Global Sales transformation
  -> Power BI semantic model used by Mine Logistics & AfterMarket
  -> Mining 360 Global Sales
```

Mining 360 must query validated Power BI measures. It must not reproduce the source SQL revenue calculation or maintain a separate financial result.

## Validated model objects

- Fact table: `F_Ecriture_Analytique`
- Budget fact: `F_Budget`
- Customer: `D_Client`
- Equipment and serial number: `D_Equipement`
- Equipment model/nature/type: `D_Modele_Equipement`, `D_Nature_Equipement`, `D_Type_Materiel`
- Product classification: `D_LOB`, `D_Famille_Comptable`, `D_Categorie_famille_comptable`, `D_Hierarchie_Produit`
- Service classification: `D_Service`
- Manufacturer: `D_Constructeurs_Analytique`, `D_Constructeurs_Bi`
- Organization: `D_Business_Unit`, `D_Societe_Groupe_Neemba`
- Channel: `D_Canal_Distribution`
- Geography: `D_Territoire`, `D_Territoire_Analytique`, `D_Pays`

## Measures

The preferred official revenue measure is `CA en €`, subject to confirmation of its DAX expression and active relationships. Existing YTD, MTD, K and M variants must be used for their corresponding experiences rather than recreated in Mining 360.

Validated global YTD measure:

- `YTD Parts Sales Dyn`: despite its name, this measure returns global Sales YTD across Parts, Machines and Services when no report-level Sales-domain filter is applied. Mining 360 mapping: `global_revenue_ytd`.

The existing Power BI report obtains Parts YTD by applying a global `PARTS` filter around this measure. Mining 360 must not expose it as Parts Sales until the filter's exact semantic table, column and value are validated and configured. Machine and Services values must use the same governed domain-filter mechanism where valid.

Validated invoice revenue measures:

- EUR: `CA Facture EU` (`global_revenue_eur`)
- US dollar: `CA Facture US` (`global_revenue_usd`)
- CFA/XOF: `CA Facture XO` (`global_revenue_cfa`)

These measures are the official source for displayed revenue. YTD, MTD or custom periods must be obtained through the approved semantic-model date context; Mining 360 must not convert currencies or sum raw debit/credit columns.

Margin, cost, budget, prior-year variance and Top Clients must also resolve through their validated semantic-model measures.

## Governed Sales domains

The application supports three target domains:

- Parts Sales
- Machine Sales
- Services Sales
- Rental Sales

LOB is the approved primary Sales-domain discriminator. Other dimensions such as `D_Hierarchie_Produit`, `D_Famille_Comptable`, `D_Service`, `D_Business_Unit` and manufacturer may support analysis, but must not replace the governed LOB rule without business validation.

Validated domain mapping:

- Semantic field: `GlobalCA[LOB]`
- Parts Sales: `LOB = PARTS`
- Machine Sales: `LOB = PRIME`
- Services Sales: `LOB = SERVICE`
- Rental Sales: `LOB = RENTAL`

The LOB filter must wrap official semantic-model measures. It must not be embedded in a replacement revenue calculation.

Mappings remain configuration data and must be validated by the business before activation.

## Discovery still required

1. DAX expression and home table of `CA en €`.
2. Active and inactive relationships used by official CA measures.
3. Distinct values and revenue coverage for LOB, product detail, accounting family, invoiced service, division and manufacturer.
4. Validated Parts, Machines and Services classification, including overlap and unmapped handling.
5. CAT versus Non-CAT rule.
6. Onshore, Offshore and Interco rule.
7. Authoritative territory field.
8. Customer key and display field.
9. Equipment key, serial number and null coverage.
10. Revenue restatement, exclusion and currency rules embedded in measures.

## Reconciliation gate

Before production activation, compare Mining 360 and the Power BI report for the same:

- period;
- company and branch;
- customer;
- Sales domain;
- territory;
- currency;
- RLS identity.

The total and all domain subtotals must match Power BI. A difference blocks publication; it must never be corrected by adding an ungoverned frontend calculation.

## Current technical limitation

Power BI REST `ExecuteQueries` rejects the service principal for this RLS model, and the configured Power Automate flow is currently unavailable. Semantic metadata inspection must resume through an authorized delegated identity, a repaired governed flow, or an approved metadata export from Power BI Desktop/XMLA.
