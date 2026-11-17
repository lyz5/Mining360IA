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
