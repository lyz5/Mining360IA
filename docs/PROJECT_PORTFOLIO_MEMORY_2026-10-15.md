# Portefeuille de projets — mémoire de travail

Dernière consolidation : **15 octobre 2026**.

Ce document donne la vue commune des six projets suivis avec Papa Djibril Diagne. Il sert de point de reprise avant une demande qui peut concerner plusieurs applications. Il ne remplace pas les mémoires techniques propres à chaque projet et ne constitue pas une autorisation de déploiement.

## 1. Vue d'ensemble

| Projet | Finalité | Référence locale canonique | Environnement distant connu | État observé |
| --- | --- | --- | --- | --- |
| Mining 360 | Plateforme intégrée de visibilité opérationnelle et commerciale minière | `C:\Users\diagnepa\Documents\MBA\Mining360IA` | BODEFM, entrée `https://bodefm/mining360` | Local actif ; BODEFM exploité avec procédures protégées |
| MiningProd | Application opérationnelle historique, browsers, formulaires, tables et vues | Documentation, scripts et preuves dans le dépôt Mining 360 | Production `/Miningprod` et clone isolé `/Miningprod_test` sur `172.17.0.111` | Clone de test actif ; production protégée |
| Mayite | Application métier de référence pharmaceutique et de gestion des professionnels/abonnements | `C:\Users\diagnepa\Documents\Personal Projects\Mayite` | PythonAnywhere ; `https://equivalence.mayite-service.com` | Copie locale active ; source de production sauvegardée sur branche dédiée |
| DSTV | Gestion de clients, abonnements, renouvellements, facturation et analyses Canal+/DSTV | `C:\Users\diagnepa\Documents\Personal Projects\Dstv` | PythonAnywhere ; `https://dstvsenegal.pacdigitale.com` | Copie locale active ; source de production sauvegardée sur branche dédiée |
| Site web Pacdigitale | Site vitrine et génération de contacts de Pac Digitale | `C:\Users\diagnepa\Documents\Personal Projects\Website` | WordPress sur LWS ; `https://www.pacdigitale.com` | Dépôt `main` propre ; copie locale active |
| Mémoire Executive MBA | Recherche appliquée sur Mining 360, performance opérationnelle et croissance commerciale | Dossier MBA et livrables dans `exports/Memoire_MBA_Validation_2026-10-11` | Soumission académique à venir | Proposition de validation produite en 15 pages ; terrain et protocole à confirmer |

Les six projets sont comptés séparément. `Miningprod_test` est l'environnement de test de MiningProd et non un septième projet.

### Tableau de pilotage actuel

| Projet | Dernier état de travail connu | Prochaine décision utile |
| --- | --- | --- |
| Mining 360 | Fuel réparé sur BODEFM ; Operating Hours, UX premium Chatbot et retrait du bouton Watchlist validés localement selon leurs périmètres respectifs | Autoriser séparément les déploiements BODEFM souhaités, puis vérifier parité, sécurité et performance |
| MiningProd | Clone isolé opérationnel ; UI test modernisée ; browser CAT Price enrichi et tarif S2 2026 intégré | Continuer les changements dans le clone, mesurer CAT Price et valider toute promotion vers la production |
| Mayite | Source PythonAnywhere sauvegardée ; exécution locale confirmée | Définir la prochaine évolution fonctionnelle et décider comment réconcilier la branche sauvegardée avec `main` |
| DSTV | Source PythonAnywhere sauvegardée ; exécution locale confirmée | Définir la prochaine évolution et auditer les routes de mutation avant modernisation |
| Site Pacdigitale | Thème personnalisé versionné ; dépôt propre ; copie locale active | Confirmer les prochains contenus ou évolutions et la configuration SMTP avant de compter sur les contacts |
| Mémoire MBA | Proposition de validation de 15 pages terminée ; revue comparative des anciens mémoires disponible | Faire valider sujet/problématique, choisir le terrain, les données et les interlocuteurs |

### Modèle d'environnement adopté le 15 octobre 2026

Le développement et les tests de toutes les applications doivent s'effectuer sur ce poste avant promotion. Mayite, DSTV et Pacdigitale disposent déjà de leurs environnements locaux. Mining 360 doit recevoir SQL Server 2022 Developer local pour reproduire la major version BODEFM, et Miningprod_test doit être transféré dans un IIS/SQL Server local isolé. Le mémoire MBA reste un flux documentaire et ne nécessite pas de runtime.

Références :

- `docs/LOCAL_FIRST_DEVELOPMENT_STANDARD_2026-10-15.md` ;
- `docs/MINING360_MININGPROD_LOCAL_PLATFORM_PLAN_2026-10-15.md` ;
- `docs/DEV_MACHINE_CONTINUITY_RUNBOOK_2026-10-15.md`.

## 2. Relations entre les projets

```text
MiningProd ── source opérationnelle et référentiels ──> Mining 360
Mining 360 ── cas d'étude, données et modèle de valeur ──> Mémoire Executive MBA

Pac Digitale ── portefeuille numérique ──> Site Pacdigitale
                                      ├──> Mayite
                                      └──> DSTV
```

- MiningProd et Mining 360 restent deux applications distinctes. MiningProd ne doit pas devenir la base applicative Django de Mining 360.
- Le mémoire utilise Mining 360 comme cas de recherche appliquée. Une fonctionnalité, une mesure technique ou une roadmap ne devient pas une preuve académique de résultat sans données validées.
- Mayite, DSTV et le site Pacdigitale ont chacun leur propre dépôt Git, leur propre runtime et leur propre procédure de déploiement.

## 3. Mining 360

### Rôle et périmètre

Mining 360 est une application Django de pilotage minier organisée autour de cinq espaces métier à mettre en valeur :

1. Business Overview ;
2. Excellence Center ;
3. Reporting ;
4. M360 Chatbot ;
5. Ressources.

Elle consolide des données opérationnelles, techniques, de maintenance et commerciales. Mining360 AI historique et M360 Chatbot sont des produits séparés et doivent conserver leurs routes distinctes.

### Architecture et environnements

- Code local : dépôt de travail courant, sans métadonnées Git actives dans cette copie.
- Local : Django, base SQLite `db.sqlite3`, URL de santé vérifiée le 15 octobre 2026 sur `http://127.0.0.1:8001/health/` avec HTTP 200.
- BODEFM : Django/Waitress, base applicative SQL Server `Mining360App`, runtime et rollback gouvernés.
- MiningProd reste une source externe ; ne jamais remplacer `Mining360App` par la base `MiningProd`.

### État fonctionnel à retenir

- Business Overview : Revenue gouverné, Mining par défaut, All Divisions explicite, MTD/YTD bornés à aujourd'hui, détails Machines et Pièces Mining-only, Back Orders relié au Mine Logistics Report, onglet GET/UC Opportunities présent sans données gouvernées confirmées.
- Performance BODEFM : index filtré actif et maintenance ciblée des statistiques à préserver. Les références historiques sont 1,204 s pour le cœur sans cache et 3,674 s pour une ouverture navigateur initiale ; ce sont des observations.
- Excellence Center : Availability, MTBF, MTBS, MTTR, Fuel, Connectivity et Top Downtime Drivers selon les capacités documentées. `Operating Hours` a été ajouté et validé localement le 14 octobre 2026, sans déploiement BODEFM à cette date.
- Fuel Consumption : fichier de référence rétabli et valeur BODEFM vérifiée le 14 octobre 2026 ; préserver la source et les unités retournées.
- M360 Chatbot : présentation premium et résolution du périmètre KPI validées localement le 14 octobre 2026 ; le périmètre analytique chiffré reste limité aux KPI Excellence Center documentés. Déploiement BODEFM non présumé.
- Customer 360 : le bouton `Add to Watchlist` a été retiré localement le 14 octobre 2026 dans les trois variantes frontales ; aucun déploiement BODEFM n'est présumé.

### Protections

- Ne jamais modifier les calculs Revenue, le Published Mapping, les permissions/RLS ou la précision monétaire sans contrôle de parité.
- Ne jamais exposer les secrets chiffrés ni les fichiers de configuration locaux.
- Ne jamais déployer sur BODEFM sans autorisation explicite.
- Avant un changement Business Overview, lire le guide BODEFM et les mémoires de performance indiqués dans `AGENTS.md`.

### Sources de reprise principales

- `docs/MINING360_HANDOFF_2026-09-18.md`
- `docs/BUSINESS_OVERVIEW_BODEFM_GUIDE_2026-10-10.md`
- `docs/M360_CHATBOT_BUSINESS_OVERVIEW_2026-10-10.md`
- `docs/M360_CHATBOT_PREMIUM_ANSWERS_2026-10-14.md`
- `docs/RESOURCE_DOCUMENT_MEMORY_2026-09-24.md`

## 4. MiningProd

### Rôle et périmètre

MiningProd est une application WebForms/ASP.NET historique, pilotée par métadonnées, formulaires et browsers. Son modèle comprend des tables, vues, triggers, attributs et configurations de formulaires. Il ne faut pas assimiler un browser à une table unique ni une colonne affichée à une suppression physique de données.

### Environnements

- Production : application IIS `/Miningprod`, chemin documenté `C:\inetpub\wwwroot\Miningprod`, base `MiningProd`.
- Test : `http://172.17.0.111/Miningprod_test/`, application `D:\Miningprod_test\app`, pool IIS dédié `Miningprod_test`, base isolée `Miningprod_test`.
- Le clone est un snapshot et ne se synchronise pas automatiquement avec la production.
- L'identité SQL du test est dédiée, non sysadmin, sans accès à la base de production.

### État vérifié

- Architecture du clone : 449 formulaires, 8 995 définitions de colonnes, 340 tables utilisateur non système, 385 vues et 555 triggers inventoriés en lecture seule. Cet inventaire ne prouve pas le fonctionnement exhaustif de tous les formulaires.
- Sites : MetaFormID `2405988`.
- Equipment Browser : MetaFormID `45`.
- CAT - Part List Price : MetaFormID `2406027`, distinct de Neemba PCR `2406025`.
- CAT Price S2 2026 : 1 158 000 lignes source intégrées ; contrôle enregistré avec zéro référence manquante, zéro écart sur les quatre valeurs associées et zéro doublon. Le total de la table après conservation des anciennes références est 1 158 293.
- Les colonnes Major Class, Minor Class et PPC sont créées comme attributs texte et rattachées au browser. La devise de `DN $` et la précision métier de DealerNet restent à confirmer.
- Le clone possède une page d'accueil et une connexion modernisées, ainsi que le branding Neemba documenté.

### Risques et règles

- Une définition globale Major Class supplémentaire a été créée lors de l'intervention historique. Ne pas la supprimer sans audit de dépendances.
- `Load All Records=-1` sur CAT Price et un temps d'ouverture observé autour de 52 secondes demandent une analyse dédiée avant optimisation.
- Les scripts de renommage, création de colonnes et import sont des mutations historiques ; ne pas les relancer comme tests.
- Tester d'abord dans `Miningprod_test`. Toute action en production MiningProd exige une demande explicite, une sauvegarde et un retour arrière ciblé.

### Sources de reprise principales

- `docs/MININGPROD_BROWSER_WORKING_MEMORY.md`
- `docs/MININGPROD_ARCHITECTURE_REVIEW_2026-10-12.json`
- `docs/MININGPROD_TEST_2026-10-12.json`
- `docs/MININGPROD_CAT_PRICE_IMPORT_2026-10-12.md`
- `docs/MININGPROD_SITES_ACCESS_2026-10-11.md`

## 5. Mayite

### Rôle et périmètre vérifié

Mayite est une application Django orientée professionnels de santé et référentiel pharmaceutique. Les routes présentes couvrent notamment les professionnels, étudiants, structures, DCI, médicaments, classes, propriétés, laboratoires, abonnements, annexes documentaires, paiement PayDunya et API.

### Code et environnements

- Dépôt : `https://github.com/lyz5/MayiteService.git`.
- Copie canonique locale : `C:\Users\diagnepa\Documents\Personal Projects\Mayite`.
- Branche locale : `backup/pythonanywhere-20261012`, liée à la branche distante du même nom.
- Dernier commit observé : `9cc6f62`, sauvegarde de la source PythonAnywhere du 12 octobre 2026.
- Production documentée : `/home/djimen10/mayiteservice` sur PythonAnywhere ; domaine `equivalence.mayite-service.com`.
- Local : `http://127.0.0.1:8012/`, HTTP 200 vérifié le 15 octobre 2026, MySQL local `Mayite`.

### État de travail

- Le code de production a été sauvegardé sans données, médias, caches ni secrets.
- Le projet repose historiquement sur Django 2.0.1 ; l'environnement local de compatibilité utilise Django 2.2.28 et des dépendances adaptées.
- Des fichiers locaux de démarrage et des overrides sont présents mais non commités. `config/settings/base.py` et `v2/urls.py` ont aussi des modifications locales à examiner avant tout commit.
- Les médias de production ne sont pas restaurés localement.
- La page publique de connexion est indexée et accessible à l'outil web ; cela ne remplace pas un test authentifié ni un audit de bout en bout.

### Discipline

- Préserver les variables d'environnement pour secret Django, base, paiement et messagerie.
- Comparer la branche de sauvegarde à `main` avant toute fusion : la documentation signale que le code déployé est plus ancien que GitHub `main`.
- Ne pas appliquer de migration, envoyer de courriel réel, déclencher un paiement ou déployer sur PythonAnywhere sans demande explicite.

## 6. DSTV

### Rôle et périmètre vérifié

DSTV est une application Django de gestion commerciale et opérationnelle des abonnements Canal+/DSTV. Les routes présentes couvrent clients, formules, options, matériels, services, renouvellements, factures, journaux, analyses, utilisateurs et API mobiles/métier.

### Code et environnements

- Dépôt : `https://github.com/lyz5/DstvApp.git`.
- Copie canonique locale : `C:\Users\diagnepa\Documents\Personal Projects\Dstv`.
- Branche locale : `backup/pythonanywhere-20261012`, liée à la branche distante du même nom.
- Dernier commit observé : `0beb435`, sauvegarde de la source PythonAnywhere du 12 octobre 2026.
- Production documentée : `/home/djimen10/dstv` sur PythonAnywhere ; domaine `dstvsenegal.pacdigitale.com`.
- Local : `http://127.0.0.1:8011/`, redirection vers `/login/` puis HTTP 200 vérifiée le 15 octobre 2026, MySQL local `DSTV`.

### État de travail

- La base du projet est ancienne et indique une génération Django 1.10 ; l'environnement local de compatibilité utilise Django 2.2.28.
- La source de production est sauvegardée sans données, médias, caches ni secrets.
- `dstv/settings.py` est modifié localement ; les fichiers de démarrage et `dstv/local_overrides.py` sont non commités.
- Le domaine public n'a pas pu être consulté par l'outil web lors de la consolidation. Cela ne prouve pas une panne.

### Discipline

- Vérifier les droits et protections des nombreuses routes de mutation avant toute modernisation fonctionnelle.
- Préserver les secrets Django, MySQL et tokens API hors Git.
- Ne pas lancer d'opération de facturation, de renouvellement, de correction globale ou de déploiement PythonAnywhere sans demande explicite.

## 7. Site web Pacdigitale

### Rôle et architecture

Le site public Pacdigitale est un WordPress hébergé chez LWS. Le code versionné est limité au thème personnalisé `pacdigitale-2026`. WordPress core, plugins, uploads, base et configurations locales/production sont exclus du dépôt.

### Code et environnements

- Dépôt : `https://github.com/lyz5/pacdigitalewebsite.git`.
- Copie canonique locale : `C:\Users\diagnepa\Documents\Personal Projects\Website`.
- Branche : `main`, propre au contrôle du 15 octobre 2026.
- Dernier commit observé : `0aa15de`, documentation du guide d'implémentation du 14 octobre 2026.
- Local : `http://127.0.0.1:8020/`, HTTP 200 vérifié le 15 octobre 2026.
- Production : `https://www.pacdigitale.com/`. Le contrôle automatisé rencontre la protection DDoS LWS ; cela ne prouve pas une indisponibilité utilisateur.

### État fonctionnel

- Page unique : hero, chiffres clés, défis/solutions, six expertises, démarche en quatre étapes, partenaires et contact.
- Le formulaire valide et assainit les entrées puis utilise `wp_mail()` vers `admin_email`.
- Les messages du formulaire ne sont pas stockés en base. Un SMTP fiable doit être configuré avant de considérer la livraison des contacts comme garantie.
- Les modifications doivent rester dans `wp-content/themes/pacdigitale-2026/` sauf demande explicite plus large.

### Discipline

- Lire `docs/IMPLEMENTATION.md` du dépôt Website avant modification.
- Tester PHP, desktop, mobile, navigation, carrousel et formulaire.
- Ne jamais publier `wp-config.php`, un dump, les uploads ou des fichiers d'accès.
- Le déploiement LWS/FTPS et l'activation de thème exigent une autorisation explicite.

## 8. Mémoire Executive MBA

### Sujet et contribution attendue

**Mining 360 : levier de performance opérationnelle et de croissance commerciale**.

Question centrale : comment Mining 360 peut-il transformer les données opérationnelles et commerciales en décisions et actions mesurables permettant d'améliorer simultanément la performance des exploitants miniers et la croissance commerciale de Neemba ?

La contribution visée est un modèle intégré allant des données aux actions, puis aux résultats client et aux résultats commerciaux de Neemba. Les capacités opérationnelles, les développements en cours et la roadmap IA doivent rester clairement séparés.

### Livrables et état

- Dossier de validation V2 Word et PDF produit le 11 octobre 2026.
- Pagination contrôlée : 15 pages, 14 sauts explicites, 17 notes, 5 schémas originaux, aucun débordement détecté.
- Sources et points à confirmer documentés dans le même dossier d'export.
- Trois archives d'anciens mémoires EMBA 2019, 2021 et 2022 inventoriées : 98 fichiers, 41 documents principaux, revue analytique ciblée. Cette revue n'est pas une lecture exhaustive de chaque page.
- Soutenance prévue en décembre 2026 ; date exacte à confirmer.

### Décisions encore nécessaires

1. Valider les exigences académiques, le directeur et la date de dépôt/soutenance.
2. Choisir le terrain ou les cas opérationnels selon l'accès et la qualité des données.
3. Définir la traçabilité Insight → recommandation → action → résultat → opportunité/commande/facture.
4. Valider définitions KPI, coûts, marges et méthode d'attribution avec les métiers et Finance.
5. Confirmer gouvernance, confidentialité, personnes à interviewer et faisabilité du pilote IA.

### Sources de reprise principales

- `exports/Memoire_MBA_Validation_2026-10-11/Mining360_Validation_Sujet_Memoire_v2.docx`
- `exports/Memoire_MBA_Validation_2026-10-11/Mining360_Validation_Sujet_Memoire_v2.pdf`
- `exports/Memoire_MBA_Validation_2026-10-11/Mining360_Sources_Utilisees.md`
- `exports/Memoire_MBA_Validation_2026-10-11/Mining360_Points_A_Confirmer.md`
- `docs/EMBA_ARCHIVES_REVIEW_MEMORY_2026-10-12.json`

## 9. Règles communes de conduite

Avant toute intervention :

1. identifier le projet et le dépôt canonique ;
2. lire sa mémoire et ses instructions locales ;
3. contrôler la branche, les changements non commités et l'environnement ciblé ;
4. séparer lecture, modification locale, migration de données et déploiement ;
5. préparer validation et retour arrière avant toute action distante ;
6. ne jamais afficher ni copier de secret ;
7. ne jamais présenter une donnée ancienne, une maquette ou une roadmap comme un état actuel ;
8. conserver les preuves utiles sans données personnelles ou confidentielles.

### Autorisations de déploiement distinctes

Une autorisation donnée pour un projet ou un environnement ne vaut pas pour les autres :

- Mining 360 BODEFM ;
- MiningProd production ;
- Miningprod_test ;
- Mayite PythonAnywhere ;
- DSTV PythonAnywhere ;
- Pacdigitale LWS ;
- soumission ou transmission du mémoire MBA.

## 10. Prochain cycle de consolidation

À chaque changement important, mettre à jour d'abord la mémoire propre au projet, puis ce portefeuille uniquement si l'un des éléments suivants change : dépôt canonique, environnement, objectif, dépendance, statut de déploiement, risque majeur ou prochaine décision.

Les informations encore non vérifiées doivent rester marquées **À confirmer** plutôt que déduites d'un nom de fichier, d'une URL ou d'une fonctionnalité prévue.
