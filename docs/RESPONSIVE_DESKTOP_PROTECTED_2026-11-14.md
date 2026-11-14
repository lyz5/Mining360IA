# Responsive Mining360 — desktop protégé

Travail local sur `feature/responsive-desktop-protected-20261114`, depuis le tag
immuable `bodefm-validated-2026-11-14` (`401b973`). Le commit applicatif `237c6e9`
a été poussé sur cette branche à la demande de l'utilisateur. Le bilan initial
ci-dessous décrit les vérifications locales avant promotion ; il ne prouve pas
un déploiement BODEFM.
Le prompt Responsive Desktop Protégé remplace le précédent prompt mobile-first.

## Audit initial

Stack : Django/templates, CSS et JavaScript natifs, graphiques SVG existants,
SDK Power BI existant. Pas de migration de framework ni de nouvelle dépendance.
La navigation commune est `includes/app_nav.html` ; ses liens sont déjà rendus
selon les autorisations serveur. Les adaptations réutilisent ces liens.

Les 90 états du dossier privé `exports/Mining360_Captures_2026-11-14` constituent
la référence BODEFM : manifest, index CSV, résultats, instructions, PNG complets
et PDF. Les aperçus en chargement (notamment Sales/Configuration) ne valident pas
les vues finales. Les nouvelles comparaisons locales utilisent des données de test
déterministes, jamais un fallback de l'application.

Problèmes préexistants observés : sidebar dans le flux mobile ; seconde navigation
fixe Business ; débordements tablette Business, Data Preview et Knowledge Admin ;
ancien résultat Availability visible après échec MTBS/MTBF ; route Workflow 404.
Les reproductions et leurs limites sont consignées dans le bilan de validation ;
les captures initiales ne suffisent pas à établir une cause technique.

## Lots

A. Shell/navigation compacte et pilote Business ; aucune mutation des permissions.
B. Couleurs Business exclusivement : registre stable par identifiant, surfaces
   communes, dimensions desktop préservées. Cohortes Parts séparées.
C. Adaptations ciblées des autres pages, du cadre viewer et du chatbot.
D. Correctifs d'état locaux, isolés, avec tests de concurrence.

Les API, mesures, imports, caches, authentification, CSRF, RLS, modèles, tokens et
cycle d'intégration Power BI/Power Apps restent hors modification.

## Validation et limites

La référence a 4 échecs de tests connus (3 anciens tests Users, 1 ordonnanceur de
refresh) ; voir `deployment/bodefm-validated-20261114/validation.json`. Les corriger
ne fait pas partie du responsive. Aucun test de bouton de mutation ne doit écrire
sur un service partagé. Le serveur de fixtures est lié à 127.0.0.1, utilise une
base isolée, bloque les mutations et les sources externes et n'est pas importé
par l'application. Les screenshots de fixtures portent une indication explicite.

Les résultats détaillés se trouvent dans
[le bilan de validation](RESPONSIVE_VALIDATION_2026-11-14.md). Aucun chiffre de
performance terrain ni validation de téléphone physique n'est affirmé.

## Fichiers et composants par lot

| Lot | Fichiers | Fonction |
|---|---|---|
| A | `Mining360IA/settings.py`, `reports/templatetags/presentation_tags.py`, `includes/presentation.html`, `includes/app_nav.html`, `presentation_bootstrap.js` | Deux interrupteurs indépendants ; activation par script externe même origine, sans assouplir la CSP. Navigation issue des liens déjà autorisés par le serveur. |
| A / C | `reports/static/reports/responsive.js`, `responsive.css` | Header compact, cinq destinations maximum, More, focus/inert, tableaux à défilement local, navigateurs secondaires repliables, Sources, viewer et chatbot. Les sections CSS du lot C sont identifiées. |
| A | `business_command_center_v2.js` | Filtres provisoires mobiles ; Cancel restaure et Apply lance une seule lecture. Comportement desktop conservé. |
| B | `business_theme.css`, registre `colors` dans `business_command_center_v2.js` | Couleurs stables par identifiant et surfaces sobres ; pas de déplacement desktop. |
| C | `resource_detail.html` | Lien Open document uniquement en présentation compacte, vers le raw URL déjà protégé ; header et métadonnées du lecteur sans débordement. |
| D | `homepage_command_center.js` et règles d'état ciblées dans `responsive.css` | Réponse/contextes périmés ignorés, anciens chiffres cachés, erreur explicite, emplacements de chargement conservés. |
| D | `codex_chatbot/static/codex_chatbot/chatbot.js` | Respect de la lecture des anciens messages et action Latest messages ; mécanismes de rendu sécurisé et moteur conservés. |
| D | `business_command_center_v2.js` | Contexte URL Mining Turnover retrouvé lors d'un retour ; l'ancienne liste des vues acceptées omettait `turnover`. Correction liée au nouvel interrupteur responsive. |
| Tests / preuves | `reports/test_responsive_presentation.py`, `tests/presentation/`, `.gitignore`, les deux présents guides et le pointeur dans `docs/MINING360_HANDOFF_2026-09-18.md` | Contrats, jeux isolés, Edge, matrice, captures, mesures, état exact de livraison ; artefacts privés ignorés. |

Les graphiques, exports et scripts de copie existants restent utilisés. Les SVG
larges disposent d'une zone de lecture locale sur petit écran ; la période,
granularité et échelle métier ne sont pas recalculées. Les détails repliables
déplacent le vrai composant puis le remettent à sa place au retour desktop :
aucun formulaire, tableau ou gestionnaire actif n'est dupliqué.

Le spinner partagé a été inspecté : il est déjà informatif et utilise
`pointer-events:none`. Le CSS compact le transforme en petit indicateur, sous
les panneaux de navigation. Son JavaScript, le comptage des requêtes, les
boutons désactivés et les protections de mutation sont inchangés.

## Breakpoints et préférences

- `<768px` : header compact, navigation inférieure, contenu et safe areas.
- `768–1199px` : header et tiroir, grilles intermédiaires ; pas de seconde barre fixe.
- `>=1200px` : styles/disposition desktop d'origine, hors lot B et correction D explicitée.

La préférence `nav-collapsed` et la préférence propre au viewer ne sont jamais
réécrites par le tiroir. Les onglets Business restent sous le titre. Le focus
revient au déclencheur, Escape ferme les panneaux ; les états provisoires des
filtres sont annulés lors du retour au desktop. Les redimensionnements n'appellent
aucune API métier dans la nouvelle couche.

## Registre Business

| Identifiant | Couleur |
|---|---|
| `machine` | `#FFCC00` |
| `parts` | `#2563EB` |
| `service` | `#0F766E` |
| `rental` | `#7C3AED` |
| `total` | `#111827` |
| `unclassified` | `#64748B` |

Source commune : variables `--bo-*` du CSS, lues par les graphiques natifs.
Les couleurs ne dépendent pas de l'ordre des résultats. Périmètre strict :
`.bcc-body` et `.pf-body`. Statuts, comparaisons temporelles et cohortes Parts
restent des registres distincts. Le SVG et la copie PNG utilisent les mêmes
styles résolus ; aucun CSS n'est injecté dans une iframe Power BI.

## Désactivation / retour arrière

Les deux variables d'environnement du processus Django sont indépendantes :

```powershell
$env:MINING360_RESPONSIVE_UI_ENABLED = '0'
$env:MINING360_BUSINESS_THEME_ENABLED = '0'
```

Relancer le **processus local autorisé**, puis recharger le document. La
désactivation responsive enlève ses assets, ses listeners, sa navigation et les
réservations d'espace. Désactiver uniquement le thème conserve le responsive
avec les couleurs précédentes. Les tests vérifient les deux combinaisons et
comparent le rendu legacy. Les attributs/éléments des tableaux et navigateurs
sont également remis en place après le cycle compact → desktop.

Ces commandes ne redémarrent aucun service et n'ont pas été appliquées à BODEFM.
L'acheminement de ces variables par son lanceur devra être vérifié dans une
promotion autorisée. Le tag `bodefm-validated-2026-11-14` reste intact ; les
fichiers gelés `deployment/bodefm-runtime-static/` n'ont pas été remplacés.
Une future livraison devra reconstruire/vérifier `collectstatic` et son manifeste
dans le workflow approuvé, et non réutiliser les anciens hashes pour les nouveaux assets.

## Viewer et lots ultérieurs

Le projet charge le SDK local Power BI **2.23.7**. Les symboles `hasLayout`,
`MobilePortrait` et `updateSettings` sont présents dans son fichier distribué.
La documentation [Microsoft sur les layouts mobiles](https://learn.microsoft.com/en-us/javascript/api/overview/powerbi/mobile)
prévoit une vérification par page ; cela ne démontre pas qu'un rapport possède
effectivement ce layout. Les 14 viewers de l'index restent à auditer par page
avec leurs identités autorisées. Aucun n'est déclaré dépourvu de layout sur la
seule base d'une capture. Le [guide de mise à jour des paramètres](https://learn.microsoft.com/en-us/javascript/api/overview/powerbi/update-settings)
décrit les limites des changements runtime ; aucune modification de ce cycle
n'est activée ici. Prime Movers conserve les identités distinctes Power BI/Power Apps.

Optimisation des appels/caches, layouts mobiles Power BI et éventuelle PWA sont
des lots séparés. Aucun service worker, cache de données privées, mode hors ligne,
changement de connexion ou nouvelle API n'a été ajouté.

## Publication et déploiement ciblé

Après la livraison locale, l'utilisateur a demandé explicitement le push puis
le déploiement BODEFM. La branche dédiée est publiée ; `main` et le tag de
référence ne sont pas déplacés par cette publication.

`deployment/windows/deploy_responsive.ps1` adapte le workflow ciblé déjà utilisé
pour Parts Fulfillment : 12 chemins applicatifs autorisés, 7 assets avec leurs
variantes hashées/gzip, manifeste statique fusionné et sauvegarde vérifiée sous
`D:\Mining360Backups\Responsive_*`. Il contrôle les empreintes avant bascule,
la propriété du processus sur le port 8000 et les 7 fichiers métier protégés.
Il conserve les entrées statiques étrangères au lot, les secrets, les données,
les migrations et les définitions des tâches. Aucun pip, migrate, SQL/IIS restart
ou nettoyage d'autres versions ne fait partie de ce script.

Le manifeste n'est pas une constante d'application : il est construit depuis
un commit immuable et les fichiers réellement inventoriés sur le serveur.
Les noms hashés sont vérifiés avec le stockage manifeste Django. La bascule ne
commence qu'après sauvegarde de chaque ancienne cible et validation des sources.
Un échec restaure les fichiers sauvegardés puis relance la tâche existante.
Le retour arrière refuse les modifications concurrentes étrangères au paquet.

Commande transparente, uniquement avec les chemins exacts du reçu de livraison :

```powershell
& 'C:\Mining360\control\responsive-<commit8>\deploy_responsive.ps1' -Manifest 'C:\Mining360\control\responsive-<commit8>\manifest.json'
# Retour arrière du même paquet, après contrôle du reçu et de ses empreintes :
& 'C:\Mining360\control\responsive-<commit8>\deploy_responsive.ps1' -Manifest 'C:\Mining360\control\responsive-<commit8>\manifest.json' -Rollback -BackupPath 'D:\Mining360Backups\Responsive_<timestamp>_<commit8>'
```

Ces exemples contiennent des placeholders et ne sont pas des commandes prêtes
à exécuter. Le reçu BODEFM final distingue préparation, installation et contrôles
effectivement réussis ; la présence du script sur Git ne vaut pas déploiement.
