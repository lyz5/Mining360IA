# Suppression locale d’API Management — 19 septembre 2026

Suppression appliquée au Development de cette machine. Aucun accès ni changement de Production pendant cette intervention.

## Réalisé

- Retrait du menu, des cinq templates, du JavaScript et des styles dédiés, des vues et des routes de gestion.
- Retrait du panneau fournisseur dans AI Agents, de son endpoint et des commandes de bootstrap/health du catalogue.
- Suppression des services de catalogue, routage multi-fournisseurs, budgets, circuit breaker, credentials et journaux dédiés.
- Migration `reports.0146_remove_api_management` appliquée : neuf tables retirées, avec les content types et permissions dédiés.
- Mise à jour du générateur documentaire et du script de captures ; anciens assets collectés retirés et fichiers statiques recollectés.
- Redémarrage des seuls processus identifiés comme appartenant au Development : Waitress, worker Codex et passerelle HTTPS. Aucun changement DNS, certificat ou magasin de confiance.

Les migrations historiques restent présentes pour permettre la reconstruction cohérente du schéma. Elles ne réactivent pas le module après la migration 0146.

## Données et restauration

Sauvegarde SQLite complète avant migration : `../../local-backups/before-api-management-removal-20260919/db.sqlite3`, 5 285 912 576 octets, `PRAGMA quick_check = ok`. Les sources modifiées ou retirées ont également été sauvegardées dans le sous-dossier `source`.

Les nombres de lignes des 36 tables surveillées (Business Mapping, Business Overview, Codex et utilisateurs) sont inchangés. Le contrôle des clés étrangères après migration est correct. Cela ne remplace pas une comparaison exhaustive de toutes les valeurs métier.

Une migration inverse recréerait les tables sans récupérer leurs anciennes données. Pour retrouver le catalogue supprimé, utiliser la sauvegarde et les sources correspondantes, services locaux arrêtés ; ne pas remplacer une base ayant reçu de nouvelles données sans réconciliation préalable.

## Vérifications

- `python manage.py check` : réussi.
- `python manage.py migrate --check` : réussi après application.
- `makemigrations --check --dry-run` : aucun changement manquant.
- 11 tests ciblés de suppression et AI Config : réussis.
- Suite générale isolée : 687 tests, 672 réussis, trois assertions KPI déjà en échec avant modification et douze erreurs déjà présentes liées aux restrictions de l’environnement d’audit. Aucun nouvel échec identifié.
- Syntaxe du JavaScript AI Agents : correcte.
- Navigateur local : AI Config HTTP 200, aucun lien API Management, lien M360 Chatbot présent, aucune erreur JavaScript de page.
- Anciennes pages/API de gestion contrôlées avec une session administrateur éphémère : HTTP 404. Session supprimée après test.
- `http://127.0.0.1:8001/health/` : statut et base `ok` après redémarrage.

Preuves dans le dossier parent : `api-management-removal-result.json`, `api-management-removal-browser.json`, `api-management-removal-focused/test-results.json` et `api-management-removal-tests/test-results.json`. Capture : `../.runlogs/api-management-removal/ai-config-without-api-management.png`.

## Limite explicite

Cette intervention retire **API Management**, pas toutes les fonctions utilisant encore une API OpenAI. Les anciens consommateurs partagés (Mining360 AI, transcription, embeddings et classifications) passent désormais par une petite intégration directe `legacy_ai_service`, utilisant la configuration OpenAI existante hors catalogue. Il n’y a plus de sélection Claude/Gemini/GLM, de routage par agent ni de fallback multi-fournisseurs. Aucune requête externe payante n’a été exécutée pour les tests.

M360 Chatbot conserve son moteur Codex et ses outils métier. La migration des autres usages vers Codex reste un chantier distinct ; la transcription et les embeddings ne doivent pas être déclarés disponibles via Codex sans une implémentation et des tests spécifiques.
