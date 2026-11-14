# Validation locale — responsive, desktop protégé

Branche `feature/responsive-desktop-protected-20261114`, base BODEFM `401b973`.
**Bilan de la validation locale avant publication : aucun déploiement,
redémarrage partagé ou changement de modèle/base de production pendant ces tests.**
Le push et la promotion ont ensuite été demandés séparément ; leur statut ne
doit pas être déduit de ce bilan de fixtures.

## Résultats

- 92 tests Django ciblés réussis ; les 7 tests de présentation ont aussi été rejoués après le bootstrap final.
- 330 contrôles de format sur 22 pages, sans débordement horizontal du document ni exception JavaScript.
- Largeurs : 320, 360, 390, 430, 767, 768, 769, 1024, 1199, 1200, 1201, 1280, 1366, 1440, 1920 px ; 1366 × 768 inclus.
- 6 contrôles navigation/filtres et 9 scénarios fonctionnels : réussite.
- 8 pages desktop comparées : géométrie identique, avec et sans thème ; pixels identiques au rendu stabilisé lorsque le thème est désactivé.
- Les quatre échecs historiques documentés dans la référence BODEFM ne sont pas corrigés ou requalifiés par ce chantier.

Les tests financiers comparent les mêmes agrégats et lignes de fixtures avant/après les interrupteurs. Ils ne constituent pas une nouvelle certification des sources, des attributions Power BI ou des identités RLS.

## Parcours réellement vérifiés

- menu opens/closes, focus and main inert restored, no business request.
- shared loading indicator stays compact and leaves navigation clear; no request-policy change.
- filter draft/Cancel preserves applied value and sends no query.
- Apply commits once, one bootstrap request, URL matches context.
- desktop/mobile/tablet/desktop cycle preserves filter and sends no query.
- Mining Turnover URL/back context is retained instead of falling back to Executive.
- More legible with both sidebar preferences; preference restored after resize.
- Parts loaded measures, paired columns, Unallocated rows without an order, textual invoice key.
- Future Order detail exposes distinct accounting and following-month order dates.
- Signed credits use a table; Future Order stays in data/control rather than disappearing.
- Empty source month distinguished from zero and unavailable.
- Existing Copy visual keeps its actual PNG download fallback.
- Failed MTBS displays its own context and hides earlier Availability results.
- Late aborted MTBS response cannot replace newer MTBF result or loading state.
- Chat draft survives keyboard-size emulation, history Escape and desktop/mobile cycle.

## Mesures comparables

Local Windows Edge; fresh browser context per trial, same fixture database and warmed local backend; 3 samples. No CPU/network throttling. Not field p75 or live Power BI timing.
Temps de rendu/état prêt ci-dessous en millisecondes, médianes de 3 essais. Attente de stabilisation des captures exclue du temps prêt. Aucun gain de production n’est déduit de ces fixtures. INP et p75 terrain non mesurés.

| Page | Prêt avant | Prêt après | LCP avant/après | CLS avant/après |
|---|---:|---:|---:|---:|
| business | 225.33 | 208.19 | 220 / 204 | 0.0 / 0.0 |
| parts | 196.29 | 180.67 | 104 / 108 | 0 / 0 |
| reporting | 112.35 | 109.18 | 112 / 108 | 0 / 0 |
| chatbot | 97.74 | 95.75 | 100 / 108 | 0 / 0 |
| viewer | 89.84 | 92.39 | 96 / 96 | 0 / 0 |
| resources | 122.72 | 118.74 | 132 / 124 | 0 / 0 |
| report-config | 105.84 | 117.18 | 100 / 108 | 0.17 / 0.13 |
| excellence | 193.75 | 188.85 | 156 / 140 | 0.02 / 0.01 |

Le CLS initial de 0,26 introduit dans Excellence par le retrait des emplacements de chargement a été refusé et corrigé : les emplacements sont conservés pendant l’attente, sans présenter les anciennes valeurs. La mesure finale figure ci-dessus. Reporting Configuration reste au-dessus de l’objectif CLS 0,1 ; le comportement asynchrone existant est à traiter dans un lot dédié.

## Couverture des 90 états

Chaque ligne distingue vérification d’interface et validation des données. Un cadre « indisponible » Power BI ne valide ni le contenu embarqué ni ses layouts mobiles.

| N° | État | Interface | Limite de source |
|---:|---|---|---|
| 1 | Login | vérifié | fixture locale, production non retestée |
| 2 | Login - Windows credentials form | bloqué | Sélection nécessaire absente des fixtures locales |
| 3 | Business Overview | vérifié | fixture locale, production non retestée |
| 4 | Business Overview - Mining Turnover | vérifié | fixture locale, production non retestée |
| 5 | Business Overview - Sales - Machine Sales | vérifié | Données de test; détail opérationnel ou Published Mapping réel non chargé |
| 6 | Business Overview - Parts Classification | vérifié | Données de test; détail opérationnel ou Published Mapping réel non chargé |
| 7 | Business Overview - Projects & Tenders | vérifié | fixture locale, production non retestée |
| 8 | Parts Orders & Sales Fulfillment | vérifié | fixture locale, production non retestée |
| 9 | Parts Fulfillment - Sales Cohort Details | vérifié | fixture locale, production non retestée |
| 10 | Excellence Center | vérifié | fixture locale, production non retestée |
| 11 | Excellence Center - MTBS | vérifié | fixture locale, production non retestée |
| 12 | Excellence Center - MTBF | vérifié | fixture locale, production non retestée |
| 13 | Excellence Center - MTTR | vérifié | fixture locale, production non retestée |
| 14 | Excellence Center - Fuel | vérifié | fixture locale, production non retestée |
| 15 | Excellence Center - Connectivity | vérifié | fixture locale, production non retestée |
| 16 | Reporting | vérifié | fixture locale, production non retestée |
| 17 | M360 Chatbot | vérifié | fixture locale, production non retestée |
| 18 | Resources | vérifié | fixture locale, production non retestée |
| 19 | Users | vérifié | fixture locale, production non retestée |
| 20 | Data | vérifié | fixture locale, production non retestée |
| 21 | Business Mapping | vérifié | fixture locale, production non retestée |
| 22 | Invoice Tracking | vérifié | fixture locale, production non retestée |
| 23 | Sources | vérifié | fixture locale, production non retestée |
| 24 | M360 AI Admin | vérifié | fixture locale, production non retestée |
| 25 | AI Knowledge Base | vérifié | fixture locale, production non retestée |
| 26 | System Config | vérifié | fixture locale, production non retestée |
| 27 | System Config - Connections | vérifié | fixture locale, production non retestée |
| 28 | System Config - Parameters | vérifié | fixture locale, production non retestée |
| 29 | System Config - Database Servers | vérifié | fixture locale, production non retestée |
| 30 | System Config - Managed Tables | vérifié | fixture locale, production non retestée |
| 31 | AI Config | vérifié | fixture locale, production non retestée |
| 32 | AI Agents | vérifié | fixture locale, production non retestée |
| 33 | Reporting Configuration | vérifié | fixture locale, production non retestée |
| 34 | Workflow | hors lot | Workflow absent du code de référence; 404 préexistante |
| 35 | Downtime Checking | vérifié | fixture locale, production non retestée |
| 36 | Business Mapping - Mapping Health | vérifié | Données de test; détail opérationnel ou Published Mapping réel non chargé |
| 37 | Business Mapping - Conflicts | vérifié | Données de test; détail opérationnel ou Published Mapping réel non chargé |
| 38 | Business Mapping - Publications | vérifié | Données de test; détail opérationnel ou Published Mapping réel non chargé |
| 39 | Business Mapping - Governance | vérifié | Données de test; détail opérationnel ou Published Mapping réel non chargé |
| 40 | AI Knowledge Base - Knowledge Resolution | vérifié | fixture locale, production non retestée |
| 41 | AI Knowledge Base - Power BI Metadata | vérifié | fixture locale, production non retestée |
| 42 | AI Knowledge Base - Business Glossary | vérifié | fixture locale, production non retestée |
| 43 | AI Knowledge Base - KPI Dictionary | vérifié | fixture locale, production non retestée |
| 44 | AI Knowledge Base - Mining Terminology | vérifié | fixture locale, production non retestée |
| 45 | AI Knowledge Base - Question Library | vérifié | fixture locale, production non retestée |
| 46 | AI Knowledge Base - Synonym Library | vérifié | fixture locale, production non retestée |
| 47 | AI Knowledge Base - Synonym Analytics | vérifié | fixture locale, production non retestée |
| 48 | AI Knowledge Base - Test Synonym Resolution | vérifié | fixture locale, production non retestée |
| 49 | AI Knowledge Base - Business Rules | vérifié | fixture locale, production non retestée |
| 50 | AI Knowledge Base - Prompt Library | vérifié | fixture locale, production non retestée |
| 51 | AI Knowledge Base - Recommended Actions | vérifié | fixture locale, production non retestée |
| 52 | AI Knowledge Base - AI Logs | vérifié | fixture locale, production non retestée |
| 53 | AI Knowledge Base - User Feedback | vérifié | fixture locale, production non retestée |
| 54 | AI Knowledge Base - Power BI Interaction | vérifié | fixture locale, production non retestée |
| 55 | Users - Add User form | vérifié | fixture locale, production non retestée |
| 56 | Data - Browser Preview | bloqué | Sélection nécessaire absente des fixtures locales |
| 57 | Resources - Document Detail | vérifié | fixture locale, production non retestée |
| 58 | Chat Readiness | vérifié | fixture locale, production non retestée |
| 59 | Data Quality | vérifié | fixture locale, production non retestée |
| 60 | Downtime Mapping Check | vérifié | fixture locale, production non retestée |
| 61 | Resource Knowledge Administration | vérifié | fixture locale, production non retestée |
| 62 | Deployment Process | vérifié | fixture locale, production non retestée |
| 63 | Reporting Hub - List View | vérifié | fixture locale, production non retestée |
| 64 | AI Configuration - Semantic Model | vérifié | fixture locale, production non retestée |
| 65 | AI Configuration - Query & Response | vérifié | fixture locale, production non retestée |
| 66 | AI Configuration - Business Governance | vérifié | fixture locale, production non retestée |
| 67 | AI Configuration - Test & Diagnostics | vérifié | fixture locale, production non retestée |
| 68 | AI Agents - Agent Router | vérifié | fixture locale, production non retestée |
| 69 | AI Agents - Execution Logs | vérifié | fixture locale, production non retestée |
| 70 | Report - Fleet Performance Report | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |
| 71 | Report - Fuel Monitoring Report | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |
| 72 | Report - LCC Dashboard | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |
| 73 | Report - Mine Logistics Report | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |
| 74 | Report - Mine Logistics Report - Beta | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |
| 75 | Report - Mine Monthly Report - Customer | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |
| 76 | Report - Mine Monthly Report - Neembers | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |
| 77 | Report - Mine Operator Induced Report | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |
| 78 | Report - Mining AfterMarket Perormance - Parts | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |
| 79 | Report - Mining CCR Report | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |
| 80 | Report - Neemba SOS Analysis Report | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |
| 81 | Report - New Tech Sales Report | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |
| 82 | Reporting Configuration - Loaded State | vérifié | fixture locale, production non retestée |
| 83 | Reporting Configuration - Selected Report | vérifié | fixture locale, production non retestée |
| 84 | Reporting Configuration - Appearance | vérifié | fixture locale, production non retestée |
| 85 | Reporting Configuration - Open & Navigate | vérifié | fixture locale, production non retestée |
| 86 | Reporting Configuration - Help & AI | vérifié | fixture locale, production non retestée |
| 87 | Reporting Configuration - Test & History | vérifié | fixture locale, production non retestée |
| 88 | Report - Mine Logistics Report - After bounded load wait | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |
| 89 | Report - Percentage Of Connected Assets Report | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |
| 90 | Report - Prime Movers Operational Status | vérifié | Cadre/état indisponible seulement; contenu et layouts Power BI non testés |

## Limites et prérequis

- Connexion/formulaire Windows complet : configuration AD absente du banc local. Aucun test d’authentification réelle sur mobile.
- Data Browser Preview : aucun browser opérationnel alimenté dans les fixtures ; navigation et panneaux seulement.
- Workflow : route absente dans la référence, aucune fausse page créée.
- Les écrans administratifs vides/en erreur ne valident pas les mutations. Aucun Save, Publish, Run, Sync ou Deploy réel n’a été exécuté.
- La table SQL non gérée de Downtime Checking n’existe pas dans la base SQLite du banc : seul le cadre/état d’indisponibilité est vérifié.
- Viewer : cadre et code d’intégration préservés. Sessions Power BI/Power Apps réelles, rapports complets et changements de taille sous embed live à retester après autorisation, avec les identités habituelles.
- Firefox/WebKit non installés ; iPhone/Android physiques non disponibles. La réduction de viewport simule le clavier et le reflow, pas le matériel ou le SSO.
- Reflow 320px vérifié ; zoom navigateur à 200 % et audit lecteur d’écran manuel complet non effectués.
- CSV métier : service/format/périmètre inchangés par empreinte ; l’export intégral sur source réelle n’a pas été relancé.

## Preuves privées et fichiers protégés

1561 fichiers du manifeste BODEFM contrôlés. Seuls les fichiers de présentation attendus et les deux paramètres de présentation diffèrent. Services Revenue/Parts, accès, permissions, intégration Power BI, routes, migrations et scripts de déploiement restent identiques.

Dossier privé : `exports/Mining360_Responsive_Desktop_Protege_2026-11-14/INDEX.html` à la racine canonique. JSON détaillés, captures avant/après aux trois formats et PNG complets restent ignorés par Git. Les fixtures ne sont jamais importées par l’application.

La désactivation est décrite dans [le guide de mise en œuvre](RESPONSIVE_DESKTOP_PROTECTED_2026-11-14.md). Les tests vérifient la disparition des nouveaux assets, handlers et réservations d’espace dans un nouveau document. Aucun réglage BODEFM n’a été changé.
