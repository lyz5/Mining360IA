# PROMPT MAITRE - MINING 360 CONTROL CENTER V2

## Contexte

Je veux faire évoluer l'application Windows **Mining 360 Control Center** en un centre de pilotage moderne, premium et complet pour les services techniques de Mining360.

Le Control Center est distinct du **Business Command Center**. Il ne présente pas des indicateurs de chiffre d'affaires. Il sert à démarrer, arrêter, redémarrer, surveiller et diagnostiquer les composants techniques nécessaires au fonctionnement de Mining360.

Cette évolution doit préserver les règles de sécurité existantes. Aucun changement LDAP, certificat, pare-feu, compte de service, secret, déploiement de production ou arrêt d'un processus non identifié ne doit être réalisé automatiquement sans validation explicite.

---

## 1. Etat actuel vérifié dans le code

### Fichiers principaux

- `desktop/control_center.py` : interface Windows Tkinter.
- `desktop/control_core.py` : démarrage, arrêt et contrôles de santé.
- `desktop/test_control_core.py` : tests unitaires du contrôleur.
- `deployment/windows/start_mining360_dev.ps1` : lancement de l'environnement de développement.
- `deployment/windows/https_reverse_proxy.py` : passerelle HTTPS locale.
- `deployment/windows/restart_mining360_dev_runtime.ps1` : redémarrage isolé de Waitress sur le port 8001, non intégré à l'interface actuelle.
- `deployment/windows/start_mining360.ps1` : runtime serveur géré par Waitress.
- `deployment/services/system_doctor.py` : diagnostic local et distant plus complet, actuellement séparé du Control Center desktop.

### Ce que fait réellement le Control Center actuel

L'interface propose quatre commandes :

- **Démarrer** : exécute `start_mining360_dev.ps1` en arrière-plan.
- **Arrêter** : recherche les PID écoutant sur les ports 443 et 8001, vérifie qu'ils appartiennent à Mining360, puis termine leur arbre de processus.
- **Ouvrir** : ouvre `https://mining360-dev.neemba.local` dans le navigateur.
- **Actualiser** : relance les contrôles locaux et externes.

Le script de démarrage lance trois composants :

1. Django via Waitress sur `127.0.0.1:8001` avec huit threads ;
2. le worker Codex via `manage.py run_codex_worker --poll-seconds 0.5` ;
3. la passerelle HTTPS sur le port 443.

### Contrôles actuellement visibles

| Contrôle | Méthode actuelle | Limite actuelle |
|---|---|---|
| Processus Mining 360 | Détection d'un PID Mining360 sur le port 8001 | Ne représente pas tous les processus lancés |
| Passerelle HTTPS | Requête sur `<URL publique>/health/` | Pas de diagnostic distinct du certificat, du DNS et du proxy |
| Django / Waitress | Requête sur `http://127.0.0.1:8001/health/` | Ne mesure pas la saturation, les threads ni le temps de réponse |
| Base de données | Valeur `database` retournée par `/health/` | Le health check exécute uniquement `SELECT 1` |
| Active Directory | Connexion LDAP technique | Ne montre pas la validité détaillée de la chaîne LDAPS |
| Power BI API | Acquisition d'un jeton | Ne valide pas les datasets, rapports ou dernières actualisations |

### Fréquence des contrôles

- services locaux : toutes les 4 secondes ;
- Active Directory et Power BI : toutes les 30 secondes.

### Sécurité déjà présente

- les contrôles sont exécutés hors du thread graphique ;
- les mots de passe, secrets et tokens reconnus sont masqués dans les messages ;
- un PID n'est arrêté que si sa ligne de commande correspond au dépôt ou à un marqueur Mining360 connu ;
- un processus inconnu occupant un port Mining360 n'est pas tué ;
- les logs du lanceur sont conservés dans `.runlogs/desktop-control`.

### Lecture de la capture actuelle

La capture montre un état global **Attention** parce que :

- aucun processus Mining360 n'est détecté ;
- la passerelle HTTPS refuse la connexion avec `WinError 10061` ;
- Django / Waitress refuse aussi la connexion ;
- le contrôle de base de données reste en attente, car il dépend du health check Django ;
- Active Directory est joignable ;
- l'authentification Power BI réussit.

Cela signifie que les dépendances externes testées sont disponibles, mais que le runtime Web local n'est pas démarré ou n'écoute pas sur les ports attendus.

---

## 2. Ce qui manque actuellement

Le Control Center ne donne pas une vision complète des services réellement nécessaires à Mining360.

### Services lancés mais non suivis individuellement

- worker Codex Chatbot ;
- état d'authentification Codex et capacité à traiter une requête ;
- processus exact de la passerelle HTTPS ;
- distinction entre processus lanceur, Waitress et proxy HTTPS.

### Services ou fonctions présents dans le projet mais absents du Control Center

- tâche planifiée serveur `Mining360TestRuntime` ;
- tâche `Mining360DeploymentWorker` ;
- état du worker de déploiement et des déploiements en attente ;
- migrations Django en attente ;
- fichiers statiques collectés ;
- manifeste de la release active ;
- erreurs runtime récentes ;
- chaîne de certificats LDAPS ;
- expiration et validité du certificat HTTPS ;
- configuration et état des intégrations actives ;
- synchronisation Business Mapping et son dernier résultat ;
- synchronisation Invoice Tracking / Reconciliation et son dernier résultat ;
- fraîcheur des snapshots Revenue, Fleet, Machine Sales et Parts Sales ;
- état des sources SQL Server, Snowflake et modèles sémantiques lorsqu'elles sont configurées ;
- espace disque des répertoires de logs, médias, fichiers statiques et releases ;
- consommation mémoire et CPU des processus Mining360 ;
- files de travaux et workers bloqués ;
- visibilité claire de l'environnement contrôlé : local, développement, test BODEFM ou production.

Toutes ces capacités ne doivent pas être déclarées opérationnelles par simple présence d'une configuration. Chaque contrôle doit avoir une preuve mesurable et un délai d'expiration.

---

## 3. Objectif du Control Center V2

Le V2 doit permettre à un administrateur autorisé de répondre en moins de dix secondes aux questions suivantes :

- Mining360 est-il réellement utilisable ?
- Quel composant est indisponible ou dégradé ?
- Le problème vient-il du runtime, de la base, de l'identité, d'une source de données ou d'un worker ?
- Quelle est la dernière preuve de bon fonctionnement ?
- Puis-je démarrer, arrêter ou redémarrer l'application sans toucher à un autre service Windows ?
- Quelle action sûre est recommandée ?
- Où puis-je consulter les logs utiles ?

---

## 4. Commandes requises

La barre d'actions principale doit contenir :

- **Démarrer** ;
- **Arrêter** ;
- **Redémarrer** ;
- **Ouvrir Mining360** ;
- **Actualiser** ;
- **Diagnostics** ;
- **Journaux**.

Les boutons doivent refléter l'état réel :

- désactiver `Démarrer` lorsque tous les composants requis sont opérationnels ;
- désactiver `Arrêter` lorsque Mining360 est déjà arrêté ;
- autoriser `Redémarrer` lorsqu'au moins un composant géré fonctionne ou reste bloqué ;
- empêcher les doubles clics et les opérations concurrentes ;
- afficher une progression et l'étape courante.

---

## 5. Redémarrage contrôlé

Le bouton **Redémarrer** ne doit pas être une succession aveugle de `Arrêter` puis `Démarrer`.

Il doit exécuter une machine d'état contrôlée :

1. acquérir un verrou d'opération ;
2. enregistrer l'utilisateur, l'environnement et l'heure ;
3. effectuer un précontrôle et identifier précisément les processus gérés ;
4. arrêter proprement les composants dans l'ordre inverse de dépendance ;
5. attendre la libération des ports 443 et 8001 ;
6. utiliser une terminaison forcée uniquement après délai, et seulement pour un PID dont la propriété Mining360 est prouvée ;
7. fermer les anciens handles de logs ;
8. démarrer Waitress, le worker Codex et la passerelle HTTPS dans l'ordre prévu ;
9. attendre le health check local Django ;
10. attendre le health check HTTPS public ;
11. vérifier la base et les workers essentiels ;
12. afficher `Opérationnel`, `Dégradé` ou `Échec` avec les preuves ;
13. conserver les logs complets et une synthèse expurgée des secrets.

Etats de progression contrôlés :

- Préparation ;
- Arrêt en cours ;
- Attente de libération des ports ;
- Démarrage du runtime ;
- Démarrage des workers ;
- Démarrage HTTPS ;
- Vérification de santé ;
- Terminé ;
- Terminé avec avertissements ;
- Échec.

Le redémarrage doit être idempotent. Une erreur sur un composant secondaire ne doit pas masquer l'état des composants qui fonctionnent.

---

## 6. Modèle de santé des services

Utiliser des états explicites :

- Opérationnel ;
- Dégradé ;
- Démarrage ;
- Arrêt ;
- Redémarrage ;
- Indisponible ;
- Non configuré ;
- Inconnu ;
- Contrôle expiré.

Ne pas communiquer l'état uniquement par couleur.

Chaque contrôle doit exposer :

- nom fonctionnel ;
- catégorie ;
- état ;
- résumé métier ;
- dernière vérification ;
- durée du contrôle ;
- dépendances ;
- preuve technique masquée ;
- action recommandée ;
- lien vers les logs filtrés.

Différencier obligatoirement :

- **Processus actif** : le processus existe ;
- **Connectivité** : le port ou le service répond ;
- **Readiness** : le composant est prêt à traiter une demande ;
- **Fraîcheur des données** : la dernière donnée est suffisamment récente.

Un processus actif n'est pas automatiquement un service opérationnel.

---

## 7. Inventaire cible des contrôles

### Runtime

- Processus principal Mining360 ;
- Django / Waitress ;
- passerelle HTTPS ;
- certificat HTTPS ;
- base de données applicative ;
- migrations ;
- fichiers statiques ;
- mémoire, CPU et temps de fonctionnement ;
- endpoint de santé et temps de réponse.

### Identité et sécurité

- Active Directory / LDAPS ;
- chaîne CA LDAPS ;
- expiration des certificats ;
- configuration des hôtes autorisés, sans afficher les secrets ;
- présence des secrets requis, jamais leur valeur.

### IA et traitements

- Power BI API ;
- Codex worker ;
- fournisseur Codex configuré ;
- ancien Mining360 AI, séparé et inchangé ;
- files de tâches et âge du plus ancien travail ;
- dernier succès et dernière erreur de chaque worker.

### Données

- SQL Server applicatif ;
- sources NMBEPM et Snowflake uniquement lorsqu'elles sont configurées ;
- dernier snapshot Revenue ;
- dernier snapshot Fleet ;
- dernière synchronisation Business Mapping ;
- dernière publication de Mapping ;
- dernière synchronisation Invoice Tracking ;
- détails Machine Sales ;
- détails Parts Sales ;
- avertissements de fraîcheur.

### Déploiement

- environnement sélectionné ;
- release active ;
- tâche runtime ;
- worker de déploiement ;
- déploiement en cours ou en attente ;
- dernier déploiement ;
- disponibilité du rollback ;
- erreurs runtime récentes.

Les contrôles doivent être activés selon l'environnement. Par exemple, les tâches planifiées BODEFM ne doivent pas être présentées comme manquantes dans un simple environnement local qui ne les utilise pas.

---

## 8. Architecture visuelle premium

Le V2 doit être une application d'exploitation calme, dense et lisible, pas une collection de grandes cartes décoratives.

### En-tête compact

Afficher :

- logo Mining360 ;
- `Mining 360 Control Center` ;
- environnement actif ;
- statut global ;
- dernière vérification ;
- menu utilisateur ou niveau d'autorisation.

### Bandeau de commande

Afficher les actions principales sur une seule ligne, avec icônes reconnues, libellés courts, info-bulles et états désactivés cohérents.

`Redémarrer` devient une commande principale clairement identifiable, mais nécessite une confirmation précisant l'environnement et les composants concernés.

### Vue principale

Utiliser deux zones :

- à gauche, une liste compacte des services groupés par catégorie ;
- à droite, le détail du service sélectionné, ses dépendances, ses mesures, son historique et ses actions sûres.

Ajouter en haut une synthèse compacte :

- Disponibilité globale ;
- Services opérationnels ;
- Services dégradés ;
- Incidents ;
- Travaux en attente ;
- Dernière actualisation.

### Navigation locale

- Vue d'ensemble ;
- Services ;
- Données & Intégrations ;
- Travaux ;
- Déploiement ;
- Journaux & Historique.

### Principes graphiques

- fond gris très clair ;
- surfaces blanches structurées ;
- en-tête navy Mining360 ;
- jaune Mining360 réservé aux actions et sélections ;
- vert, orange et rouge utilisés uniquement pour le statut ;
- bordures discrètes ;
- rayon maximal de 8 px ;
- aucune lueur, aucun effet 3D, aucune grande zone décorative ;
- typographie Segoe UI cohérente ;
- texte technique long placé dans un panneau de détail avec copie ;
- dimensions stables pendant les actualisations.

### Retours d'opération

Pendant un démarrage, arrêt ou redémarrage :

- afficher une barre de progression déterminée par étapes ;
- afficher l'étape courante ;
- conserver l'interface consultable ;
- permettre l'ouverture des logs ;
- ne pas figer la fenêtre ;
- afficher une synthèse finale claire ;
- permettre de copier le diagnostic.

---

## 9. Architecture technique proposée

Séparer strictement :

- `ServiceRegistry` : inventaire déclaratif par environnement ;
- `HealthCheckRunner` : exécution parallèle avec timeout ;
- `ServiceLifecycleManager` : start, stop, restart et ownership des PID ;
- `OperationCoordinator` : verrou, étapes, progression et annulation sûre ;
- `DiagnosticsAggregator` : fusion des contrôles desktop et System Doctor ;
- `EventStore` : historique local/audité des opérations ;
- `SecretRedactor` : nettoyage centralisé de tous les messages ;
- `ControlCenterViewModel` : état de l'interface sans logique système ;
- interface graphique premium.

Ne pas dupliquer les contrôles déjà fiables de `DeploymentSystemDoctorService`. Les adapter derrière une interface commune quand le contexte Django est disponible.

Ne pas appeler un endpoint coûteux toutes les quatre secondes. Prévoir trois cadences :

- processus et ports locaux : 3 à 5 secondes ;
- santé applicative : 10 à 15 secondes ;
- intégrations externes et fraîcheur des données : 30 à 120 secondes.

Annuler ou ignorer les résultats obsolètes lorsque l'utilisateur relance un contrôle.

---

## 10. Sécurité non négociable

- ne jamais stocker ou afficher un mot de passe, token, secret ou chaîne de connexion complète ;
- ne jamais modifier automatiquement LDAP ou ses certificats ;
- ne jamais désactiver la validation TLS ;
- ne jamais tuer un processus sur la seule base d'un numéro de port ;
- vérifier le chemin, la ligne de commande, le parent et si possible un manifeste PID signé par le lanceur ;
- distinguer environnement local, test et production ;
- exiger une confirmation renforcée pour production ;
- appliquer le moindre privilège ;
- journaliser les opérations administratives ;
- ne pas transformer un avertissement en succès ;
- ne pas afficher `0 incident` si le contrôle n'a pas été exécuté ;
- ne réaliser aucun déploiement depuis le Control Center V2 sans permission et workflow de déploiement existant.

---

## 11. Tests requis

### Tests fonctionnels

- démarrage complet depuis un état arrêté ;
- démarrage lorsque l'application fonctionne déjà ;
- arrêt complet ;
- arrêt face à un PID inconnu sur le port ;
- redémarrage sain ;
- redémarrage après panne Waitress ;
- redémarrage après panne HTTPS ;
- worker Codex absent ;
- base indisponible ;
- Active Directory indisponible ;
- Power BI indisponible ;
- timeout d'un contrôle externe ;
- double clic sur une commande ;
- fermeture du Control Center pendant une vérification ;
- secrets présents dans une exception ;
- environnement local sans tâches planifiées serveur.

### Tests de sécurité

- refus de tuer un processus non Mining360 ;
- redaction des secrets dans l'UI et les logs ;
- contrôle des permissions administratives ;
- confirmation de l'environnement ;
- absence de modification LDAP/TLS ;
- absence d'exposition des chaînes de connexion.

### Tests UX

- aucune interface figée ;
- progression visible ;
- focus clavier visible ;
- navigation clavier complète ;
- statut compréhensible sans couleur ;
- texte lisible à 200 % de zoom ;
- fenêtre utilisable à 1280 x 720 et 1920 x 1080 ;
- aucun texte tronqué ;
- journal consultable et copiable.

---

## 12. Plan d'implémentation recommandé

### Phase 1 - Stabilisation du coeur

- créer le registre de services ;
- séparer processus, connectivité, readiness et fraîcheur ;
- ajouter le contrôle explicite du worker Codex ;
- implémenter le redémarrage orchestré ;
- compléter les tests du cycle de vie ;
- conserver l'interface actuelle comme repli temporaire.

### Phase 2 - Couverture complète

- intégrer les contrôles pertinents du System Doctor ;
- ajouter runtime, déploiement, workers, certificats et fraîcheur des données ;
- rendre l'inventaire dépendant de l'environnement ;
- ajouter l'historique des opérations.

### Phase 3 - Interface premium

- créer l'en-tête et le bandeau de commande compacts ;
- créer la liste de services et le panneau de détail ;
- ajouter progression, filtres, recherche et états dégradés ;
- moderniser les journaux ;
- vérifier l'accessibilité.

### Phase 4 - Validation

- tests unitaires et d'intégration ;
- tests sur machine locale ;
- tests sur BODEFM sans modification de sécurité ;
- captures avant/après ;
- mesure du démarrage et des contrôles ;
- procédure de rollback.

---

## 13. Critères d'acceptation

Le Control Center V2 est terminé lorsque :

- tous les composants lancés sont surveillés individuellement ;
- les services critiques configurés sont visibles ;
- `Redémarrer` fonctionne avec progression et contrôle final ;
- aucun processus inconnu ne peut être arrêté ;
- l'état global est calculé à partir des services requis pour l'environnement actif ;
- les contrôles expirés ne restent pas verts ;
- les pannes partielles sont clairement isolées ;
- le worker Codex est visible séparément ;
- les tâches runtime et déploiement sont visibles sur BODEFM ;
- la fraîcheur des principales données est consultable ;
- les diagnostics détaillés restent accessibles sans surcharger l'écran ;
- l'interface reste fluide pendant les opérations ;
- les secrets sont masqués partout ;
- tous les tests de cycle de vie et de sécurité passent ;
- l'ancien Control Center reste disponible pendant le pilote comme rollback.

---

## 14. Consigne à ChatGPT/Codex

Commence par relire et vérifier les fichiers cités. Ne suppose pas qu'un service existe parce qu'il est mentionné dans ce document : confirme sa configuration et son mode d'exécution dans le dépôt et sur l'environnement ciblé.

Avant toute modification, fournis :

1. l'inventaire réel des processus et services ;
2. la matrice des dépendances ;
3. les contrôles existants réutilisables ;
4. les différences entre local, développement, BODEFM et production ;
5. le plan fichier par fichier ;
6. les tests de référence ;
7. les risques et le rollback.

Ensuite, implémente par incréments réversibles. Ne modifie ni LDAP, ni certificat, ni pare-feu, ni production sans validation explicite.

Pour chaque livraison, distingue obligatoirement :

- **Réalisé** ;
- **Testé** ;
- **Non testé** ;
- **Bloqué** ;
- **Risques** ;
- **Prochaine action**.

Le résultat attendu n'est pas une maquette. Il faut un Control Center Windows réellement opérationnel, moderne, sûr et relié aux vrais services Mining360.
