# Validation fonctionnelle locale du 29 septembre 2026

Mise à jour ultérieure : le profil applicatif du chatbot est désormais authentifié et six parcours SNIM-Guelb ont été validés dans Edge. Voir [SNIM_GUELB_CHATBOT_VALIDATION_2026-09-29.md](SNIM_GUELB_CHATBOT_VALIDATION_2026-09-29.md). Le constat d'authentification ci-dessous décrit le contrôle antérieur ; les autres limites restent applicables.

L'application est utilisable partiellement sur `http://127.0.0.1:8001/`. La restauration complète n'est pas validée : le moteur Codex du chatbot n'est pas authentifié, deux migrations destructrices restent en attente et le corpus documentaire manque.

## Réalisé

- Diagnostic sur le réseau NEEMBA, confirmé par l'utilisateur : résolution du contrôleur Active Directory, TLS avec confiance Windows et bind du compte technique réussis. Dernier audit utilisateur : succès le 29 septembre à 02:13:40 UTC. Aucun mot de passe utilisateur essayé par l'agent.
- Correction d'un événement de suivi dans `reports/static/reports/homepage_command_center.js` : le changement de KPI envoyait `metric_change`, absent des types acceptés par le serveur. Il utilise maintenant `filter_change` avec `action=metric_change`. Aucun calcul, droit, mapping ou schéma modifié.
- Playwright installé dans le venv du projet ; utilisation d'Edge existant sans fenêtre sur l'instance applicative existante. Pas de deuxième serveur.

## Testé

- `python manage.py check` : succès. `python -m pip check` : succès.
- Une instance HTTP 8001 (PID 19976), une passerelle 443 (PID 14544), un worker (PID 25792), identités reconnues par le contrôleur. Les processus parents Python sont les lanceurs du venv.
- HTTPS via boucle locale avec SNI et certificat restauré explicitement vérifié : 200, base OK. Cela ne valide pas l'ancienne URL dans le navigateur.
- Business Overview : page et API en 200, changement YTD vers MTD, quatre onglets Executive/Mining Turnover/Sales/Projects & Tenders fonctionnels. Pas de recalcul indépendant des montants.
- Excellence Center : Availability, MTBF, MTBS, MTTR et Fuel répondent avec HTTP 200 et `ok=true`. Après correction, événements de changement acceptés (201), aucune erreur HTTP locale ni JavaScript détectée dans le contrôle final.
- Reporting : recherche filtrant le catalogue, état de recherche dans l'URL, vue liste, ouverture d'un rapport, configuration Power BI et iframe chargées. Le lecteur atteint `Ready`. Un rapport testé, pas le catalogue complet.
- M360 Chatbot : soumission 202, suivi 200, message assistant affiché. La question contenant « Mining » a déclenché une clarification de périmètre (correspondances de clients). La question `Quel est le Revenue Parts YTD ?` a obtenu une preuve gouvernée, mais termine `PARTIALLY_SUCCEEDED / PARTIALLY_ANSWERABLE`.
- Cause confirmée du résultat partiel : `CODEX_RUNTIME_UNAVAILABLE`, réponse distante 401 sans authentification. `codex login status` dans le profil applicatif `.test-runtime/codex-chatbot-home` retourne `Not logged in` (code 1). Aucun contenu de fichier d'authentification lu ou copié.
- Les erreurs Service Unavailable présentes dans le journal Waitress concernent `/api/access-control/directory/search/` ; pas de traceback détecté lors de cette inspection. Le bind Active Directory actuel réussit ; la recherche utilisateurs complète n'a pas été retestée.

Les sessions navigateur temporaires utilisent le compte existant du dernier audit de connexion réussi et sont supprimées en `finally`. Aucun mot de passe, cookie ou jeton persisté dans les preuves. Deux conversations de test et les événements d'utilisation normaux restent dans l'historique ; aucune donnée existante supprimée.

## Non testé

Tous les rapports et exports, les rôles non administrateurs/RLS de bout en bout, les scénarios métier exhaustifs, la reformulation IA après authentification, la recherche documentaire du chatbot et la validité métier indépendante de tous les chiffres.

## Bloqué

- Profil applicatif Codex non connecté ; nouvelle authentification utilisateur nécessaire. L'ancienne authentification n'a pas été restaurée.
- `manage.py migrate --check` : code 1 ; `reports.0146_remove_api_management` et `reports.0147_remove_openai_usage` non appliquées car elles suppriment des données et permissions. Voir le rapport de rapprochement pour leur contenu.
- Nom `mining360-dev.neemba.local` toujours non résolu au contrôle. Aucun changement DNS/hosts ni magasin de certificats.
- Corpus de recherche Resources et revues source de septembre 23–24 absents. Les 448 PDF restaurés précédemment ne remplacent pas ce corpus et ne constituent pas une lecture intégrale.

## Risques

Le fonctionnement dépend du réseau d'entreprise pour les intégrations. Le chatbot présente actuellement une réponse gouvernée de secours, sans reformulation Codex. La formulation « Mining » peut être interprétée comme un client et nécessiter une précision. Le passage des tests ne constitue ni une validation de tous les parcours ni une autorisation de supprimer les sauvegardes.

## Prochaine action

Depuis le projet, l'utilisateur exécute :

```powershell
.\.venv\Scripts\python.exe deployment\windows\login_chatbot_codex.py
```

Ce lanceur existant appelle `codex login` avec le profil réellement utilisé par M360 Chatbot, sans copier celui de l'autre machine. Son mode `--check-only` a été vérifié. Terminer la connexion dans le navigateur, puis retester une réponse du chatbot. Référence : https://learn.chatgpt.com/docs/auth.

Preuves locales sans cookies ni réponses brutes : `.migration-review/browser-validation-current.json`, `.migration-review/browser-validation-followup.json`, `.migration-review/restore-20260929/runtime-validation.json`. Le script `.migration-review/browser_validation_current.py` effectue de vraies interactions et crée une conversation de test à chaque exécution ; ce n'est pas une vérification sans effet de bord.
