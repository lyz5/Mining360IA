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
