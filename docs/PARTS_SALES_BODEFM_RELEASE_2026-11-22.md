# Sales → Parts : livraison BODEFM du 22 novembre 2026

## État installé et autorisation

**Déployé et validé** sur `https://mining360.neemba.com/`, Business Overview →
Sales → Parts Classification. L'utilisateur a donné Go, confirmé SSH Running et
port 22 en écoute, puis reçu l'annonce avant la bascule. Ce Go autorisait cette
livraison immédiate ; les autres livraisons conservent la règle du soir avec Go.

- Branche publiée : `feature/parts-sales-alignment-20261118`.
- Commit de livraison : `76197c7a42310e0fcbd5051115c1f3ceba12c9f7`.
- Code applicatif de l'évolution : `17bfc408b8580f260ea130e7882ed40a3f1daab6`.
- Cible gérée approuvée, clé SSH épinglée, 26 fichiers comparés avant préparation.
- 23 cibles installées ; 35 empreintes de fichiers installés ou protégés
  revérifiées après l'import réel.
- Deux mappings JS/CSS remplacés parmi 212 entrées statiques ; autres mappings
  conservés et variantes gzip vérifiées.
- Migrations 0151/0152 appliquées ; précision Pièces `decimal(28,10)`.
- Catalogue vérifié du poste installé : 960 789 références CAT. Aucun mapping
  métier publié et aucune mesure/relation Power BI modifiée.

Une relance ciblée de Mining360 a été nécessaire ; aucun redémarrage IIS/SQL
global, changement de certificat, rôle, secret ou connexion n'a été effectué.

## Données activées

L'import automatique a commencé à **14:35:15 UTC** et s'est terminé à
**14:45:47 UTC**. La fenêtre demandée va du 1er janvier 2025 au 22 novembre 2026 ;
la dernière écriture disponible est le **20 novembre 2026**. Les données récentes
de la source expliquent les écarts YTD avec la copie locale, restée au snapshot
Revenue du 15 novembre. Les chiffres d'octobre restent ceux de la recette.

- Run : `0b66d6a9-f74b-4de7-a636-508d49f4a4c4`.
- 60 551 groupes comptables ; CA source 471 857 165,8924602 EUR sur cette fenêtre.
- 320 146 groupes Pièces attribués ; 318 093 391,9740500002 EUR réconciliés.
- Anciennes lignes hors fenêtre conservées ; lignes remplacées gardées inactives.
- Statut `Completed with Warnings` : 8 751 groupes sans lignes correspondantes,
  neuf sans client comptable unique et deux avec poids net nul. Ces exceptions
  restent dans le résiduel ; elles ne prouvent pas l'absence de factures ni un
  caractère non opérationnel du CA.
- Refresh activé sur le calendrier Business Overview existant : 05:00 GMT.
  Il lit le modèle existant, sans déclencher son actualisation Power BI.

| Indicateur | Octobre 2026 | YTD au 22 novembre |
| --- | ---: | ---: |
| CA certifié | 20 100 153,90 EUR | 224 200 353,37 EUR |
| CA relié aux lignes | 19 281 855,70 EUR | 176 869 233,93 EUR |
| Matched to Invoice Lines | 95,93 % | 78,89 % |
| CAT classifié | 16 339 832,86 EUR | 144 361 910,20 EUR |
| Autres marques | 2 448 911,67 EUR | 24 174 603,41 EUR |
| CA sans liaison aux lignes | 818 298,21 EUR | 47 331 119,44 EUR |
| Allocations de lignes | 21 081 | 211 711 |

Ces taux concernent les lignes de facture, avec le même CA comptable que Parts
Orders & Sales Fulfillment. L'attribution de cette dernière page à une commande
unique et datée conserve une définition différente. En octobre, son Unallocated
vaut 824 169,24 EUR ; aucune attribution n'a été forcée pour égaliser les résiduels.

## Recette et préservation

89 tests SQL locaux de l'évolution et trois tests SQL supplémentaires du rollback
passent. Sur BODEFM, les agrégats Revenue et leur identifiant d'import ont la même
empreinte avant/après ; le rôle/scope des comptes contrôlés est inchangé. Le lecteur
Business Overview existant conserve HTTP 200, l'autre lecteur HTTP 403, et Config
reste HTTP 403 pour les deux. Cela ne remplace pas un audit exhaustif de tous les
comptes ou de toutes les attributions métier.

Edge en HTTPS strict a validé les chiffres, l'absence de la notice Machines dans
Parts et les largeurs 1600/1024/390 sans débordement de page ni exception JavaScript.
L'export PPC demandé depuis une vue de cinq groupes sur la page 2 contient les
**570 groupes** du périmètre ; montant et allocations réconcilient la synthèse.
L'API Parts Fulfillment confirme le même CA d'octobre. Les sessions temporaires
ont été supprimées ; aucun e-mail n'a été envoyé.

Observations de performance, sans garantie de délai :

- Service Revenue sans cache avant : 2,094 / 1,093 / 1,032 s ; après :
  1,735 / 1,046 / 0,954 s, mêmes empreintes financières.
- Edge avant : 24,786 / 4,159 s ; après : 4,755 / 2,104 s.
- Onglet Parts : 5,096 s avant, 3,908 s après.

Le premier chargement avant est dispersé ; sa cause n'a pas été établie. Ces
mesures ne montrent pas de régression répétée. Index actif Revenue, précision,
maintenance ciblée des statistiques et services de permissions sont conservés.

## Sauvegardes et retour arrière

Sauvegarde SQL COPY_ONLY compressée, CHECKSUM, vérifiée par RESTORE VERIFYONLY :
`D:\Mining360Backups\PartsSalesData_20261122_76197c7a\Mining360App_before_parts.bak`.
Le reçu et son SHA-256 sont dans le manifeste de validation. Le même dossier
conserve les identifiants/hashes des anciennes lignes actives pour le rollback.

Sauvegarde des fichiers :
`D:\Mining360Backups\PartsSales_20261122_063444_76197c7a`.
L'heure du nom de dossier est l'heure locale du serveur, distincte des heures UTC
des runs Django. Aucune restauration n'a été nécessaire.

Retour arrière ciblé, après décision opérateur :

```powershell
& 'C:\Mining360\control\parts-sales-76197c7a\deploy_parts_sales.ps1' -Manifest 'C:\Mining360\control\parts-sales-76197c7a\manifest.json' -Rollback -BackupPath 'D:\Mining360Backups\PartsSales_20261122_063444_76197c7a'
```

Le runtime identifié est arrêté, les anciens états actifs rétablis dans une
transaction, les nouveaux détails conservés inactifs et les fichiers restaurés
après vérification des hashes. La précision et le catalogue restent en place.
Un import distinct actif ou une modification concurrente bloque la restauration.
Ne jamais restaurer toute la base après de nouvelles activités métier.

Manifestes versionnés : [package](../deployment/parts-sales-20261122/manifest.json),
[validation](../deployment/parts-sales-20261122/validation.json).
Preuves privées : `.runlogs/parts-sales-deploy-20261122/` à la racine canonique ;
catalogue compressé et données détaillées hors Git.
