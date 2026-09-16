# Mining360 — Réconciliation du CA et des commandes

## Dossier de préparation pour Codex

**CA Combine Analysis · Backorder Request / Orders · Business Review**

Préparé pour Papa Djibril Diagne — 6 septembre 2026 — Version 1.0

### Finalité métier

Construire dans Mining360 une lecture traçable du business : comprendre le contenu de chaque facture, retrouver les commandes et les pièces concernées, identifier le reste à facturer et expliquer les blocages. Cette base doit ensuite alimenter le Business Review avec des chiffres cohérents et des actions concrètes par société, client et site minier.

Le résultat attendu relie trois réalités distinctes : les engagements clients dans Orders, la facturation commerciale et le CA comptabilisé dans CA Combine. La réconciliation doit expliquer leurs différences et préserver le détail de chacune.

### Ce que Codex doit permettre de comprendre

- Pour une facture : quels produits, quantités, commandes et montants la composent, et quel CA a été comptabilisé ?
- Pour une commande : quelle part a été facturée, quelle part reste dans le pipe et dans quel état opérationnel ?
- Pour un client ou un site : quel business est réalisé, engagé, bloqué ou susceptible d’être facturé prochainement ?
- Pour un écart : quelle est sa cause, sa preuve, son montant et l’action nécessaire ?

### Niveau de preuve de ce dossier

Les objectifs et statuts sont **confirmés dans cet échange**. Les objets et règles **retrouvés dans l’historique** restent à vérifier dans les sources actuelles. L’architecture, les contrôles et les indicateurs sont **proposés pour ce chantier**.

Ce dossier reconstitue le contexte disponible, sans reproduire les conversations et requêtes intégrales. Aucune nouvelle réconciliation des bases de production n’a été exécutée.

<!-- COVEREND -->

## 1. CA Combine Analysis : le socle comptable

### Ce qui a été travaillé

Le travail CA Combine / Suivi_CA_Combine / Global Sales concerne le CA issu de NMBEPM, enrichi par les axes société, client, compte, produit, service et équipement. Un script retrouvé dans l’historique part de `NMBEPM.dbo.ana_f_ecriture_analytique` et applique notamment `feca_taf_code LIKE 'CA'` et `tps_code_annee > 2024`. Ces filtres décrivent une version historique ; Codex doit lire ceux du rapport retenu aujourd’hui. [S2]

Les principes de calcul retrouvés sont : CA euro = somme des crédits de consolidation analytique moins les débits correspondants ; CA en devise société = somme des crédits d’écriture analytique moins les débits correspondants. Les noms physiques exacts des colonnes montants restent à récupérer dans le SQL actuel. Le champ `Facture` était relié à `feca_num_piece_ecriture_comptable`. [S2]

Les vues `v_epm_ecritures_analytiques`, `v_epm_journal_ventes` et `v_export_journal_des_ventes` figurent également dans le contexte antérieur. Leur existence, leur rôle et leur utilisation effective par le rapport actuel doivent être établis ; elles ne sont pas présumées interchangeables.

### Colonnes effectivement lues dans l’export historique

| Besoin | Libellés présents dans Dataset CA Combine.xlsx |
|---|---|
| Identité et organisation | Id de l’écriture comptable ; Code société ; Code Succursale |
| Document et temps | Facture ; Date écriture comptable ; Date saisie ; Type journal ; Code journal |
| Client | Code Client ; Nom Client ; Code CIC Client ; Code Pays |
| Montants et devise | CA en € ; CA en devise locale ; Devise |
| Périmètre analytique | Taf Code ; N° Compte comptable ; LOB ; Libellé Produits ; Service |
| Équipement | Code équipement ; N° série équipement ; Modèle équipement |

Source : export historique fourni le 27 mai 2026, onglet Export. Ses 43 colonnes ont été relues ; il n’établit pas le schéma actuel du modèle sémantique. [S5]

### Conséquence pour le rapprochement

Une facture peut correspondre à plusieurs écritures ou ventilations analytiques. L’unicité de l’identifiant d’écriture dans la sortie doit être mesurée. La colonne Facture ne garantit pas l’existence d’une facture commerciale : l’export contient notamment un libellé « FAE PRESTATION SNIM ». Codex devra identifier les écritures de factures à établir, avoirs, extournes et ajustements selon les règles Finance, puis conserver un rapprochement séparé pour ces catégories. [S5]

<!-- PAGE -->

## 2. Backorder Request : le portefeuille Orders

### Deux niveaux à distinguer

La page **Mining Parts Tracking** est décrite comme une analyse du portefeuille de commandes, des montants et de l’exposition financière. Elle comporte les cinq onglets BackOrder, Delivered, Disponible, Overdue et Picking Ongoing. La page **Order Details** expose une commande et ses lignes : identité, client, date, ETA, devise, montants, références, marque et quantités commandées/préparées. [S4]

Le suivi **BackOrders Tracking** constitue un sous-ensemble spécialisé : il suit les lignes BackOrder CAT jusqu’aux commandes fournisseurs et aux statuts CAT/PSO. La vue `VW_BACKORDERS_TRACKING` ne doit donc pas être utilisée par défaut comme inventaire complet de toutes les commandes et factures.

### StatutGlobal : logique historique à récupérer

| Priorité retrouvée | Statut | Ce qui est établi / contrôle attendu |
|---|---|---|
| 1 | BackOrder | Conditions métier spécifiques ; ne découle pas de la seule présence d’une contre-marque. |
| 2 | Picking Ongoing | Règle SQL/DAX exacte à lire dans le rapport actuel. |
| 3 | Delivered | Vérifier la définition de livraison et son niveau, commande ou ligne. |
| 4 | Overdue | ETA dépassée ; vérifier exclusions et traitement des dates vides. |
| 5 | Disponible | Valeur par défaut dans l’ordre historique ; vérifier qu’elle prouve bien la disponibilité. |

L’ordre BackOrder → Picking Ongoing → Delivered → Overdue → Disponible provient du contexte de la discussion du 10 août 2026. Les conditions complètes de chaque branche n’ont pas été récupérées. [S2]

### Trois dimensions indépendantes

Conserver séparément le statut opérationnel, le statut de facturation et le statut de réconciliation comptable. Une ligne Delivered peut encore nécessiter une facturation ; une ligne préparée peut être partiellement facturée. Ces possibilités doivent être testées sur les données, sans les transformer en règles implicites.

Disponible ne signifie pas automatiquement « facturable immédiatement » : les conditions commerciales, le circuit de livraison et les blocages doivent être confirmés. De même, un statut CAT I1 « Source Item » décrit une disponibilité chez CAT ; il ne prouve ni une réception filiale ni une facturation client.

Le périmètre CAT est documenté pour BackOrders Tracking. Le périmètre de la page Orders complète — marques, sociétés, types de commandes, archives et dates — reste à demander à l’utilisateur. [S3, S4]

<!-- PAGE -->

## 3. Acquis du suivi fournisseur à préserver

### Sources documentées au 25 juillet 2026

| Objet Snowflake documenté | Rôle historique |
|---|---|
| NEEMBA.LOGISTICS_PARTS.A_BRONZE_IE_NEG_ENT | Entêtes des commandes clients |
| NEEMBA.LOGISTICS_PARTS.A_BRONZE_IE_NEG_LIG | Lignes de commandes clients et inter-filiales |
| NEEMBA.CORE.A_BRONZE_IE_AGR_TAB | Décodage des statuts |
| NEEMBA.SALES.A_BRONZE_IE_FRN_CDL | Lignes des commandes fournisseurs |
| NEEMBA.SALES.A_BRONZE_IE_FRN_BSE | Référentiel fournisseurs |
| NEEMBA.CORE.A_BRONZE_IE_IMP_LIG | Flux de réponses CAT/PSO |

Ces emplacements sont des références documentaires, à faire confirmer dans l’environnement Mining360 actuel. [S3]

### Leçons déjà acquises

Le modèle part de NEG_ENT pour récupérer correctement le client, puis joint NEG_LIG sur société, succursale et commande. La clé historique `CleBackOrder` comprend société, succursale, commande client, ligne et référence pièce. `SK` est décrit sans la référence pièce. Codex devra vérifier stabilité et unicité, notamment si une référence est modifiée.

La jointure fournisseur doit inclure la ligne de contre-marque : société, succursale, numéro fournisseur, `FCDL_LIGNE` et référence. Omettre cette ligne avait multiplié les enregistrements. La chaîne comporte des relations multiples ; `VW_BACKORDERS_CAT_DETAIL` et `VW_BACKORDERS_PSO_DETAIL` les conservent séparément de la synthèse à une ligne par BackOrder. [S3]

Les règles de périmètre BackOrder documentées sont : CAT ; commande EN COURS ou PARTIELLEMENT LIVRE ; nature contre-marque C ; quantité à livrer différente de la commandée ; quantité facturée différente de la commandée ; date commande à partir du 1er janvier 2024. Ce filtre spécialisé ne définit pas tout le pipe Orders. [S3]

### Résultats historiques, non chiffres actuels

Le document du 25 juillet rapporte 28 515 lignes et autant de clés uniques, zéro doublon final, 95 lignes sans ligne de contre-marque, 3 lignes fournisseur non trouvées et 25 correspondances inter-filiales ambiguës. Ces chiffres prouvent les contrôles réalisés alors ; ils ne constituent pas des seuils fixes pour une extraction future. [S3]

Le suivi fournisseur pourra expliquer un blocage du pipe. Ses prix d’achat, soldes fournisseurs et montants inter-filiales ne doivent pas être assimilés au prix de vente client ou ajoutés au CA client.

<!-- PAGE -->

## 4. La liaison commande–facture : piste et preuves

### Rectification à conserver explicitement

L’utilisateur a cité `NENT_FAC` comme piste de liaison. Le présent échange ne permet pas de déterminer s’il s’agit d’une table, d’une vue, d’un champ ou d’un alias de rapport. Le dictionnaire Irium consulté ne comporte pas d’objet sous ce nom exact. Cette absence dans un dictionnaire ancien ne prouve pas son absence de la base actuelle.

Le dictionnaire fournit en revanche les éléments suivants. [S6]

| Table / champ | Description du dictionnaire | Utilité potentielle |
|---|---|---|
| neg_lig.nlig_numfac | N° de facture | Candidat de liaison commerciale |
| neg_lig.nlig_qtefac | Quantité facturée | Contrôle des facturations partielles |
| neg_lig.nlig_succfac | Succursale ayant émis la facture | Identification de l’émetteur |
| neg_lig.nlig_servfac | Service ayant émis la facture | Contexte de facturation |
| neg_ent.nent_facht | CA HT de la facture | Montant d’entête à qualifier |
| neg_ent.nent_facttc | CA TTC de la facture | Contrôle TTC distinct du CA HT |
| neg_ent.nent_numfacann | Facture si annulation « logique » | Analyse des annulations |

Le dictionnaire est issu d’une extraction décrite au 7 janvier 2022 et a été partagé le 30 août 2026. Ces descriptions ne valident ni l’exhaustivité des champs, ni la gestion de l’historique, ni leur sémantique dans la réplication actuelle.

### Questions que Codex doit poser et résoudre

- « Où vois-tu NENT_FAC exactement : rapport, table, requête, mesure ou base ? Peux-tu m’indiquer son emplacement et un exemple ? »
- Où trouver les entêtes et lignes de toutes les factures émises, y compris avoirs et archives ?
- `NLIG_NUMFAC` conserve-t-il toutes les factures d’une ligne ou seulement une référence courante ?
- Une facture couvre-t-elle plusieurs commandes ? Une ligne peut-elle être facturée en plusieurs fois ?
- La succursale de commande diffère-t-elle de celle qui facture ? Comment les codes société se correspondent-ils ?

### Clé candidate, non clé déjà validée

Tester société émettrice normalisée + numéro de facture. Ajouter succursale émettrice, type de document et/ou série/exercice seulement si les règles de numérotation le nécessitent. Ne pas ajouter automatiquement l’année comptable, qui peut différer de l’année de la facture. Conserver les identifiants en texte, les zéros initiaux et les valeurs brutes à côté des valeurs normalisées.

<!-- PAGE -->

## 5. Modèle de rapprochement proposé

### Des faits distincts et des liens explicites

| Ensemble logique proposé | Grain et fonction |
|---|---|
| Écritures de CA | Grain réel de la source Finance ; référence des montants comptabilisés |
| Factures commerciales | Une entête par document et des lignes identifiables |
| Commandes clients | Une entête par commande et une ligne par position métier |
| Liens commande–facture | Associations entre lignes, avec quantités/montants attribuables prouvés |
| État du pipe | Reste à facturer par ligne et date d’observation |
| Exceptions | Objet concerné, motif, montant, preuve et statut de résolution |

Ces noms décrivent le modèle souhaité ; ils ne sont pas présentés comme des tables existantes. Les dimensions société, client, site, produit et calendrier doivent reprendre les référentiels Mining360 disponibles et validés.

### Procédure de réconciliation

1. Reproduire les totaux du rapport CA et les totaux Orders avec leurs filtres, mesures et dates de rafraîchissement.
2. Identifier les factures commerciales et les liens vers les commandes en mesurant toutes les cardinalités.
3. Rapprocher CA et facturation au niveau de la facture, sur un périmètre et une devise comparables.
4. Présenter les lignes commerciales sous la facture et les commandes associées, sans recopier le total comptable sur chaque ligne.
5. Calculer le reste à facturer avec les données commerciales ; enrichir ce reste des statuts et blocages opérationnels.
6. Produire les exceptions des deux côtés et les totaux de couverture, puis préparer les agrégations Business Review.

### Protection contre les doubles comptes

Deux écritures de CA et trois lignes de facture peuvent produire six lignes lors d’une jointure directe. Chaque ensemble doit donc être agrégé au niveau nécessaire avant comparaison ; les détails restent consultables séparément.

Un rapprochement prouvé au niveau facture n’établit pas une attribution exacte de CA à chaque pièce. Si cette attribution n’existe pas dans les sources, afficher le détail commercial et le total comptable côte à côte. Toute allocation doit être explicite, documentée et validée ; elle ne devient pas une donnée source.

Les relations multiples doivent rester visibles. Aucun DISTINCT, choix arbitraire du premier candidat ou rapprochement sur le seul nom client ne doit masquer une ambiguïté.

<!-- PAGE -->

## 6. Montants, dates et définition du pipe

### Mesures à maintenir séparées

| Mesure | Définition de travail à valider |
|---|---|
| CA comptabilisé | Mesure officielle du CA Combine, à la date comptable |
| Facturation commerciale nette | Factures et avoirs émis selon leurs signes et dates propres |
| Engagement client actif | Valeur de vente des commandes actives après modifications/annulations |
| Reste à facturer | Obligation commerciale restant à facturer à une date donnée |
| Écart facture–CA | CA comptabilisé moins montant commercial comparable |
| Potentiel de facturation | Part du reste à facturer répondant aux critères métier convenus |

Le pipe désigne ici les commandes clients engagées restant à facturer. Les devis ou opportunités non commandés pourront être reliés plus tard, dans une catégorie distincte. Ne pas additionner CA comptabilisé et facturation commerciale : ils représentent souvent deux lectures de la même vente.

### Calcul du reste à facturer

Préférer une valeur source de reste à facturer dont la règle est vérifiée. À défaut, reconstruire au niveau ligne l’engagement actif moins la facturation imputable, avec un traitement documenté des annulations, retours, remplacements, frais, remises et avoirs. Un avoir n’ouvre pas automatiquement une nouvelle obligation de livraison ou de facturation.

La formule quantité restante × prix net peut être un contrôle, si quantités, unités, prix, remises et frais le permettent. Elle ne doit pas devenir une estimation présentée comme montant officiel. Un reste négatif est à expliquer ; ne pas le ramener silencieusement à zéro. Une valeur inconnue reste inconnue.

### Comparaison monétaire et temporelle

Comparer HT à HT et conserver les devises document, société et consolidation. Réutiliser les règles de conversion de référence ; documenter taux, sens et date. Ne pas additionner directement EUR, USD et XOF. `AMOUNTNET`, les prix d’achat et les soldes fournisseurs restent à qualifier avant tout usage financier.

Le CA mensuel est un flux sur une période ; le pipe est un état à une date. Distinguer date commande, facture, comptabilisation, livraison, ETA et extraction. Une commande ancienne peut générer une facture récente : le filtre Orders ne doit pas la supprimer. Les filtres historiques 2024 côté BackOrder et après 2024 côté CA ne sont pas automatiquement compatibles.

Pour suivre l’évolution du pipe, vérifier l’existence d’historiques ou créer des snapshots prospectifs après validation. Un état courant seul ne permet pas de reconstituer fidèlement le pipe des mois passés.

<!-- PAGE -->

## 7. Exploration accompagnée : où Codex doit chercher

### Première étape obligatoire

Codex doit d’abord lire le contexte du projet Mining360 accessible et lister ce qu’il sait déjà. Il demande ensuite les références manquantes en petits groupes, en commençant par les deux rapports. Il avance sur les analyses possibles entre deux réponses, sans redemander les informations déjà fournies.

### Séquence de questions à poser à Papa Djibril

1. **CA Combine** : quel rapport fait référence, dans quel workspace Power BI ? Quelle page ou quel visuel représente le CA officiel ? Quel modèle sémantique, quelle table, quelles colonnes et quelle mesure exacte ? Où consulter le SQL, Power Query et le DAX ?
2. **Orders** : où se trouve la page qui contient les cinq statuts ? Quelle table l’alimente ? Où trouver les commandes complètes, lignes facturées et archives ? Quelles sont les mesures de montants et la formule de StatutGlobal ?
3. **Facturation** : où est NENT_FAC ? Où obtenir les factures et leurs lignes ? Quelle relation relie la facture commerciale à la commande et à CA Combine ?
4. **Preuves** : peux-tu désigner une facture simple, une commande partiellement facturée, une commande non facturée et un avoir ? Ajouter ensuite les cas de livraison non facturée et de commandes regroupées si présents.
5. **Business Review** : quel rapport ou module cible, quel grain de lecture, quelles périodes et quelle définition client/site ? Où sont les référentiels, budgets et objectifs déjà utilisés ?

Chaque demande précise l’information attendue et son utilité. Si Codex ne peut pas accéder à un rapport, il demande l’export, le code de requête ou la capture ciblée nécessaire. Il ne présume aucun accès aux bases ou aux API.

### Fiche à compléter pour chaque source

Consigner le rapport et son lien ; le workspace et le modèle sémantique ; la page et le visuel de référence ; la table ou vue ; la requête SQL/Power Query ; la colonne ou mesure DAX ; le grain ; la clé ; les filtres ; le périmètre société/marque/type ; la devise ; la date métier ; la date de rafraîchissement ; un exemple et son total de contrôle ; la personne ayant confirmé la règle.

### Réutiliser l’existant

Si les rapports validés et les services Mining360 exposent déjà les bonnes mesures, les réutiliser. Si le détail manque, demander où puiser ce détail et justifier le complément. Une source supplémentaire ne doit pas modifier silencieusement la définition du CA ou du périmètre commercial.

<!-- PAGE -->

## 8. Contrôles et critères d’acceptation

### Contrôles de fond

| Contrôle | Résultat attendu |
|---|---|
| Fidélité CA Combine | Total reproduit sur les mêmes sociétés, périodes, filtres et devises |
| Fidélité Orders | Totaux et volumes reproduits par statut sur le périmètre retenu |
| Grain et cardinalités | Doublons, clés nulles et relations multiples quantifiés |
| Conservation des montants | Aucune inflation due aux jointures, y compris aux détails CAT/PSO |
| Couverture | Factures rapprochées et non rapprochées visibles des deux côtés |
| Facturation partielle | Facturé et reste à facturer établis sur des cas réels |
| Écritures particulières | Avoirs, FAE, extournes et ajustements identifiés et expliqués |
| Actualité | Dates d’extraction et décalages de rafraîchissement affichés |
| Traçabilité | Chaque montant peut être expliqué et retrouvé dans sa source |

### Exceptions à produire

CA sans facture commerciale retrouvée ; facture commerciale sans CA retrouvé ; différence de montant ou de devise ; lien commande–facture absent ou ambigu ; société émettrice non mappée ; document hors période ou périmètre ; reste à facturer négatif ; client/site non identifié ; historique insuffisant ; source non accessible.

Une absence de correspondance n’est pas automatiquement une erreur : elle peut résulter d’un décalage, d’une écriture de FAE ou d’un périmètre différent. Chaque cause doit être prouvée ou marquée « à investiguer ».

### Mesurer la couverture correctement

Présenter le nombre de factures rapprochées, la couverture en montant et la ventilation des exceptions. Calculer séparément ventes et avoirs, ou utiliser une base absolue documentée, car les signes peuvent masquer des écarts. Un taux calculé sur un solde net quasi nul peut être trompeur. Ne pas fixer arbitrairement un objectif de rapprochement avant d’examiner la population.

### Recette métier

La recette comprend des exemples traçables : facture simple, facturation partielle, plusieurs commandes pour une facture, plusieurs factures pour une commande, référence de facture identique dans deux entités, avoir, annulation, FAE et livraison non facturée lorsqu’ils existent. Chaque résultat attendu doit être vérifié avec l’utilisateur.

Une tolérance monétaire peut être convenue par devise et motif d’arrondi. Les écarts restent visibles. Le statut « validé » doit reposer sur ces contrôles et sur l’examen des exceptions significatives, pas uniquement sur un total global proche.

<!-- PAGE -->

## 9. Restitution Mining360 et futur Business Review

### Parcours métier proposé

**Vue globale** : CA comptabilisé, facturation commerciale, reste à facturer, part Delivered non facturée, part Disponible/Picking non facturée, retards et montants non rapprochés. Tous les indicateurs portent leur période ou date d’état, leur devise et leur définition.

**Détail facture** : identité et émetteur, client, dates, commandes associées, lignes commerciales, quantités, prix/remises/frais si disponibles, total commercial, écritures de CA, différence et motif. Afficher le niveau de rapprochement réellement obtenu : facture, ligne ou allocation.

**Détail commande et pipe** : lignes commandées, facturation imputée, reste à facturer, statut opérationnel, dates, ETA, ancienneté et blocages. Proposer le suivi fournisseur/CAT/PSO comme explication lorsque la ligne appartient à ce circuit.

**Écarts et actions** : montant concerné, cause, preuve, responsable proposé à valider, action et échéance. Le reporting d’une action ne doit pas déclencher automatiquement un message ou une modification des systèmes sources.

### Liaison au Business Review

Le Business Review doit pouvoir passer du réalisé aux engagements clients, puis aux actions. Les questions cibles sont : que rapporte le client ; quel montant reste à transformer en facturation ; quels blocages empêchent cette conversion ; quelles décisions prendre au prochain suivi ?

Raccorder société, client, site minier, activité et période à des référentiels explicites. Un même client peut couvrir plusieurs sites ; ne pas affecter tout son CA à chacun. Les numéros de série peuvent aider au rattachement lorsqu’ils existent, mais ne garantissent pas une affectation exhaustive. Conserver un groupe « site non attribué » et un mapping historisé si nécessaire.

Les objectifs et budgets du Business Review restent une source distincte à localiser. Les montants inter-filiales doivent suivre le périmètre d’entité ou de groupe validé afin de ne pas compter plusieurs fois la même chaîne économique.

### Ordre de réalisation proposé

Commencer par une société, un client et une période choisis avec l’utilisateur, tout en conservant les commandes anciennes liées aux factures étudiées. Valider les règles et les cas limites, puis élargir le périmètre. Intégrer ensuite les vues Mining360 et, après recette, les agrégations Business Review.

La première livraison de Codex doit être une cartographie des sources et un diagnostic de faisabilité. La construction de l’interface intervient lorsque les données et les rapprochements sont suffisamment étayés.

<!-- PAGE -->

## 10. Livrables, provenance et décisions ouvertes

### Livrables à demander à Codex

- Cartographie des sources, mesures et chemins de récupération confirmés par l’utilisateur.
- Dictionnaire des champs et registre des règles avec preuve, date et statut de validation.
- Profilage des grains, clés, cardinalités, volumes et montants ; analyse des écarts de périmètre.
- Modèle de rapprochement et requêtes de diagnostic adaptées au moteur réellement utilisé.
- Restitution des factures, commandes, reste à facturer et exceptions dans Mining360.
- Rapport de recette, limites restantes et contrat de données pour le Business Review.

### Sources utilisées pour ce dossier

| Réf. | Provenance et portée |
|---|---|
| S1 | Présent échange, 6 septembre 2026 : objectif, cinq statuts, piste NENT_FAC et exploration accompagnée. |
| S2 | Contexte retrouvé des discussions CA Combine et Backorder Request, notamment 10 et 27 août 2026. Reconstitution partielle, sans dernière requête intégrale. |
| S3 | Documentation_Modele_Tracking_BackOrders_Neemba.docx, référence 25 juillet 2026 ; sections sources, clés, filtres, cardinalités et validations consultées. |
| S4 | Mine_Logistics_BackOrder_Tracking_User_Guide.docx, partagé le 25 août 2026 ; pages 3 à 9 : parcours, pages Orders et suivi CAT/PSO. |
| S5 | Dataset CA Combine.xlsx, partagé le 27 mai 2026 ; onglet Export, en-têtes et observation d’une ligne FAE. Aucun contrôle global des montants réalisé ici. |
| S6 | DICO_IRIUM_DESCRIPTION_CHAMPS(1).xlsx, partagé le 30 août 2026 ; onglets EXPLICATION et IRIUM_DESCRIPTION_CHAMPS. Descriptions recherchées pour NEG_ENT/NEG_LIG et facturation. |

### Décisions restant à prendre avec l’utilisateur

L’emplacement exact des rapports et modèles ; la source Orders exhaustive ; le sens et l’emplacement de NENT_FAC ; l’historique des facturations partielles ; la clé facture émettrice ; le mapping des sociétés ; les montants de vente officiels ; le traitement FAE/avoirs ; le périmètre CAT ou multimarque ; les dates et taux de change ; les critères de facturabilité ; le mapping client/site ; la cible Business Review.

L’écart Finance/Mining Operations évoqué antérieurement pour mai, environ 15 M contre 7 M, constitue un cas possible de recette historique. Aucune cause finale n’est démontrée dans les éléments récupérés : ne pas la présumer dans le développement. [S2]

<!-- PAGE -->

# Prompt à transmettre à Codex dans le projet Mining360

Je souhaite ouvrir un chantier fondamental pour le business dans Mining360 : réconcilier les données de CA Combine Analysis avec celles du portefeuille Orders étudié dans notre travail Backorder Request, puis préparer leur rattachement au Business Review.

Lis le dossier de préparation joint et le contexte existant du projet. Le dossier reconstitue nos travaux et propose une méthode ; il ne garantit pas que les noms et règles historiques correspondent aux versions actuellement en production.

## Objectif

Je veux pouvoir ouvrir chaque facture, comprendre ses lignes et les commandes correspondantes, retrouver le CA comptabilisé, identifier les écarts et voir ce qui n’a pas encore été facturé dans le pipe. Je veux ensuite utiliser cette base dans le Business Review pour expliquer le réalisé, le reste à facturer, les blocages et les actions par société, client et site minier.

Traite ce chantier comme un projet métier et de qualité des données. La fiabilité des montants, la traçabilité et l’explication des écarts sont essentielles.

## Contexte à conserver

CA Combine / Suivi_CA_Combine s’appuie sur NMBEPM. Une requête historique part de ana_f_ecriture_analytique, avec un filtre de CA et des montants crédit moins débit. Le rapport dispose d’un numéro de facture et de dimensions société, client, dates et axes analytiques. Plusieurs lignes comptables peuvent correspondre à une facture. L’export historique comporte aussi des écritures de FAE : une référence de pièce comptable ne prouve donc pas, seule, une facture commerciale émise.

Orders couvre BackOrder, Picking Ongoing, Delivered, Overdue et Disponible. L’ordre historique de StatutGlobal est celui-ci, Disponible étant la branche par défaut ; récupère les conditions exactes actuelles avant de les utiliser. Le suivi spécialisé VW_BACKORDERS_TRACKING porte sur des lignes BackOrder CAT et leurs liens fournisseurs/CAT/PSO. Identifie séparément la source complète de Mining Parts Tracking et Order Details, avec les lignes facturées et les archives nécessaires.

J’ai cité NENT_FAC comme piste de liaison : demande-moi où se trouve exactement cet objet et ce qu’il représente. Ne présume pas qu’il s’agit d’un champ de NEG_ENT. Le dictionnaire historique décrit notamment NEG_LIG.NLIG_NUMFAC, NLIG_QTEFAC, NLIG_SUCCFAC et NLIG_SERVFAC ; ce sont des pistes à vérifier dans les sources actuelles. Vérifie aussi où se trouve l’historique complet des factures, car une référence courante peut être insuffisante pour une facturation partielle.

## Méthode d’exploration avec moi

Commence par lire les instructions et composants Mining360 accessibles, puis dis-moi ce qui est établi et ce qui manque. Demande-moi explicitement où puiser les informations dans les rapports : rapport, workspace, modèle sémantique, page, visuel, table, mesure DAX, requête Power Query/SQL ou base source. Je t’indiquerai exactement où aller chercher.

Pose les questions par petits groupes et commence par la localisation du CA Combine de référence et de la page Orders qui contient les cinq statuts. Pour chaque question, précise ce dont tu as besoin et pourquoi. Ne me demande pas de confirmer de nouveau ce que j’ai déjà indiqué. Continue les analyses possibles pendant que nous clarifions les autres points.

Demande ensuite l’emplacement de NENT_FAC, des factures commerciales et de leurs lignes, ainsi que quelques exemples réels : facture simple, commande partiellement facturée, commande non facturée et avoir. Vérifie les cas multiples et les lignes livrées non facturées s’ils existent. Si tu n’as pas accès à une source, demande un export ou le code ciblé ; n’invente pas l’accès, les champs ou les relations.

Réutilise les sources, mesures et services existants lorsqu’ils sont adaptés. Si un détail manque, identifie le complément nécessaire avec moi. Ne remplace pas silencieusement les règles officielles des rapports.

## Analyses et règles attendues

1. Cartographie chaque source : emplacement exact, grain, clé, montant, devise, dates, filtres, historique et rafraîchissement. Distingue faits vérifiés, hypothèses et questions ouvertes.
2. Reproduis les totaux CA et Orders dans un contexte identique à leurs rapports de référence. Explique les différences de périmètre avant toute comparaison.
3. Identifie les clés commande, ligne, facture et ligne de facture. Teste les doublons et les cardinalités dans les deux sens. Conserve les identifiants en texte et leurs zéros initiaux. Détermine la société et la succursale réellement émettrices ; ne joins pas sur le seul numéro de facture.
4. Gère les factures partielles, plusieurs factures par commande, plusieurs commandes par facture, avoirs, annulations, retours, FAE, extournes, frais/remises et décalages de dates selon les sources et les règles validées. Ne déduis pas automatiquement qu’un avoir remet une commande dans le pipe.
5. Sépare les écritures de CA, les factures commerciales, les commandes, les relations commande–facture et les états du pipe. Protège les sommes contre toute multiplication due aux jointures. Ne choisis jamais arbitrairement une correspondance ambiguë.
6. Rapproche d’abord les montants au niveau facture. Présente ensuite les lignes commerciales associées. Si l’attribution du CA à la pièce n’est pas prouvée, indique le niveau réel de précision ; n’affecte pas le total facture à chaque ligne. Toute allocation doit être explicitement proposée et validée.
7. Distingue CA comptabilisé, facturation commerciale et reste à facturer. Le pipe visé est celui des commandes engagées. Utilise les valeurs de vente client ; ne confonds pas prix d’achat fournisseur, montant commandé, montant facturé et solde. Un champ inconnu ne vaut pas zéro et un reste négatif doit être expliqué.
8. Maintiens indépendants statut opérationnel, facturation et réconciliation. Delivered ne prouve pas la facturation ; Disponible ne prouve pas la facturabilité immédiate ; I1 chez CAT ne prouve pas la disponibilité locale. Valide les critères de potentiel de facturation avec moi.
9. Aligne HT/TTC, devises, conversions et périmètres. Distingue flux de CA sur une période et pipe à une date. Préserve les commandes anciennes liées aux factures récentes. Ne reconstitue pas un historique du pipe à partir du seul état courant.
10. Conserve les factures et commandes non rapprochées. Produis des exceptions avec motif, preuve, montant et statut d’investigation, ainsi que les taux de couverture en volume et en montant. Traite les avoirs de façon à éviter qu’ils masquent les écarts.

## Livrables et progression

Commence par une cartographie des sources et un diagnostic de faisabilité, avec les premiers contrôles chiffrés disponibles. Propose ensuite le modèle et un pilote limité choisi avec moi. Établis des exemples réels et des totaux de contrôle avant d’élargir le périmètre.

Conserve dans le projet la documentation, le mapping des champs, les règles validées, les questions ouvertes, les diagnostics et les résultats de recette. Les requêtes doivent correspondre au moteur effectivement utilisé, et les noms nouveaux doivent être clairement présentés comme propositions.

Prépare ensuite une restitution Mining360 avec vue globale, détail facture, détail commande/pipe et écarts/actions. La recette doit démontrer la fidélité aux rapports, l’absence de doubles comptes, le traitement des cas partiels et la traçabilité des exceptions significatives.

Prépare enfin le contrat de données du Business Review : société, client, site, activité, période, réalisé, reste à facturer, blocages et actions. Demande-moi où sont les référentiels et le rapport cible. Ne rattache pas arbitrairement un client à un site et n’additionne pas plusieurs fois la même chaîne inter-filiales. Les budgets et opportunités restent des sources séparées à identifier si nécessaires.

Commence maintenant par ton résumé de l’objectif, ce que tu retrouves dans Mining360 et tes premières questions ciblées pour que je t’indique où récupérer CA Combine et Orders. Ne démarre pas par la construction de l’interface : établissons d’abord des sources et des règles de rapprochement vérifiables.
