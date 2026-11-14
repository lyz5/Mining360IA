# Responsive Mining360 — livraison BODEFM du 14 novembre 2026

Le push puis le déploiement ont été explicitement demandés après la validation
locale. La présentation responsive est installée sur **https://mining360.neemba.com**.

## Références et récupération

- Base exportée de BODEFM : `401b973`, tag `bodefm-validated-2026-11-14`, inchangé.
- Code applicatif responsive : `237c6e9`.
- Commit réellement livré : `8460c2d55e850c592f327fd8b31ece8ee62fd0ce`.
- Branche poussée : `feature/responsive-desktop-protected-20261114` ; `main` n'a pas été déplacé.
- Contrôle : `C:\Mining360\control\responsive-8460c2d5`.
- Sauvegarde vérifiée : `D:\Mining360Backups\Responsive_20261114_124548_8460c2d5`.
- Log : `C:\Mining360\logs\responsive-8460c2d5.log`.
- [Manifeste des 41 cibles](../deployment/responsive-20261114/manifest.json).
- [Reçu des contrôles](../deployment/responsive-20261114/validation.json).

La première tentative `e9e72dc` a été refusée avant toute modification : son
contrôle mentionnait `site_access.py`, absent de la référence. `8460c2d` protège
le vrai fichier `business_review_access_service.py`. Les sources applicatives
responsive n'ont pas changé entre ces deux paquets.

## Installation et protections

Le workflow ciblé existant a été adapté, sans remplacement complet du répertoire
applicatif : 12 fichiers applicatifs, 7 assets avec variantes hashées/gzip et le
manifeste statique fusionné. Les 207 clés existantes sont conservées : trois
références JavaScript sont actualisées, les 204 mappings non concernés sont
inchangés et quatre clés sont ajoutées, soit 211 entrées. Aucun jeu de fixtures, serveur de
test, fichier de credentials ou export privé n'est installé dans l'application.

Les 41 empreintes installées et les 7 empreintes protégées ont été revérifiées.
Les 28 lectures HTTP des assets, avec demandes identity/gzip, correspondent aux
octets sources attendus après décompression. L'application et la base répondent
`ok` ; les deux routes financières anonymes renvoient vers la connexion.

Seule la tâche de runtime Mining360 a été arrêtée puis relancée. Aucun migrate,
pip, refresh de source demandé, publication de mapping, modification des secrets,
redémarrage SQL Server/IIS, suppression d'autres versions ou modification SSH/firewall
n'a été effectué. Les actions sont consignées dans le DeploymentAuditLog local
et le log de livraison BODEFM.

## Vérifications sur données réelles

Le compte web testé correspond à l'identité SSH autorisée via son profil existant.
Aucun autre administrateur n'a été substitué. Les sessions temporaires ont été
supprimées après les contrôles ; aucune valeur de session n'est publiée ici.

- Sept pages authentifiées : HTTP 200 avant et après.
- Six comparaisons financières : même import source et mêmes empreintes des
  agrégats avant/après, en Mining, YTD toutes activités, MTD toutes activités et
  YTD Parts, avec deux lectures par contexte.
- Index Revenue actif `bo_active_revenue_cover_20261010` présent et activé.
- 30 contrôles Edge aux largeurs 390, 1024 et 1440 px, cycle retour desktop inclus :
  aucun débordement du document ni exception JavaScript ; aucun appel métier au resize.
- Quatre reprises ciblées Excellence après chargement complet : mêmes contrôles réussis.
- More s'ouvre et se ferme au clavier avec restitution du focus/contenu.
- Business Overview et Parts affichent les données réelles ; les deux graphiques
  métier restent calculés par les services et mesures existants.

La géométrie desktop observée est identique pour Business, Parts, Reporting,
Chatbot, Resources et Reporting Configuration. La capture Excellence initiale
était encore en chargement : elle n'est pas utilisée comme preuve de comparaison
du résultat final. Les huit comparaisons desktop locales sur fixtures stabilisées
restent le contrôle visuel déterministe de référence.

## Temps observés et limites

Business Overview, médiane de trois navigations Edge :
**1.386 s avant / 1.097 s après**.
Premières navigations : 2.512 s / 3.009 s.
Les contextes navigateur sont neufs par phase, les caches serveur restent ceux
de l'application et le redémarrage change leur état. Ce sont des observations,
pas un gain de performance certifié ni un p75 terrain.

Les calculs serveur sans cache ont été lus deux fois par contexte. La dispersion
MTD après redémarrage a motivé cinq lectures supplémentaires : médiane
**0.906 s**, mêmes agrégats et même source. Aucun changement
de requête/cache n'a été appliqué pour obtenir ce résultat.

Les [92 tests Django et 330 contrôles de format locaux](RESPONSIVE_VALIDATION_2026-11-14.md)
gardent leur portée et leurs limites. Téléphones physiques, Firefox/WebKit,
parcours réel Windows/AD, identités non administrateur/RLS et layouts internes
des rapports Power BI restent non revalidés par cette livraison. Aucun test de
mutation administrative, envoi IA ou export métier réel n'a été ajouté en production.

Captures privées : `exports/Mining360_Responsive_BODEFM_2026-11-14/INDEX.html`.
Les captures sur données de test initiales restent dans leur dossier séparé.

## Retour arrière ciblé

```powershell
& 'C:\Mining360\control\responsive-8460c2d5\deploy_responsive.ps1' -Manifest 'C:\Mining360\control\responsive-8460c2d5\manifest.json' -Rollback -BackupPath 'D:\Mining360Backups\Responsive_20261114_124548_8460c2d5'
```

Cette commande restaure uniquement ce paquet, après vérification des sauvegardes
et de l'absence de modifications concurrentes. Elle interrompt brièvement
Mining360 et doit être exécutée dans une fenêtre autorisée. Aucun retour arrière
n'a été exécuté pendant cette livraison réussie. Les interrupteurs indépendants
sont décrits dans [le guide responsive](RESPONSIVE_DESKTOP_PROTECTED_2026-11-14.md).
