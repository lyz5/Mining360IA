# Fusion locale des chatbots — 19 septembre 2026

## Réalisé

- Un seul accès utilisateur : **M360 Chatbot**, `/codex-chatbot/`.
- `/ai/`, `/ai/new/` et les anciennes adresses de conversations redirigent vers cette interface. Le brouillon transmis depuis Excellence Center est conservé.
- L’ancienne génération `/ai/ask/` et les anciennes API de conversation répondent **410** avec l’adresse du nouvel assistant. Elles ne déclenchent plus l’ancien orchestrateur.
- Migration additive `codex_chatbot.0004_unified_history` appliquée en Development. Import de **28 conversations et 278 messages**, sans supprimer les originaux. Propriétaires, dates et états conservés ; contexte et données des pièces jointes accessibles dans l’export JSON de la conversation. Un second import ne crée aucun doublon.
- Les historiques actifs et archivés, l’archivage/restauration et le téléchargement restent limités au propriétaire.
- L’accès existant au module AI est conservé dans l’assistant unifié. Le drapeau global Disabled continue de bloquer l’accès. Les permissions métier Reporting et financières restent contrôlées par chaque outil ; Codex Admin reste séparé.
- Revenue, disponibilité et inventaire Fleet existants conservés. Ajout des outils MTBF, MTBS, MTTR, carburant et recherche documentaire validée. Les KPI complémentaires utilisent les services d’Excellence Center et leurs filtres, avec les périodes YTD/12 mois glissants.
- Extraction d’intention déterministe et recherche documentaire sans appel d’embeddings OpenAI dans ce parcours. Reformulation par le runtime Codex applicatif existant. En cas d’indisponibilité de Codex, réponse métier de secours explicitement signalée, sans inventer de valeurs.
- Export CSV des indicateurs persistés, protection des cellules contre les formules ; nouveaux liens documentaires limités à l’origine de l’application.

Sauvegarde avant intervention : `../../local-backups/before-chatbot-merge-20260919/` (SQLite vérifié par `quick_check`, sources archivées). Aucun ancien dossier supprimé. Pas de modification de Production, DNS, certificats, mots de passe ou paramètres de sécurité.

## Testé

- **57 tests Django isolés réussis** : import idempotent, propriétaires, droits, archives, anciennes routes, brouillon accentué, absence d’appel à l’ancien LLM, outils, exports, contrats et isolation du runtime. Résultat : `../../chatbot-merge-final-20260919/test-results.json`.
- `python manage.py check` et `python manage.py migrate --check` : succès.
- Redémarrage des processus Development dont l’appartenance à cette installation est validée ; `/health/` sur 8001 : OK.
- Comptages inchangés sur 34 tables protégées, dont les historiques originaux ; `foreign_key_check` : OK.
- Edge : menu unique, redirections, rendu des messages importés et parcours réel envoi → worker → réponse de clarification. Conversation synthétique de test archivée.
- Business Overview, Excellence Center, Reporting et Config AI : pages HTTP 200. Aucune erreur JavaScript lors de ces vérifications.

## Bloqué

Le test réel Codex initialise le serveur, crée le thread et démarre le tour, mais reçoit ensuite une erreur d’authentification. L’identité applicative dédiée n’est donc pas validée pour produire une réponse. Aucune authentification personnelle ou ancienne n’a été copiée.

L’utilisateur doit exécuter interactivement, depuis le dépôt :

```powershell
& '.\deployment\windows\login_chatbot_codex.cmd'
```

Ce lanceur résout le runtime configuré avec le Python du projet et exécute `codex login` dans son `CODEX_HOME`, sans changer l’environnement du terminal parent. Sa résolution a été vérifiée avec `--check-only` ; la connexion interactive n’a pas été exécutée automatiquement. Il ne modifie pas la politique d’exécution PowerShell.

## Non testé et limites

- Les appels Power BI réels de chaque nouvel indicateur et les résultats documentaires réels n’ont pas fait l’objet d’une réconciliation de bout en bout pendant cette fusion. Les tests de contrats utilisent des données synthétiques.
- Le nouveau parcours ne reprend pas encore les interfaces avancées de l’ancien chatbot : dictée, explorateur interactif des arrêts et édition/versionnement des messages. Les données originales sont conservées ; les services techniques associés n’ont pas été supprimés.
- La recherche Internet n’est pas activée dans le runtime actuel, qui interdit les outils externes. Cette fusion ne change pas cette restriction.
- Les autres fonctions de la plateforme utilisant encore l’adaptateur OpenAI historique (par exemple certaines analyses documentaires/SMCS ou transcription) ne sont pas migrées par cette intervention. Ne pas confondre fusion des chatbots et suppression intégrale de toute dépendance OpenAI.
- HTTPS et accès réseau n’ont pas été requalifiés pendant ce travail local.

## Risques et prochaine action

Les intégrations tierces utilisant les anciennes API doivent passer à `/codex-chatbot/api/runs/` ; les réponses 410 sont intentionnelles. La copie historique est un import, pas une synchronisation bidirectionnelle.

Après connexion du profil applicatif : relancer `../../check_chatbot_codex_runtime.py` avec le Python du projet, puis valider une réponse réelle Revenue, un KPI Excellence Center et une recherche documentaire avec des périmètres autorisés. **L’application locale fonctionne ; la conversation Codex reste bloquée par l’authentification.**
