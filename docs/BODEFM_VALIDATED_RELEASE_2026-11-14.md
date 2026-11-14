# Version de référence Mining360 — BODEFM, 14 novembre 2026

Cette publication correspond à l'application actuellement en service sur
**BODEFM**, désignée par l'utilisateur comme dernière version validée. Les sources
ont été lues sur `C:\Mining360\app` ; aucun code du répertoire de travail local
n'a servi à constituer l'application publiée.

Référence Git datée : `bodefm-validated-2026-11-14`, publiée avec la branche
`main`. L’historique précédent est conservé, sans réécriture.

## Contenu et preuve de provenance

- Code Django, migrations, vues, templates, JavaScript, CSS, images et scripts
  effectivement présents sur BODEFM, y compris Parts Fulfillment et le login.
- Assets statiques réellement servis, conservés dans
  `deployment/bodefm-runtime-static/`, avec leur manifeste actif et leurs variantes
  compressées. Ce dossier est une copie de livraison, pas une reconstruction locale.
- Versions de Python et des dépendances installées, enregistrées dans
  [le verrou runtime](../deployment/bodefm-validated-20261114/requirements-runtime.lock.txt).
- [Manifeste SHA-256](../deployment/bodefm-validated-20261114/source-manifest.json)
  pour chaque fichier publié. Deux calculs côté serveur et une vérification de
  l'archive transférée ont contrôlé la cohérence de l'extraction.
- [Revue des détections de secrets](../deployment/bodefm-validated-20261114/security-review.json).
  Les détections revues sont des fixtures de tests, le fallback de développement
  protégé ou des contrôles du type d'un champ mot de passe. Aucun secret configuré
  n'est ajouté à Git. La documentation historique de Git reste conservée séparément.

Les fichiers de code/asset reproduisent les octets du serveur. Les nouveaux fichiers
de preuve, le verrou runtime et `.gitattributes` sont des métadonnées de publication.
La copie de travail principale, ses modifications et ses suppressions ne sont pas
fusionnées dans cette version.

## Validation et portée

L'application et la base répondaient `ok` lors de l'extraction. Le parcours Edge
de la même installation a produit 90 pages/vues aux trois formats, dont les 14
lecteurs de rapports du catalogue ; une route Workflow absente répondait 404.
Ces captures privées restent hors Git. Ce parcours ne certifie pas tous les rôles,
tous les onglets internes Power BI ou toutes les règles financières.

Le bilan des contrôles de publication se trouve dans
`deployment/bodefm-validated-20261114/validation.json`. Le terme « validée » conserve
la décision de l'utilisateur sur l'installation de référence ; il ne transforme
pas les limites déjà connues en validation métier exhaustive.

## Reconstituer cette version

1. Partir du commit et du tag BODEFM indiqués dans la publication Git ; ne pas
   mélanger avec une branche de développement du poste local.
2. Préparer l'environnement Windows/Python indiqué par le manifeste et installer
   les dépendances du verrou runtime dans un environnement isolé. Les drivers ODBC,
   SQL Server et IIS restent des prérequis externes.
3. Restaurer séparément la base `Mining360App`, les médias/documents nécessaires et
   les secrets depuis les sauvegardes/coffres autorisés. Les valeurs de secrets,
   données, journaux, caches et l'environnement virtuel ne sont pas dans Git.
4. Configurer les variables non secrètes et secrètes suivant les scripts Windows
   présents sur le serveur et les procédures existantes ; préserver les clés de
   chiffrement nécessaires aux intégrations.
5. Pour reproduire exactement les assets actuellement servis, restaurer le contenu
   de `deployment/bodefm-runtime-static/` dans le `STATIC_ROOT` autorisé. Un nouveau
   `collectstatic` reconstruit les fichiers : le contrôler séparément plutôt que
   le supposer identique à la livraison figée.
6. Valider santé, permissions, Revenue, Parts Fulfillment, rapports et périmètres
   utilisateur avant toute promotion. Aucun déploiement n'est exécuté par cette
   publication Git et aucune migration de base n'est lancée sur BODEFM.

## Évolution suivante

Cette version fournit le point de départ de référence pour les futurs travaux
responsive. Développer et tester les évolutions séparément, puis publier un nouveau
commit identifié. Ne pas remplacer silencieusement cette référence par le contenu
du poste local et ne pas déplacer le tag daté.

Le responsive a ensuite été autorisé et installé au commit `8460c2d`.
Voir [le reçu de cette promotion](BODEFM_RESPONSIVE_RELEASE_2026-11-14.md) pour
les fichiers réellement installés, le rollback et les contrôles. Ce tag reste
la référence antérieure immuable, et non une copie exacte du runtime après
cette promotion. Les limites de validation historiques restent applicables.
