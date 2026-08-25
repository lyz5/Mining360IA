# Mining 360 - Audit de readiness V1

Date de l'audit : 10 aout 2026
Objectif : mise en production la semaine du 17 aout 2026

## Decision

**Statut actuel : GO conditionnel.**

L'application, ses migrations, ses routes principales, ses rapports Power BI standards et sa suite de tests forment une base exploitable. La production ne doit cependant pas etre ouverte aux utilisateurs avant la fermeture des trois points P0 suivants :

1. valider la connexion Data/MiningProd depuis le compte de service du serveur de production ;
2. valider un corpus Knowledge minimum et verifier la recherche en mode Production ;
3. figer une release Git reproductible, sauvegardee et testee sur l'environnement cible.

Prime Movers Operational Status doit rester un parcours pilote distinct tant que l'authentification Power Apps par utilisateur n'a pas ete validee de bout en bout.

## Perimetre controle

### Verification automatisee

- `python manage.py check` : aucun probleme.
- `python manage.py makemigrations --check` : aucune migration manquante.
- migrations `0054` a `0059` : appliquees.
- suite complete executee avant le durcissement final : **247 tests sur 247 passes**.
- tests de securite, reporting et conversations apres durcissement : **29 sur 29 passes**.
- tests Data de non-divulgation ajoutes : **2 sur 2 passes**.
- build statique de production : **152 fichiers copies, 456 post-traites**, sans erreur de manifest.
- dependances Python : versions epinglees dans `requirements.txt`.

### Pages principales

Les pages suivantes ont ete rendues avec un utilisateur administrateur et repondent `HTTP 200` :

- Home ;
- Reporting ;
- AI Chat ;
- Data ;
- Data Sources ;
- Data Quality ;
- Knowledge Base ;
- Resources ;
- Resources Knowledge ;
- AI Config et Agents ;
- API Provider Management ;
- Reporting Config ;
- System Config ;
- OpenAI Usage ;
- Users ;
- Deployment ;
- Health.

Les dix ecrans critiques inspectes ne contiennent aucun `id` HTML duplique. La page Business Performance retourne `404` parce que le module est desactive et absent de la navigation ; ce comportement est coherent avec la configuration actuelle.

### Limite de l'audit visuel

Chrome et Edge sont installes, mais leur lancement headless est bloque par les restrictions du poste d'execution. Les controles structurels et responsives ont ete realises sur le HTML/CSS, mais la validation visuelle finale a 1920x1080, 1366x768 et 390x844 doit etre executee manuellement sur l'environnement de recette avant le GO.

## Constats par domaine

### Reporting

**Etat : globalement pret, avec Prime Movers en pilote.**

- 12 rapports actifs sont configures et marques `Validated`.
- Les 11 rapports standards visibles et leurs endpoints d'embed repondent correctement.
- 94 pages Power BI sont importees et actives.
- Aucun objet `PowerBIVisual` n'est importe. Le chatbot peut ouvrir un rapport ou une page, mais ne peut pas garantir une navigation precise vers un visuel.
- Prime Movers Operational Status utilise une strategie d'authentification speciale et ne doit pas etre considere comme un rapport standard.
- Le titre `Mining AfterMarket Perormance` contient une faute visible a corriger.

**Ameliorations recommandees :**

1. Ajouter un statut de disponibilite par rapport : `Ready`, `Degraded`, `Unavailable`.
2. Instrumenter les evenements Power BI `loaded`, `rendered` et `error`, avec rapport, page, utilisateur et duree.
3. Importer l'inventaire des visuels pour fiabiliser les actions du chatbot.
4. Ajouter recherche, favoris et categories sans transformer la page en dashboard surcharge.
5. Afficher une erreur fonctionnelle avec `Retry` et `Open in Power BI` sans exposer le payload Microsoft.
6. Tester les permissions RLS avec au moins un utilisateur standard de chaque profil.

### Chatbot

**Etat : fonctionnel et persistant, dependances externes a surveiller.**

- Les conversations persistantes, messages, artifacts et contextes sont en base.
- La limite de 10 conversations est active.
- Les endpoints de liste et de reprise repondent correctement.
- Echantillon actuel : 44 messages completes et 6 echecs historiques, soit environ 12 % d'echecs dans ce petit volume.
- Les echecs Power Automate 502 sont transitoires et necessitent retries, timeout controle et suivi.
- Les reponses adaptatives et le suivi conversationnel sont couverts par des tests dedies.

**Ameliorations recommandees :**

1. Definir un SLO V1 : 95 % des reponses sans erreur et temps median inferieur a 12 secondes.
2. Ajouter un circuit breaker autour de Power Automate et afficher un identifiant de support non sensible.
3. Construire une suite de 30 questions metier de reference : KPI, tendance, comparaison, ranking, downtime, follow-up FR/EN.
4. Mesurer par agent : succes, timeout, no-data, fallback, duree, cout et taux de retry.
5. Conserver les fallbacks deterministes lorsque le calcul est valide mais la formulation IA echoue.
6. Ajouter une evaluation utilisateur simple utile/pas utile apres stabilisation, pas avant le lancement.
7. Ne jamais reconstruire un artifact historique depuis le contexte actif.

### Data

**Etat : blocage P0 de connectivite a lever sur le serveur cible.**

- 21 Data Browsers actifs sont configures.
- La configuration MiningProd a deja ete verifiee, mais la lecture live echoue depuis l'environnement d'audit.
- Erreur observee : connexion impossible a `bodefm:1433`, avec problemes TLS/ODBC puis hote inaccessible.
- Le dashboard System Config indique 6 integrations `Configured`, mais aucune `Connected` au moment de l'audit.
- Les erreurs Data ne renvoient desormais plus les details de connexion au navigateur ; l'API retourne `503 data_source_unavailable` et journalise le detail cote serveur.

**Actions avant production :**

1. Tester DNS, port 1433, ODBC 18, certificat TLS et authentification depuis le compte Windows qui execute Waitress.
2. Executer un preview de cinq lignes sur chaque Data Browser critique.
3. Laisser les ecritures desactivees par defaut ; activer creation/modification/import au cas par cas.
4. Tester les limites de pagination, export et import avec un volume representatif.
5. Ajouter fraicheur, source, derniere synchronisation et proprietaire sur chaque dataset.
6. Remplacer la synchronisation SQL en thread web par une commande planifiee ou un worker dedie.

### Knowledge

**Etat : blocage P0 pour l'agent Mining Knowledge en Production.**

- 15 231 elements de connaissance sont indexes.
- Ils sont tous en statut `To Review` ; aucun n'est `Validated`.
- Une recherche Production sur `availability best practices` retourne zero resultat.
- La recherche Debug retourne des elements, ce qui confirme que l'index existe mais que la gouvernance bloque la diffusion.
- 575 synonymes actifs sont valides, mais 542 n'ont encore aucune utilisation observee.
- Un seul KPI est present dans le dictionnaire Knowledge valide.

**Actions avant production :**

1. Selectionner un corpus V1 restreint de documents fiables et proprietaires identifies.
2. Valider en priorite Availability, Downtime, MTBF, MTTR, maintenance preventive, Power Train et securite.
3. Executer 20 recherches de reference et verifier pertinence, citation, page source et absence d'invention.
4. Afficher clairement `No validated source found` lorsque la base ne couvre pas la question.
5. Ajouter un tableau de couverture : documents valides, age, domaine, modele, site et questions sans reponse.
6. Mettre en place version, date d'effet, date de revue et proprietaire de chaque source.

## Securite et exploitation

### Corrections appliquees pendant l'audit

- redirection HTTPS configurable et active par defaut hors Debug ;
- cookies session et CSRF `Secure` hors Debug ;
- cookies session `HttpOnly` et `SameSite=Lax` ;
- HSTS initial de 3600 secondes en production ;
- support du host public et des headers du reverse proxy ;
- origine CSRF de production configurable ;
- details ODBC masques dans les reponses Data ;
- tests de non-divulgation ajoutes.

`includeSubDomains` et `preload` HSTS restent volontairement desactives. Ils ne doivent etre actives qu'apres confirmation que tous les sous-domaines concernes supportent HTTPS.

### Risques restants

- Le endpoint `/health/` controle uniquement l'application et la base Django. Il ne prouve pas que Power BI, Power Automate, OpenAI, MiningProd et Knowledge sont disponibles.
- Il n'existe pas de configuration de logging structuree/rotation/alerting clairement definie dans Django.
- La synchronisation SQL des configurations utilise un thread daemon dans le processus web et produit des verrous SQLite pendant les tests.
- Le worktree contient de nombreux fichiers modifies et non suivis. Une machine construite depuis le dernier commit ne reproduirait pas la version actuellement testee.

## Gate de lancement obligatoire

### P0 - a terminer avant le GO

- [ ] Creer une branche release, committer toutes les migrations et sources necessaires, puis taguer la version.
- [ ] Retirer les fichiers temporaires Office et artefacts locaux du package de release.
- [ ] Sauvegarder la base et executer un test de restauration.
- [ ] Executer les migrations sur une copie de production.
- [ ] Executer `check --deploy` avec les vraies variables d'environnement.
- [ ] Executer `collectstatic` avec le chemin statique de production.
- [ ] Verifier HTTPS, certificat, DNS public, reverse proxy et callback Entra.
- [ ] Valider MiningProd depuis le compte de service de production.
- [ ] Valider les six integrations critiques, pas seulement leur configuration.
- [ ] Valider un corpus Knowledge V1 et les recherches de reference.
- [ ] Tester les rapports et le chatbot avec un utilisateur non administrateur.
- [ ] Effectuer le smoke test visuel desktop, laptop et mobile.
- [ ] Valider le rollback applicatif et base.

### P1 - premiere semaine apres lancement

- [ ] readiness detaillee par dependance et page Status admin ;
- [ ] collecte centralisee des erreurs et alertes ;
- [ ] tableau SLO Reporting/Chat/Data/Knowledge ;
- [ ] worker de synchronisation hors processus web ;
- [ ] inventaire Power BI des visuels ;
- [ ] feedback chatbot et analyse des questions sans reponse.

## Proposition d'experience "WAW"

La valeur distinctive ne doit pas venir d'animations ou de cartes supplementaires, mais d'une continuite entre les quatre modules.

1. **Equipment 360** : une fiche machine unique regroupant KPI, evenements, rapports Power BI, commentaires et connaissances techniques.
2. **Ask about this** : depuis un site, une machine, un KPI ou un driver, ouvrir le chatbot avec un contexte signe et visible.
3. **Open evidence** : depuis une reponse IA, ouvrir exactement la page/selection Power BI ou la source documentaire citee.
4. **Unified search** : une recherche globale distinguant conversations, rapports, equipements, datasets et documents.
5. **Trust indicators** : date du calcul, fraicheur des donnees, source, filtre applique et niveau de validation toujours visibles.
6. **Personal workspace** : favoris de rapports, conversations recentes et equipements suivis, sans page d'accueil surchargee.

## Planning recommande

### J-5 a J-4

- freeze fonctionnel ;
- fermeture des P0 Data et Knowledge ;
- creation et tag de la release candidate ;
- sauvegarde et repetition des migrations.

### J-3

- deploiement en recette identique production ;
- tests des integrations avec le compte de service ;
- execution de la suite de tests et du build statique.

### J-2

- recette metier Reporting, Chatbot, Data et Knowledge ;
- responsive desktop/laptop/mobile ;
- permissions utilisateur standard et administrateur ;
- test de charge court avec utilisateurs concurrents.

### J-1

- correction uniquement des blocants ;
- validation du rollback ;
- communication utilisateurs et canal support ;
- decision GO/NO-GO signee.

### J0 et J+2

- deploiement sur une fenetre surveillee ;
- smoke test immediat ;
- suivi renforce des erreurs, latences et integrations pendant 48 heures.

## Conclusion

Mining 360 peut atteindre une V1 fiable la semaine prochaine a condition de ne pas elargir le perimetre fonctionnel. La priorite est de prouver la connectivite reelle, la qualite des connaissances, la securite et la reproductibilite de la release. Les evolutions "WAW" doivent ensuite renforcer la continuite entre donnees, rapports, IA et preuves, plutot que multiplier les ecrans.
