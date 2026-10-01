# SNIM-Guelb — validation locale du chatbot, 29 septembre 2026

## Relances KPI avec contexte — 30 septembre 2026

Les relances explicites et les demandes courtes telles que « Et le MTTR ? », « le MTBF ? », « Et le LPH ? » et « Et la disponibilité ? » reprennent le dernier périmètre Performance vérifié de la même conversation et du même propriétaire. Seuls les filtres et la période sont transmis : la nouvelle mesure est récupérée par les services gouvernés avec un nouveau contrôle des accès. Un contexte absent ou composé de plusieurs périodes demande une clarification. Une période YTD ajoutée par défaut par le parseur ne remplace plus la période précédente ; une période explicitement demandée la remplace.

Validation : 22 tests ciblés réussis. Conversation réelle de huit demandes, toutes SUCCEEDED sans appel Codex : 789 / SNIM-Guelb / janvier–août conservé sur MTBF, MTBS, MTTR, Fuel et disponibilité, puis passage explicite à juillet correctement conservé par « Et le LPH ? ». Les relances prennent entre 1,2 et 3,9 secondes dans ce contrôle. Une neuvième demande dans une nouvelle conversation obtient NEEDS_CLARIFICATION. Les changements explicites de site et de modèle sont couverts par les tests unitaires, pas par une nouvelle requête réelle multi-sites.

Preuves : `.migration-review/verify_kpi_followup.json`. Sauvegarde : `.migration-review/kpi-followup-before/`. Development redémarré sous contrôle du propriétaire des processus ; aucun déploiement Production.

## Réponses KPI rapides — 30 septembre 2026

Les demandes simples de valeurs Availability, MTBF, MTBS, MTTR et Fuel LPH utilisent maintenant une réponse déterministe après récupération des preuves gouvernées. Les explications, comparaisons, recommandations, documents et tableaux détaillés conservent le parcours existant. Le rendu rapide affiche les unités fournies, le périmètre, les dates exactes, la couverture et la fraîcheur disponibles. Les sources, les contrôles d'accès et les caches existants ne sont pas modifiés ; aucune nouvelle parallélisation des requêtes n'est introduite.

Validation : 18 tests ciblés réussis et contrôle Django sans erreur. Redémarrage contrôlé de Development, puis six requêtes HTTP réellement traitées par le worker, toutes SUCCEEDED et sans native_turn_id Codex. SNIM-Guelb / 789 / janvier–août : disponibilité 84,14 % en 6,68 s ; MTBF 21,24 h en 2,58 s ; MTBS 16,54 h en 6,67 s ; MTTR 5,43 h en 2,58 s ; Fuel 121,6 L/h en 3,09 s. La disponibilité répétée avec cache prend 0,53 s. Couverture retournée : 44 équipements pour la performance, 16 pour Fuel. Ces mesures ponctuelles incluent la file locale et ne garantissent pas les mêmes délais sous charge. Les analyses IA n'ont pas été chronométrées dans ce contrôle.

Preuves : `.migration-review/benchmark_quick_kpi.json`. Sauvegarde avant modification : `.migration-review/chatbot-speed-before/`. Les journaux stderr des trois composants du nouveau lancement sont vides. Aucun déploiement Production.

## Alignement YTD d'Excellence Center

Le YTD de l'API Excellence Center utilise maintenant le même résolveur de mois terminés que le chatbot, avant la requête et la sélection du cache. La règle couvre Availability, MTBF, MTBS, MTTR et Fuel. Les autres périodes et les contrôles d'accès sont conservés. En janvier, une erreur explicite indique qu'aucun mois de l'année n'est terminé. L'intervalle exact est affiché dans la page.

Validation : 11 tests ciblés réussis, contrôle Django sans erreur, redémarrage de l'instance Development identifiée. Dans Edge, YTD SNIM-Guelb / 789 renvoie 01/01/2026–31/08/2026, **84,14 %**, 44 équipements et huit mois dans la tendance, sans erreur JavaScript. Les trois journaux stderr du nouveau lancement sont vides. Les autres indicateurs ont été contrôlés par tests de routage ; leurs valeurs réelles n'ont pas été revérifiées dans ce changement. Production non déployée.

Preuves : `.migration-review/excellence-ytd-check.json`, `.migration-review/excellence-ytd-closed.png`. Sauvegarde du code avant modification : `.migration-review/excellence-ytd-before/`.

## Correction d'affichage du top 10

La réponse textuelle donnait dix catégories mais les tableaux complémentaires rendaient encore toutes les lignes, dont un tableau « Verified metrics » en double. Le rendu JavaScript limite désormais le classement des systèmes à dix catégories et omet ce doublon. Le résumé et le dénominateur restent visibles ; l'export CSV et les preuves complètes ne sont pas tronqués. Le script est versionné pour rechargement, sans redémarrage des services.

Contrôle dans Edge sur une conversation existante : dix catégories correspondant aux dix premières lignes vérifiées, aucun doublon « Verified metrics », aucune erreur JavaScript. Preuves : `.migration-review/top10-display-check.json`, `.migration-review/top10-display.png`. Sauvegarde préalable : `.migration-review/top10-display-before/`. Les conversations existantes bénéficient de la correction après rechargement de la page.

## Règle YTD : exclure le mois en cours

À la demande de l'utilisateur, le YTD Performance du chatbot s'arrête au dernier jour du mois précédent, en fonction de la date locale. Au 29 septembre 2026 : 1er janvier–31 août 2026. Le mois en cours reste exclu jusqu'au passage au mois suivant. En janvier, aucun mois terminé de l'année en cours n'existe : clarification explicite, sans bascule implicite sur l'année précédente.

La règle s'applique à la disponibilité, aux autres indicateurs Performance, aux comparaisons mensuelles YTD et aux downtime drivers du chatbot. Une relance « sur cette période » conserve la plage explicite vérifiée. Les plages explicites, MTD et douze mois glissants gardent leur sens. Aucun calcul Revenue ou mapping publié n'a été modifié. Mois calendaire terminé ne signifie pas couverture source exhaustive.

34 tests ciblés passent. Après redémarrage contrôlé, validation dans Edge :

- disponibilité des 789 à SNIM-Guelb YTD : **84,14 %**, 44 équipements, **01/01/2026–31/08/2026** ; réponse `SUCCEEDED / ANSWERABLE` ; comparaison source 2025 : 85,61 %, écart −1,47 point ;
- relance downtime drivers : même plage explicite, exactement dix catégories dans la réponse, total de toutes les catégories **40 706,72 h** ; rapprochement avec Excellence Center sur la même plage, somme des catégories et parts vérifiée ;
- export CSV des catégories, heures et pourcentages téléchargé et vérifié ; aucune erreur JavaScript, session temporaire supprimée.

Preuves : `.migration-review/snim_closed_ytd_browser.json`, captures `snim-closed-ytd-1.png` et `snim-closed-ytd-2.png`, export `snim-closed-ytd-export.csv`. Sauvegarde préalable : `.migration-review/ytd-complete-months-before/`.

Les valeurs historiques ci-dessous, notamment 85,77 % et 41 012,72 h, correspondent à l'ancien périmètre incluant septembre. Elles ne sont plus les valeurs du YTD demandé selon cette nouvelle règle. Les anciennes conversations ne sont pas réécrites.

## Règle de présentation : dix downtime drivers

À la demande explicite de l'utilisateur, les réponses « top downtime drivers » présentent toujours les dix premières catégories, triées par heures décroissantes. S'il existe moins de dix catégories, le nombre réellement disponible est indiqué sans inventer de ligne. Le texte du classement est construit directement à partir des valeurs vérifiées, sans reformulation susceptible de réduire la liste à cinq ; la réponse de secours utilise le même texte. Les données complètes et le dénominateur de toutes les catégories restent conservés.

Cinq tests ciblés passent. Vérification supplémentaire sur les preuves SNIM-Guelb : exactement dix lignes dans la réponse, 51 catégories source conservées, total inchangé. Preuve : `.migration-review/top10-verified-answer.txt`. Sauvegarde des deux fichiers précédents : `.migration-review/top10-before/`.

## Complément : bouton Envoyer, 29 septembre à 12:03 UTC

Après le signalement d'une question sans réponse, le serveur local répondait en HTTP 200 et aucune nouvelle demande utilisateur n'était enregistrée. L'URL utilisée par l'utilisateur n'a pas été confirmée ; la cause exacte dans son onglet reste donc non établie.

Un défaut navigateur a été reproduit : en l'absence de `crypto.randomUUID`, le gestionnaire d'envoi échouait avant son bloc de traitement des erreurs, ne transmettait aucune requête et restait verrouillé. Correction dans `chatbot.js` : UUID v4 via `crypto.getRandomValues` si nécessaire, et préparation de l'envoi incluse dans le traitement des erreurs. Version du script actualisée dans le template pour recharger le fichier corrigé. Aucun changement de sécurité, de calcul, de permission ou de service.

Validation : syntaxe JavaScript valide ; essais Edge avec requêtes interceptées, API randomUUID présente puis absente, deux envois successifs dans chaque cas. Aucun blocage, aucune erreur JavaScript, texte conservé et saisie réactivée après échec simulé. Puis soumission réelle de la formulation exacte « Donne moi la disponibilité des 789 à SNIM-guelb depuis le début de l'année » : `SUCCEEDED / ANSWERABLE`, 85,77 % sur 44 équipements, réponse après 37,1 secondes dans le contrôle navigateur. Session temporaire supprimée.

Preuves : `.migration-review/chat-submission-diagnostic.json`, `.migration-review/chat_submit_live_check.json`, `.migration-review/chat-submit-recovery-1.png`. Sauvegarde des fichiers précédents sous `.migration-review/chat-submit-before/`. Pour charger le correctif dans un onglet déjà ouvert : recharger la page. L'URL locale vérifiée est `http://127.0.0.1:8001/codex-chatbot/`.

## Complément final : downtime drivers par système / catégorie

La demande utilisateur précise que « downtime drivers » désigne Engine, Electrical System, Transmission, etc. Ce sens remplace le classement par équipement pour cette formulation. Une demande explicite « top downtime par équipement » garde le classement des machines.

- Source configurée : `DowntimeData_MiningProd[DescriptionCat]`, mesure `[DonwtimeHours]`. Aucune modification des mappings, de la source, de Production ou de BODEFM.
- Nouveau lecteur local `codex_chatbot/tools/downtime_systems.py` : reprend le contexte de dates vérifié, les filtres et les contrôles de périmètre du service Performance, puis transmet l'identité effective et le rôle RLS existants à la source.
- Les heures et pourcentages sont évalués dans la requête sémantique : heures de la catégorie / heures de toutes les catégories du même périmètre × 100. Aucun dénominateur limité au top 5 et aucun regroupement arbitraire des catégories Engine et de ses sous-systèmes.
- Les catégories vides ayant des heures restent visibles sous « Non classé ». Aucun pourcentage n'est inventé si le dénominateur est nul. Les totaux manquants, invalides, tronqués ou différents d'Excellence Center provoquent une indisponibilité explicite. Aucun contournement d'un lecteur de snapshots réplique non compatible.
- La classification source contient aussi PM, Daily Inspection et d'autres catégories d'activité ; elle ne constitue pas un diagnostic des causes racines.

29 tests ciblés passent. Dans Edge, les deux phrases exactes successives « Donne moi la dispo des 789 à SNIM-guelb en YTD? » puis « Donne moi les top downtimes drivers sur cette période » terminent `SUCCEEDED / ANSWERABLE` dans la même conversation. La deuxième réponse donne les catégories et leurs parts, avec le tableau complet de 51 catégories. L'export CSV a été téléchargé et vérifié : catégories, heures et pourcentages présents. Aucune erreur JavaScript ; sessions temporaires supprimées.

Rapprochement : 41 012,723332 h de catégories pour 41 012,723331999994 h de total sémantique, différence d'arrondi machine seulement ; somme des parts 100 %. Les 51 catégories du chatbot correspondent à la lecture source indépendante. Aucun recalcul indépendant des événements bruts n'est revendiqué.

| Catégorie source | Heures | Part du total |
| --- | ---: | ---: |
| Engine | 3 525,39 | 8,60 % |
| Transmission | 1 257,75 | 3,07 % |
| Electrical System | 434,08 | 1,06 % |

Preuves : `.migration-review/system-drivers-source.json`, `.migration-review/snim_systems_browser.json`, `.migration-review/snim-systems-export.csv`, captures `snim-systems-1.png` et `snim-systems-2.png`. Conversation de test : `60d87e48-216e-475c-aef4-9e0e476a6f24`. Sauvegarde préalable sous `.migration-review/system-drivers-before/`. Journaux du démarrage `20260929-11533*` inspectés : aucune ERROR ni Traceback ; health local confirmé après redémarrage contrôlé.

Les réserves sur les dates YTD déclarées par la source restent celles du rapport initial. Les autres sites, les comptes non administrateurs et toutes les formulations libres n'ont pas été validés en navigateur.

## Complément : relance downtime dans la même conversation

Les deux erreurs signalées par l'utilisateur correspondent aux runs du 29 septembre à 11:28:57 et 11:29:51 UTC, avant la connexion applicative réussie. Un défaut supplémentaire de routage était présent : « downtimes » au pluriel partait en conversation générale et aucune reprise du périmètre métier précédent n'était effectuée.

Correction locale ciblée : reconnaissance de `downtimes`, reprise du seul périmètre vérifié de la demande immédiatement précédente dans la même conversation et pour le même propriétaire, nouvelle lecture des données avec les contrôles d'accès actuels. Sans contexte unique, une clarification est requise. Les anciennes valeurs ne sont jamais réutilisées. La vue downtime renvoie les heures d'arrêt enregistrées, ordonnées par la source, et précise que les causes de panne ne sont pas établies.

24 tests ciblés passent, couvrant notamment le pluriel, le contexte absent ou ambigu, la conservation de la période, les permissions actuelles et l'isolation entre utilisateurs/conversations. Sauvegarde des fichiers précédents : `.migration-review/downtime-followup-before/`.

Après redémarrage contrôlé de Development, les deux phrases exactes ont été soumises depuis Edge dans une même conversation, avec succès `SUCCEEDED / ANSWERABLE`, sans erreur JavaScript ni erreur du moteur IA :

1. `Donne moi la dispo des 789 à SNIM-guelb en YTD?` : 85,77 %, 44 équipements.
2. `Donne moi les top downtimes drivers sur cette période` : périmètre SNIM-Guelb / modèle 789 / YTD conservé ; 44 heures d'arrêt et leur ordre strictement identiques à Excellence Center.

Top 5 vérifié : 789D351 (2 315,20 h), 789D392 (2 213,02 h), 789D379 (1 645,04 h), 789D378 (1 508,87 h), 789D369 (1 488,70 h). Il s'agit de contributeurs par équipement, pas d'un diagnostic des causes.

Preuves : `.migration-review/snim_followup_browser.json`, captures `snim-followup-1.png` et `snim-followup-2.png`. Conversation de test : `fd489538-ef25-4f8a-a681-3e88238a17c6`. Sessions temporaires supprimées. Les journaux du démarrage `20260929-11422*` inspectés ne montrent ni ERROR ni Traceback. Les anciennes réponses restent dans l'historique ; elles ne se réécrivent pas automatiquement.

Cette validation supplémentaire couvre cette relance explicite, sans garantir toutes les questions conversationnelles implicites.

## Réalisé

- Authentification du profil applicatif avec le lanceur existant `deployment/windows/login_chatbot_codex.py`, terminée personnellement par l'utilisateur. Connexion confirmée ; aucune ancienne authentification copiée.
- Reconnaissance de « disponibilités » au pluriel dans le routage des indicateurs.
- Détail par équipement : demande de 100 lignes maximum au lieu de la pagination implicite de 25. La signalisation de troncature reste en place. Les 44 équipements renvoyés pour SNIM-Guelb sont présents.
- Sauvegarde des deux fichiers modifiés sous `.migration-review/snim-fix-before/`. Aucun calcul métier, mapping publié, rôle ou paramètre de sécurité modifié.
- Redémarrage de l'instance Development après vérification de propriété des processus. Aucune action sur Production ou BODEFM.

## Testé

Neuf tests ciblés passent, dont deux régressions nouvelles ; Django system check sans erreur.

Six soumissions réelles depuis Edge, avec une session temporaire du compte existant du dernier audit de connexion réussi, terminent `SUCCEEDED / ANSWERABLE`. Le moteur IA a un thread et un tour actifs, sans code d'erreur. Les réponses sont visibles, sans erreur JavaScript. Les sessions temporaires ont été supprimées ; les conversations de test restent consultables.

| Demande | Résultat vérifié |
| --- | --- |
| Disponibilité SNIM-Guelb YTD | 85,77 % |
| Disponibilité SNIM-Guelb MTD, dates et couverture | 98,81 %, avec réserve explicite sur la couverture |
| Disponibilité SNIM-Guelb en août 2026 | 85,15 % |
| Disponibilité SNIM-Guelb par modèle YTD | Modèle 789 : 85,77 % |
| Disponibilité SNIM-Guelb par équipement YTD | 44 valeurs, tableau non tronqué |
| Disponibilité SNIM-Guelb objectif et fraîcheur YTD | Objectif 75 %, écart +10,77 points ; actualisation et date disponible affichées |

Les preuves conservées par chacun des six runs ont été comparées à l'API Excellence Center avec les mêmes filtres, période et regroupement : contexte identique et égalité exacte des valeurs, y compris les 44 équipements. Ce rapprochement ne constitue pas un recalcul indépendant des mesures sémantiques.

Une seule écoute locale sur 8001 (PID 14140), une sur 443 (PID 28868). Processus serveur, passerelle, worker et leurs lanceurs identifiés comme appartenant au contrôleur. HTTP health OK. Les quatre journaux d'erreur `launcher-20260929-11322*` inspectés ne contiennent ni ERROR ni Traceback.

Preuves locales : `.migration-review/snim_browser_check.json`, `.migration-review/snim-final-check.json`, captures `.migration-review/snim-browser-1.png` à `snim-browser-6.png`. Les scripts de navigateur créent de vraies conversations ; ne pas les relancer comme un contrôle sans effet de bord.

## Non testé

Toutes les formulations libres, les questions de suivi implicites, toutes les périodes, les filtres d'un équipement isolé, les autres sites et les comptes non administrateurs ne sont pas couverts par cette validation. Aucun engagement de couverture exhaustive du chatbot.

## Bloqué

Aucun blocage technique restant pour les six demandes vérifiées. Les limites générales de restauration, Resources, DNS et migrations ne sont pas levées par ce contrôle ciblé.

## Risques

- La source YTD déclare une période du 1er janvier au 30 septembre 2026 et une date disponible au 30 septembre, alors que le contrôle est effectué le 29 septembre. Cette convention de source n'a pas été modifiée ; elle ne prouve pas l'existence d'observations futures.
- Pour le MTD demandé du 1er au 29 septembre, la dernière date disponible annoncée est le 6 septembre. L'actualisation du 29 septembre à 08:51 ne démontre donc pas une couverture quotidienne complète. Le chatbot expose cette limite dans le scénario testé.
- Le bon fonctionnement dépend de la disponibilité du réseau, des sources et de la session applicative. Les chiffres peuvent évoluer après actualisation.

## Prochaine action

Pour la présentation, employer les six formulations validées avec le nom complet SNIM-Guelb, garder la réserve de couverture MTD et consulter les tableaux de preuves. Les conversations de validation sont disponibles dans l'historique du compte testé.
