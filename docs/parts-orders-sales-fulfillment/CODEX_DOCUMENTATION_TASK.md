# Mission Codex — intégrer la documentation Parts Orders & Sales Fulfillment

Tu disposes d’un dossier documentaire sur la réalisation du modèle Power Query / Power BI qui alimente le dashboard de Mining360.

## Objectif

Intégrer cette documentation dans le dépôt existant, selon ses conventions, afin qu’un développeur ou analyste puisse comprendre, reproduire et maintenir la solution. Cette mission est documentaire : ne pas modifier le rapport, les mesures, les relations, les requêtes de production ou la page applicative sans demande explicite.

## Sources et ordre de lecture

1. `README.md`.
2. `DOCUMENTATION_COMPLETE.md`.
3. `sources/REGISTRE_SOURCES.md`.
4. Les fichiers `sql/`, `powerquery/`, `dax/` et `validation/` référencés dans le document.

Les sources du dossier distinguent code confirmé, reconstitution, archive et recommandation. Conserver ces distinctions.

## Travail demandé

- Identifier l’emplacement de documentation approprié dans le dépôt.
- Intégrer le guide complet et ses annexes ; adapter uniquement les liens et l’organisation au dépôt.
- Créer un index permettant de passer de l’objectif métier aux tables sources, transformations, mesures, contrôles et interactions Mining360.
- Conserver les noms de tables et colonnes, les dialectes SQL et la séparation entre relation de modèle et dépendance Power Query.
- Documenter la solution finale `FactSalesAllocation` séparément des essais V1/V2/V3/V4.
- Conserver les contrôles financiers comme références d’instantanés, jamais comme constantes applicatives.
- Signaler explicitement les éléments non vérifiés, notamment Order Intake EUR, Montant_EU_lines, RLS et code final OrderLineItems History.
- Si les définitions live sont accessibles en lecture autorisée, compléter ces sections avec leur code exact et la provenance ; sinon conserver la mention « à vérifier ».
- Vérifier les liens internes, les blocs de code et la visibilité des captures.
- Livrer la liste des fichiers documentaires créés/modifiés et des limites restant ouvertes.

## Contraintes non négociables

- Aucun filtre Customer / Site sur cette page.
- Le CA est analysé par date comptable ; l’ancienneté provient de la date de commande.
- Ne pas copier le CA d’une facture sur toutes les lignes opérationnelles.
- Ne pas attribuer une facture multicommande à plusieurs cohortes sans règle documentée.
- Ne pas convertir Unallocated en « facture manquante » ou « CA non opérationnel ».
- La solution actuelle n’implémente pas une répartition proportionnelle multicommande.
- Ne pas présenter une reconstitution comme le code exact du modèle publié.
- Ne pas réintroduire une boucle Power Query parent → dérivée → parent.
- Ne pas déduire le périmètre de l’Order Intake uniquement des factures déjà comptabilisées.
- Ne pas masquer les réserves sur les dates, les clés et les résultats historiques.
- Aucun changement de droits, aucun déploiement et aucune suppression d’objet de production.

## Résultat attendu

Une documentation intégrée, navigable, techniquement cohérente et traçable, qui explique à la fois la réalisation finale et les décisions qui ont permis d’y parvenir.
