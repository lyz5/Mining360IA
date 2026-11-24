# Parts Fulfillment : livraison BODEFM du 24 novembre 2026

**Déployé et validé** après la demande « déploie », confirmation SSH Running/port
22 en écoute et annonce avant bascule. La préparation et les 41 tests locaux
précèdent cette promotion ; aucune correction directe de production n'a été faite.

- Commit applicatif : `ef76b01cad58aacd95edd4ebf5abd24fc9af8d5c`.
- Branche : `feature/parts-fulfillment-current-month-20261124`, poussée sur Git.
- Route : `/business-review/parts-fulfillment/`.
- Quatre fichiers applicatifs : service, template, JS, CSS. Treize cibles avec
  assets/gzip/manifeste ; 24 fichiers de référence vérifiés avant, 33 empreintes
  installées ou protégées revérifiées après.
- Deux mappings statiques remplacés parmi les 212 entrées, autres mappings conservés.
- Une relance ciblée de Mining360 ; pas de redémarrage IIS/SQL global, migration,
  import métier, changement de connexion, certificat, rôle ou modèle Power BI.

## Recette réelle

La page sans paramètre de mois affiche **novembre 2026**, conserve douze mois de
tendance et présente les montants Actual vs Last Month MTD avec dates explicites.
Octobre reste sélectionnable ; le bouton Current month revient au défaut et
retire le mois fixé de l'URL. Refresh conserve ce mode.

| KPI | Actuel EUR | Référence MTD EUR | Variation | Dates comparées |
| --- | ---: | ---: | ---: | --- |
| Commandes | 17 774 111,89 | 11 343 585,70 | +56,69 % | 1–24 nov. / 1–24 oct. |
| CA comptable | 9 942 490,01 | 12 139 292,43 | −18,10 % | 1–23 nov. / 1–23 oct. |

Valeurs de contrôle du 24 novembre, non constantes applicatives. Le CA d'octobre
reste 20 100 153,90 EUR. Les mesures et valeurs de toute la série avant/après
correspondent au centime ; les cohortes et leur réconciliation sont conservées.
Last Month MTD des KPI est une période de comparaison, distincte de la cohorte
`[CA Last Month]` dans la barre d'origine des ventes.

Edge en HTTPS strict : défaut courant, références et variations, sélection
d'octobre, retour courant, Refresh et largeurs 1600/1024/390 validés. Aucun
débordement de page ni exception JavaScript observé. Sessions temporaires des
comptes existants supprimées ; aucun e-mail envoyé.

Empreinte des agrégats Revenue et identifiant d'import inchangés ; droits et
scopes enregistrés inchangés. Le lecteur Business Overview garde HTTP 200,
l'autre lecteur HTTP 403, Config HTTP 403 pour les deux. Ce contrôle ciblé ne
constitue pas un audit exhaustif de toutes les identités ou attributions.

Observations sans garantie de délai : service Revenue sans cache avant
1,391 / 1,093 / 0,969 s ; après 1,343 / 1,125 / 1,063 s. L'index actif et la
précision Revenue sont conservés. Parts Fulfillment dans Edge : 14,694 s au premier
chargement après redémarrage, 0,334 s au suivant. Il n'existe pas de mesure froide
navigateur avant comparable pour cette page ; ces observations ne prouvent pas un
gain de vitesse. Les lectures initiales dépendent du modèle et du connecteur.

## Sauvegarde et rollback

Dossier : `D:\Mining360Backups\PartsCurrent_20261124_113150_ef76b01c`.
Le nom utilise l'heure locale du serveur ; l'opérateur sauvegarde et vérifie les
seuls fichiers remplacés. Aucune restauration n'a été nécessaire.

Retour arrière ciblé, après décision opérateur :

```powershell
& 'C:\Mining360\control\parts-current-ef76b01c\deploy_parts_current.ps1' -Manifest 'C:\Mining360\control\parts-current-ef76b01c\manifest.json' -Rollback -BackupPath 'D:\Mining360Backups\PartsCurrent_20261124_113150_ef76b01c'
```

L'opérateur réutilise le workflow ciblé validé du déploiement Turnover, avec
substitution des seuls chemins et contrôles de périmètre. Hash divergent ou
processus non identifié : arrêt de la mutation. Aucun état métier n'est restauré.

Preuves versionnées : [manifeste](../deployment/parts-current-20261124/manifest.json),
[validation](../deployment/parts-current-20261124/validation.json), opérateur et
contrôle dans le même dossier. Captures privées et contrôleur local :
`.runlogs/parts-current-deploy-20261124/`. L'adaptateur privé de lecture utilisé
pour les tests du poste n'est pas déployé sur BODEFM.
