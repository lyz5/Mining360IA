# Livraison commune — totaux Mining Turnover et accès Business Overview

## Autorisation

Après validation locale des totaux, l'utilisateur a demandé « déploie maintenant »
et signalé le correctif d'accès réalisé dans l'autre session. Ce Go autorise cette
livraison commune maintenant ; la règle habituelle du soir reste applicable aux
autres livraisons. Le correctif d'accès a été retrouvé dans le même worktree,
revu et conservé. Les comptes et leurs rôles ne sont pas réattribués.

## Périmètre préparé

Quatre fichiers applicatifs : `Mining360IA/settings.py` pour les neuf rollouts de
lecture, le template `business_command_center_v2.html` et ses fichiers JS/CSS
pour les totaux. Les contrôles de rôle Business Overview, Account/MineSite,
Config, écriture et export restent dans leurs services inchangés.

La source part de `bb4710f`, dont les fichiers applicatifs correspondent à la
livraison e-mail/code BODEFM. Les seules références statiques modifiées sont
celles du JS et CSS du tableau. Les variantes gzip sont régénérées et le
manifeste statique est fusionné en conservant les autres entrées.

Le précontrôle BODEFM a confirmé SSH Running, clé épinglée, cible approuvée,
santé application/base `ok` et capacité disque suffisante. Aucun des neuf
rollouts concernés n'a de surcharge machine, opérateur ou SYSTEM : aucune
variable d'environnement ne doit être modifiée pour activer les nouveaux défauts.

## Sauvegarde et rollback

`deployment/windows/deploy_turnover_totals.ps1` reprend le workflow ciblé déjà
utilisé pour la présentation : inventaire et hash avant copie, sauvegarde des
seuls fichiers existants sur D:, arrêt du runtime identifié, copie contrôlée,
relance et santé. Une erreur après modification déclenche la restauration de
ces mêmes fichiers. Un fichier modifié concurremment bloque l'installation ou
la restauration. Les onze fichiers protégés incluent les services Revenue/RLS,
les rôles, les modèles et la connexion e-mail.

Aucune migration, modification SQL, clé, configuration de connexion, changement
IIS/certificat ou refresh de source n'est demandé. Les sessions de contrôle
temporaires doivent être supprimées. Le résultat effectif et le dossier de
sauvegarde seront consignés dans le reçu de promotion.


## Résultat effectif — 18 novembre 2026 UTC

**Installé et contrôlé sur BODEFM** après notification à l'utilisateur avant la
bascule. Le nom du dossier conserve le début de préparation du 17 novembre.

- Commit applicatif : `81f408c481f05aa287e641ae0d0fc30e62630274`.
- Branche publiée : `feature/mining-turnover-totals-20261117`.
- Treize cibles et onze fichiers protégés vérifiés par SHA-256 après recette.
- Les 212 références statiques sont conservées ; seuls les deux mappings JS/CSS
  sont actualisés, avec variantes gzip vérifiées.
- Sauvegarde : `D:\Mining360Backups\TurnoverTotals_20261117_210911_81f408c4`.
- 33 tests SQL locaux, dont les huit tests de rôle, et neuf contrôles Edge locaux.
- Sept contrôles Edge live en HTTPS strict : montants de tous les totaux,
  document sans débordement en 1440/1024/390 et santé HTTP 200.
- Compte Business Overview existant, non Super Admin : HTTP 403 avant, HTTP 200
  après. Autre compte sans ce rôle : HTTP 403. Config : HTTP 403 en JSON pour
  les deux. Les comptes, mots de passe, rôles, groupes et scopes sont conservés.
- Mêmes agrégats financiers et même import avant/après ; index actif et précision
  `numeric(28,10)` conservés. Aucun refresh demandé, migration ou mutation des
  données métier ; seules les sessions de recette et leurs métadonnées normales
  de connexion ont été créées puis les sessions supprimées.
- Une seule relance ciblée du runtime Mining360 ; aucun redémarrage IIS/SQL,
  changement de certificat, de variable d'environnement ou de connexion.
- Sessions temporaires supprimées ; aucun e-mail envoyé.

Les temps ont varié : premier calcul avant installation de 246,859 s, puis
1,141 / 1,000 s ; premier groupe après de 2,313 / 3,640 / 3,641 s. L'import quotidien
s'était achevé à 05:00:57 UTC ; sa causalité avec la première lenteur n'est pas
établie. Cinq mesures supplémentaires justifiées par cette dispersion donnent
1,328 / 1,032 / 1,015 / 1,063 / 1,672 s (médiane 1,063 s), mêmes montants/source,
sans requête SQL active observée en fin de contrôle. Aucune modification de
requête, cache ou réglage SQL n'a été appliquée. Edge : 4,624 / 1,031 s avant,
4,156 / 1,639 s après. Ces observations ne constituent pas une garantie de délai.

Voir [le manifeste](../deployment/turnover-role-20261117/manifest.json) et
[le reçu](../deployment/turnover-role-20261117/validation.json).

Retour arrière ciblé, après décision opérateur :

```powershell
& 'C:\Mining360\control\turnover-totals-81f408c4\deploy_turnover_totals.ps1' -Manifest 'C:\Mining360\control\turnover-totals-81f408c4\manifest.json' -Rollback -BackupPath 'D:\Mining360Backups\TurnoverTotals_20261117_210911_81f408c4'
```

Aucun rollback n'a été nécessaire. Les premiers dossiers préparés, non activés,
ne sont pas des versions installées. Les tests de tous les rôles et périmètres
Power BI restent hors du périmètre de cette recette ciblée.
