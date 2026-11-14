# Registre d'intégration — 14 novembre 2026

Ce registre a été créé dans Mining360 lors de l'import documentaire. **Ce n'est
pas le registre original annoncé dans le dossier fourni.** Il ne reconstitue pas
arbitrairement la correspondance de ses références `[S1]` à `[S7]` et `[T1]` à
`[T10]` : leur résolution exacte reste à obtenir.

## Pièces effectivement reçues

| Pièce source | Conservation | Portée |
| --- | --- | --- |
| `Downloads/CODEX_DOCUMENTATION_TASK.md` | [Copie intégrale](../CODEX_DOCUMENTATION_TASK.md) | Mission documentaire et contraintes |
| `Downloads/DOCUMENTATION_COMPLETE.md` | [Copie intégrale](../DOCUMENTATION_COMPLETE.md) | Reconstitution de la création du modèle, étapes, code inclus et réserves |

Les tailles et empreintes SHA-256 des originaux sont dans le
[manifeste](manifest.json). Les copies sont identiques octet par octet. Un fichier
`.gitattributes` local au dossier préserve leurs fins de ligne lors des checkouts
Windows et conserve les deux espaces de saut de ligne Markdown du guide. Le code
marqué « confirmé » reste confirmé selon le dossier d'origine ; « revérifié »
signifie recalculé par son auteur sur ses exports, pas recalculé durant cet import.

## Sources du dépôt relues pour le rapprochement

- [Implémentation applicative](../../PARTS_FULFILLMENT_IMPLEMENTATION_2026-11-13.md).
- [Reçu documentaire BODEFM](../../PARTS_FULFILLMENT_BODEFM_RELEASE_2026-11-13.md).
- [Évolutions de présentation et copie des visuels](../../PARTS_VISUAL_COPY_2026-11-14.md).
- [Correspondance des mesures et contrôles d'accès](../../../reports/parts_fulfillment_service.py).
- [Routes, vues et export](../../../reports/parts_fulfillment_views.py).
- Reçus privés existants du correctif `59eac66e` dans
  `.runlogs/parts_fulfillment_deploy/` : statut d'installation, santé, réponse
  authentifiée, agrégats et détails. Leur contenu métier n'est pas importé en bloc.

Voir la [mémoire de reprise](../../PARTS_FULFILLMENT_MEMORY_2026-11-14.md) pour les
écarts de nom de mesure, d'Order Intake et d'interface. Aucune connexion nouvelle
au modèle ou au serveur n'a été réalisée pour cette mission documentaire.

## Pièces annoncées mais absentes

L'inventaire complet de la section 30.1 du guide est enregistré dans le manifeste,
avec le statut `not_supplied` pour les originaux absents : README, neuf SQL, cinq
Power Query, quatre DAX, six validations, registre des sources et quatre images.
Les README et registre d'intégration présents ici sont des créations nouvelles,
pas des substitutions présentées comme les originaux.

Les blocs SQL / M / DAX inclus dans le guide restent consultables. Aucun fichier
annexe manquant n'a été reconstruit pour donner l'impression d'un dossier complet.
Le classeur Exports N.xlsx n'est pas incorporé, ni relu pour de nouveaux contrôles.

## Contrôle documentaire

- Intégrité : copies comparées par SHA-256 avec les deux fichiers transmis.
- Structure : délimiteurs des blocs de code contrôlés et titres du guide conservés.
- Navigation : liens du nouvel index, de la mémoire et de ce registre contrôlés.
- Captures : les deux liens d'image du guide (`01_maquette_reference.png` et
  `02_reconciliation_2026.png`) pointent vers des fichiers absents, répertoriés
  dans le manifeste. Les deux autres images annoncées sont également absentes.
- Validation financière : résultats historiques conservés avec leur provenance ;
  aucun nouveau contrôle live, audit RLS ou test de déploiement n'est revendiqué.
