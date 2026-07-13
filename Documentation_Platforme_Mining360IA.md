# Documentation de la plateforme Mining360IA

Date de mise a jour: 2026-07-02

## 1. Vue d'ensemble

Mining360IA est une application Django de consultation et d'analyse pour les operations minières. Elle regroupe quatre axes fonctionnels:

- Reporting Power BI
- AI
- Data Sources
- Resources

L'application expose:

- la liste des rapports Power BI
- l'ouverture de rapports dans l'application
- la verification des sources SQL Server
- la previsualisation des objets SQL via AJAX
- la consultation des ressources documentaires
- l'usage futur de l'API OpenAI pour l'analyse

## 2. Architecture technique

### 2.1 Framework et rendu

- Backend: Django
- Frontend: templates HTML Django
- Style: CSS personnalise dans `reports/static/reports/styles.css`
- Interaction dynamique: JavaScript dans `reports/static/reports/source_actions.js`

### 2.2 Composants principaux

- `reports/views.py`: logique des pages et des endpoints AJAX
- `reports/sqlserver.py`: connexion SQL Server et execution des requetes de preview
- `reports/powerbi.py`: appels Power BI REST API
- `reports/live_sources.py`: gestion des sources enregistrees
- `reports/resource_library.py`: indexation et recherche des documents

## 3. Pages fonctionnelles

### 3.1 Reporting

La page Reporting affiche les rapports du workspace Power BI avec:

- nom du rapport
- dernier refresh
- statut du refresh
- lien d'ouverture dans l'application
- lien direct Power BI quand disponible

Fonctions principales:

- `reporting`
- `report_detail`
- `get_powerbi_reports`
- `get_powerbi_report_embed_info`

Fonctions UI:

- tri et mise en page du tableau
- redirection vers le rapport selectionne

### 3.2 AI

La page AI est reservee aux futures fonctions d'analyse avec OpenAI.

Fonctions attendues:

- interpretation technique des descriptions CAT
- explication des ecarts de classification
- assistance d'analyse sur les ressources et donnees

Fonctions principales cote code:

- `ai_home`
- helpers OpenAI du module `reports/views.py`

### 3.3 Data Sources

La page Data Sources gere les connexions SQL Server et les sources personnalisees.

Fonctionnalites:

- ajout d'une source
- edition d'une source
- verification d'une source
- suppression d'une source
- affichage des tables, vues et custom views
- preview SQL en mode AJAX
- filtres dynamiques
- tri ascendant/descendant sur les en-tetes
- mode fullscreen sur la preview

Fonctions principales:

- `data_sources`
- `source_add`
- `source_edit`
- `source_delete`
- `source_verify`
- `source_detail`
- `source_object_preview`
- `source_table_preview`

Fonctions JavaScript:

- `loadPreviewForCurrentSelection`
- `renderTablePreview`
- `bindPreviewFilters`
- `bindPreviewSorting`
- `setPreviewLoading`
- `setPreviewFilterPanelOpen`
- `syncPreviewFilterRow`

### 3.4 Resources

La page Resources indexe et affiche les documents techniques.

Fonctionnalites:

- vue mosaïque
- recherche par mot-cle
- filtrage par categorie
- ouverture du document dans l'application
- lecture des PDF et fichiers texte indexés

Fonctions principales:

- `resources`
- `resource_detail`
- `resource_search`
- `build_resource_index`

## 4. Filtres et preview SQL

La preview des objets SQL a ete enrichie avec:

- un bouton `Filters`
- une fenetre modale popup
- ajout dynamique de plusieurs filtres
- liaison AND / OR entre filtres
- operateurs `=` et `LIKE`
- detection automatique du type de colonne
- champ calendrier pour les dates
- champ texte pour les chaines et nombres
- validation par bouton `Apply`
- fermeture automatique de la popup apres validation

Comportement de chargement:

- le spinner reste visible pendant toute la requete AJAX
- en fullscreen, le spinner reste affiche au-dessus de la zone de preview
- le timeout de chargement est conserve sur une duree longue cote client

Tri de table:

- clic sur un en-tete de colonne
- tri ascendant au premier clic
- tri descendant au second clic
- indicateur visuel de direction

## 5. Composants UI notables

- sidebar principale repliable
- panneau catalogue repliable
- bouton fullscreen pour la preview
- popup de filtres
- badges de statut pour les refresh
- flash messages AJAX
- spinner de chargement global

## 6. Paquets et dependances

Dependances runtime presentes dans le projet:

- `Django>=5.2.0`
- `requests>=2.32.0`
- `pyodbc>=5.1.0`
- `openai>=2.0.0`
- `pythonnet>=3.1.0`
- `snowflake-connector-python`

Dependance utilisee pour la generation de cette documentation Word:

- `python-docx`

## 7. Fichiers de reference

- `Mining360IA/Mining360IA/settings.py`
- `Mining360IA/Mining360IA/urls.py`
- `Mining360IA/reports/views.py`
- `Mining360IA/reports/sqlserver.py`
- `Mining360IA/reports/powerbi.py`
- `Mining360IA/reports/source_actions.js`
- `Mining360IA/reports/styles.css`

## 8. Notes d'exploitation

- Les identifiants de connexion ne sont pas documentes ici.
- Les sources SQL Server sont verifiees via AJAX et le statut est mis a jour sans rechargement complet.
- Les objets Power BI sont affiches selon la configuration du workspace et des permissions disponibles.
- La documentation doit etre mise a jour a chaque changement de comportement UI ou de flux de donnees.

## 9. Configuration Power BI

L'application utilise l'authentification Azure AD en mode service principal pour appeler l'API Power BI.

Variables attendues:

- `POWERBI_TENANT_ID`
- `POWERBI_CLIENT_ID`
- `POWERBI_CLIENT_SECRET`
- `POWERBI_WORKSPACE_ID`

Resolution des credentials:

1. Lecture des variables d'environnement du process.
2. Si une variable `POWERBI_*` manque, lecture du fichier local `powerbi_credentials.local.json` a la racine du projet Django.

Le fichier `powerbi_credentials.local.json` est volontairement ignore par Git. Il peut contenir les cles suivantes:

```json
{
  "POWERBI_TENANT_ID": "...",
  "POWERBI_CLIENT_ID": "...",
  "POWERBI_CLIENT_SECRET": "...",
  "POWERBI_WORKSPACE_ID": "..."
}
```

Le secret client ne doit pas etre copie dans la documentation.

Un inventaire des options de connexion par rapport est genere dans `powerbi_report_connections.json`.
Ce fichier ne contient pas de secret. Il contient:

- les rapports du workspace utilises par l'application
- les datasets principaux et datasets lies
- les exigences `effective identity`
- les exigences de roles RLS
- les roles disponibles cote interface
- le role par defaut
- le statut du test de generation du token embed

Commande de regeneration:

```powershell
python manage.py sync_powerbi_report_config --test-embed
```

## 10. Test semantique Power BI

Un premier test deterministe a ete ajoute pour valider la future couche IA semantique.

La couche IA doit utiliser les mesures deja creees dans les modeles semantiques Power BI.
Elle ne doit pas recreer les KPI a partir des tables sources, sauf en mode diagnostic lorsque
l'execution directe du modele semantique est indisponible.

Le fichier `semantic_model_dictionary.json` contient le mapping entre:

- termes metier utilisateur
- datasets Power BI
- mesures DAX existantes
- tables et colonnes de filtre
- formats de reponse

Cas traite:

- Question: disponibilite des 777 de Fekola au mois de mai
- Dataset: `FPR Global DB + RLS`
- Mesure existante prioritaire: `Availability Trucks`
- Table equipement: `EquipmentList`
- Filtre modele: `777`
- Table site: `MinesiteList`
- Filtre site: `Fekola`
- Table date: `bravo`
- Table downtime: `Downtimes`

Commande de test:

```powershell
python manage.py test_semantic_question --dataset "FPR Global DB + RLS" --year 2026 --month 5 --model 777 --site Fekola
```

La page `AI` contient maintenant une interface question/reponse connectee au modele semantique Power BI.
Elle supporte les premiers cas:

- disponibilite par `Model`, `MineSite` et mois
- disponibilite de tous les modeles d'un site sur les 12 derniers mois
- affichage de la mesure utilisee
- affichage des filtres semantiques appliques
- affichage du DAX genere
- interpretation automatique simple
- interpretation enrichie par OpenAI lorsque `OPENAI_API_KEY` est configure
- fallback automatique sur les regles semantiques si OpenAI est indisponible

Endpoint AJAX:

```text
/ai/ask/
```

Exemples de questions:

```text
Minesite: Fekola, Date: Mai 2026, Model: 6020
Minesite: Fekola, tous les models sur les douzes derniers mois
```

Configuration OpenAI:

- Cle: `OPENAI_API_KEY`
- Modele: `OPENAI_MODEL`
- Emplacement recommande: `powerbi_credentials.local.json` ou variables d'environnement Windows
- Modele par defaut: `gpt-4.1-mini`

Role d'OpenAI:

1. Comprendre la question utilisateur en langage naturel.
2. Extraire les parametres semantiques: dataset, mesure, site, modele, periode.
3. Enrichir l'interpretation metier apres recuperation du resultat Power BI.

OpenAI ne calcule pas les KPI. Les valeurs numeriques viennent du modele semantique Power BI.

Endpoint de test:

```text
/ai/semantic-test/?dataset=FPR%20Global%20DB%20%2B%20RLS&year=2026&month=5&model=777&site=Fekola
```

## 11. Passerelle Power Automate pour DAX

Les datasets RLS ne peuvent pas etre interroges avec `executeQueries` via service principal.
La passerelle recommandee est un Flow Power Automate execute avec une connexion utilisateur Power BI.

Configuration locale:

- Cle: `POWER_AUTOMATE_DAX_FLOW_URL`
- Emplacement: `powerbi_credentials.local.json`
- L'URL doit etre l'URL POST du trigger contenant les parametres `sp`, `sv` et `sig`.
- Cette URL est un secret d'appel du Flow et ne doit pas etre copiee en clair dans la documentation.

Payload envoye par Mining360IA:

```json
{
  "datasetId": "364edd69-532c-4e10-867f-3b3d4dfdb6c7",
  "datasetName": "FPR Global DB + RLS",
  "query": "EVALUATE ...",
  "question": "Availability for 777 at Fekola in 2026-05",
  "metric": "availability",
  "measure": "Availability Trucks",
  "filters": {
    "EquipmentList[Model]": "777",
    "MinesiteList[Minesite]": "Fekola",
    "bravo[Date]": "2026-05"
  },
  "period": {
    "year": 2026,
    "month": 5,
    "start_date": "2026-05-01"
  }
}
```

Structure du Flow:

1. Creer un `Instant cloud flow` dans Power Automate Cloud.
2. Trigger: `When an HTTP request is received`.
3. Action Power BI: executer une requete sur un dataset.
4. Workspace: Efficience Mine.
5. Dataset: utiliser `datasetId` du payload.
6. Query: utiliser `query` du payload.
7. Response: retourner le resultat Power BI en JSON.

Commande de test apres configuration de l'URL du Flow:

```powershell
python manage.py test_power_automate_dax_flow --show-dax
```
# Business Performance V1

The Business Performance module provides an executive and operational view of customer fleet, Parts revenue and Prime revenue from the Power BI semantic model `Customer Fleet & Revenue Planning Model`.

## Architecture

The browser sends selected filters to Django. `BusinessPerformanceService` validates every logical field against `bp_mappings`, builds controlled DAX, and executes it through the existing Power Automate / Power BI layer. Results are cached for the configured duration and every query is recorded in `bp_query_logs`. Power BI remains the official KPI source.

Business configuration is stored locally by Django and mirrored to SQL Server Mining360 through the existing configuration synchronization mechanism:

- `bp_config`: workspace, semantic model, defaults, cache and thresholds.
- `bp_mappings`: logical names mapped to Power BI measures or columns.
- `bp_query_logs`: page, action, filters, DAX, duration, status and errors.

Secrets are not stored in these tables and are never displayed by the Business Performance configuration page.

## Pages and functions

- Overview: KPI cards, Top Customers, annual revenue trend, Parts Pareto, opportunity matrix and rule-based insights.
- Customers: searchable customer portfolio and navigation to Customer Details.
- Customer Details: filtered customer summary, revenue trend, fleet, Parts and Prime records.
- Parts Sales: server-loaded transaction detail with Excel and CSV export.
- Machine Sales: server-loaded Prime detail with Excel and CSV export.
- Fleet Details: active/inactive fleet detail with Excel and CSV export.
- Config: administrator-only connection settings and semantic mappings.

## Security

Business Performance access requires the Reporting permission and a Business Performance role. Supported roles are Executive, Business Manager, Country Manager, Account Manager, Viewer and Administrator. Administrators have full access. Country/client restrictions are stored in `business_performance_scope` and are added to each query; Power BI RLS remains active and is not bypassed.

## Configuration procedure

1. Open `Config > Business Performance`.
2. Confirm the semantic model name or enter its dataset ID.
3. Map every required logical field to the exact Power BI measure, table or column.
4. Map optional filters and raw-data fields required by the detailed pages.
5. Save, then open Overview and compare the values with the source Power BI report.
6. Assign Business Performance roles from the Users page.

## Seeded Power BI measure candidates

The migration proposes these names for validation: `Fleet`, `Fleet Share %`, `CA Parts`, `Parts Contribution %`, `Parts/Fleet`, `CA Prime`, `Prime/Fleet`, `Total CA`, `Total CA/Fleet`, `Top 3 Contribution`, `Active Customers`, and `Machines Sold`. They are configuration candidates, not duplicated calculations. Table and column mappings are intentionally left for validation against the real semantic model metadata.

## Current V1 boundary

Forecasts, predictive scores, automated LLM insights and PDF Customer Business Reviews are reserved for later versions. The `Forecast & Opportunities` route is structurally reserved but does not generate forecasts in V1.

# Power BI Interaction Copilot

Mining360 AI now separates semantic querying from report interaction. OpenAI returns only a canonical intent. Django validates the section, metric and filters, generates controlled DAX, and resolves every report, page, slicer and visual identifier from validated Knowledge Base records.

The Power BI Interaction administration area is available under `Config > AI Knowledge Base > Power BI Interaction`. It provides Reports, Pages, Visuals, Slicers, KPI-to-Page, KPI-to-Visual, Intent Navigation, Supported Actions, Debug Logs and Navigation Test.

Interaction metadata lifecycle:

1. Import Reports retrieves the workspace report catalog through the Power BI REST API.
2. Discover embeds one report and uses the Power BI JavaScript API to retrieve pages, visuals and slicers.
3. Imported metadata is stored as `To Review`.
4. An administrator reviews internal names, maps filter codes and metrics, then changes the status to `Validated`.
5. Only active and validated records are used by the production chatbot.

The reusable frontend component is `reports/static/reports/powerbi_embed.js`. It embeds reports, refreshes embed tokens, navigates by internal page name, applies mapped slicers or page filters, resolves visuals and records JavaScript API events. Missing visual mappings produce warnings and do not prevent the report page from opening.

Configuration and audit tables are mirrored into SQL Server Mining360. They include `ai_powerbi_interaction_reports`, `ai_powerbi_interaction_pages`, `ai_powerbi_interaction_visuals`, `ai_powerbi_interaction_slicers`, `ai_kpi_page_mappings`, `ai_kpi_visual_mappings`, `ai_intent_navigation_mappings`, `ai_powerbi_supported_actions`, `ai_conversation_contexts` and `ai_powerbi_interaction_logs`.

Security rules:

- Embed tokens and credentials remain backend-only.
- OpenAI never receives credentials or Power BI internal identifiers.
- RLS roles remain part of the controlled DAX and embed-token flows.
- Administration and metadata discovery require a platform administrator.
- Identifiers supplied in a user or AI payload are ignored; only database mappings are used.
