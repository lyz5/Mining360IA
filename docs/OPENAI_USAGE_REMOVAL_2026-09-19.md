# Suppression locale d’OpenAI API Usage — 19 septembre 2026

Module retiré du Development local : menu, template, JavaScript et styles, routes, vues, collecte automatique, middleware de contexte, synchronisation administrative, export et services de budgets/coûts. La commande `sync_openai_usage` est supprimée.

La migration `reports.0147_remove_openai_usage` a supprimé six tables : `OpenAIModelPricing`, `OpenAIUsageLog`, `OpenAICostSnapshot`, `OpenAIUsageSnapshot`, `OpenAIBudget`, `OpenAICreditSnapshot`, ainsi que leurs content types et permissions. La relation devenue inutile dans `VoiceTranscriptionLog` est retirée. Les journaux propres à la transcription sont conservés. La classification SMCS ne consulte plus la table supprimée et ne renvoie plus ses anciennes mesures d’usage comme si elles étaient disponibles.

Sauvegarde complète avant migration : `../../local-backups/before-openai-usage-removal-20260919/db.sqlite3` (5 285 920 768 octets, `quick_check = ok`), avec sauvegarde des sources dans le sous-dossier `source`. Les migrations historiques et ces sauvegardes sont conservées pour la restauration. Une migration inverse ne restituerait pas les données supprimées : une récupération exige la sauvegarde et les sources correspondantes, en tenant compte des éventuelles données nouvelles.

Validation :

- 44 tests ciblés réussis : suppression, AI Config, précédent retrait d’API Management, saisie vocale, Downtime Mapping Check et classification SMCS.
- `manage.py check` et `manage.py migrate --check` réussis ; aucun changement de modèle sans migration.
- Contrôle de clés étrangères correct ; nombres de lignes inchangés dans les 37 tables surveillées.
- Arrêt et redémarrage des seuls processus Development identifiés ; `/health/` répond `ok`.
- Navigateur local : AI Config HTTP 200, aucun lien OpenAI API Usage ni API Management, lien M360 Chatbot présent, aucune erreur JavaScript.
- Les cinq anciennes URL testées (page, dashboard, settings, synchronisation et export CSV) renvoient HTTP 404.
- Aucun content type du module ne subsiste dans la base locale.

Preuves dans le dossier parent : `openai-usage-removal-result.json`, `openai-usage-removal-browser.json`, `openai-usage-removal-tests/test-results.json`, `openai-usage-removal-smcs-tests/test-results.json`. Capture dans `runtime/.runlogs/openai-usage-removal/`.

Aucune modification de Production, de DNS, de certificat ou de credential. Aucun appel IA externe réalisé pour les tests. Le retrait du suivi d’usage ne migre pas les appels OpenAI hérités vers Codex ; le moteur et les outils métier de M360 Chatbot restent distincts.
