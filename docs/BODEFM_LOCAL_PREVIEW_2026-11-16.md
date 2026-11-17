# Mining360 BODEFM sur localhost — instance de recette isolée

**Mise à jour du 17 novembre :** les e-mails réels sont autorisés et fonctionnent
sur localhost via le flow dédié Outlook; 45 tests SQL passent. Le bandeau indique
Real email delivery et la boîte locale n'expose plus de codes. Les autres accès
externes restent bloqués. Voir [la note de livraison e-mail](EMAIL_SIGNIN_REAL_DELIVERY_2026-11-17.md).
Les descriptions de capture fichier ci-dessous conservent la phase initiale de recette.

Instance démarrée et testée sur **ce poste**, URL `http://localhost:8016/`. Elle ne remplace
pas BODEFM et ne partage ni sa base, ni ses cookies, ni ses connexions.

## Références inspectées

- `docs/LOCAL_FIRST_DEVELOPMENT_STANDARD_2026-10-15.md` : Local → Git → BODEFM.
- `docs/MINING360_MININGPROD_LOCAL_PLATFORM_PLAN_2026-10-15.md` : SQL Server local.
- `docs/Mining360_Control_Center.md`, `docs/CONTROL_CENTER_REPAIR_2026-09-19.md`
  et `desktop/project_environment.py` : le lanceur historique utilise SQLite,
  le port 8001 et démarre aussi des traitements. Il n'est pas utilisé pour cette
  recette SQL isolée et reste inchangé.
- `command-center/README.md` : le 360 Global Command Center du portefeuille
  (vue web sur 8030) est distinct du Business Command Center de Mining360.
- `docs/BODEFM_BUSINESS_OVERVIEW_PARITY_PERFORMANCE_2026-10-10.md` : conservation
  de l'index filtré et des contrôles financiers du Business Overview.

Le Business Command Center est la route applicative
`/business-review/command-center/`. Il lit les buffers Revenue et le Mapping
publié de la base locale. Il ne faut pas le confondre avec l'outil desktop.

## Code et données

Code de référence : BODEFM `f81a3ad37e8b956f4a932a22db3320ab156095f5`, auquel
s'ajoutent les modifications locales non publiées de connexion e-mail/code.
Worktree : `.release-worktrees/email-code-signin`.

La sauvegarde existante du 15 novembre est copiée par SFTP en lecture seule :
`Mining360App_before_expired_cleanup_20261115_154735_ea52880c.bak`.
Aucune nouvelle sauvegarde n'est créée sur BODEFM et aucun service distant n'est
arrêté. Cette sauvegarde précède la purge des anciennes versions du Revenue :
elle contient davantage d'historique inactif que le serveur après maintenance.
C'est un snapshot daté, pas une synchronisation temps réel du 16 novembre.

Restauration cible exclusivement : `localhost\MSSQL_IA`, SQL Server 2022,
base **Mining360App_BODEFM_Local_20261116**. Les scripts refusent de remplacer
une base ou des fichiers existants. La base historique `Mining360App_Dev` et
`Miningprod_test_Local` restent indépendantes.

La restauration doit vérifier les checksums natifs SQL. La préparation compare
l'empreinte des agrégats Revenue actifs et des droits avant/après la nouvelle
migration, son retour arrière, sa réapplication et l'isolation des intégrations.
L'index `bo_active_revenue_cover_20261010` et la précision réelle `numeric(28,10)`
doivent rester présents. Le modèle et les calculs métier ne sont pas reconstruits.

## État validé le 16 novembre

Restauration complète avec checksum réussie. Application/base : `ok`. La nouvelle
migration passe application → retour arrière → application. Empreintes du Revenue
actif et des rôles/scopes conservées. Le compte de recette existant se connecte
dans Edge avec un code capturé; Config et Users lui restent accessibles. Les
tests refusent Config au viewer. 37 tests SQL passent, dont concurrence et CSRF.
Zéro erreur JavaScript dans le parcours vérifié, login sans débordement en
1440/390 px. Le cœur Business Overview répond HTTP 200 en 4,247 secondes après
connexion, avec ses vrais graphiques et agrégats SQL.

Moteur local : SQL Server 2022 `16.0.1000.6`; Python 3.13.15, Django 6.0.6.
Une attente `CXSYNC_PORT` a été observée pendant la recette. `MAXDOP=1` est appliqué
à **cette seule base**, avec empreinte Revenue inchangée. La configuration globale
du moteur SQL et BODEFM restent inchangés. Ce réglage n'est pas une mise à jour SQL
ni une preuve de parité de performance avec la production.

Les seuls compteurs locaux utilisés par le compte de recette automatique sont
réinitialisés pour permettre les essais manuels; les limites de l'application
restent actives et testées. Les reçus, captures et `browser-validation.json`
décrivent le périmètre vérifié. Les intégrations externes restent désactivées.

## Isolation

Le profil `Mining360IA.settings_local_preview` exige un opt-in explicite et
refuse BODEFM. Le runtime écoute uniquement `127.0.0.1:8016`; il refuse aussi les
hôtes et pairs HTTP externes. Les connexions ODBC sont limitées à cette base
locale et les sockets Python sortants vers des hôtes externes sont bloqués.

Sur la copie uniquement :

- les intégrations et cibles de déploiement sont désactivées et leurs secrets
  supprimés de la base de travail;
- les sessions copiées sont effacées et les mots de passe copiés rendus inutilisables;
- les rôles, utilisateurs actifs, groupes, permissions et périmètres sont conservés;
- aucune clé de déchiffrement de production n'est installée;
- une clé Django et une clé de chiffrement locales sont générées hors Git;
- aucun worker ni ordonnanceur de refresh n'est démarré;
- les e-mails sont capturés par le backend fichier, sans connexion SMTP.

Le bandeau LOCAL TEST indique la date du snapshot. La boîte de test est
`http://localhost:8016/__local__/mailbox/`. Utiliser une adresse déjà active dans
la copie de Config → Users. Cette boîte est un outil de recette **local**, jamais
une route du WSGI de production. Les identifiants et fichiers privés ne doivent
pas être exportés ou poussés sur Git.

## Démarrer et arrêter

Après préparation de la copie et création du reçu `ready.json` :

```powershell
# Depuis le worktree email-code-signin.
.\deployment\windows\start_mining360_bodefm_local.ps1 -StateDirectory '<dossier privé local-instance>'
```

Arrêt avec le Python du projet :

```powershell
python .\deployment\stop_local_preview.py --state-directory '<dossier privé local-instance>'
```

L'arrêt vérifie PID, date de création, chemin du code, arguments et enfants;
aucun arrêt opportuniste par port. Si le port est déjà occupé, le démarrage
préserve le processus présent et refuse une seconde instance.

Les reçus et logs sont dans
`.runlogs/email-code-signin-20261116/local-instance/`. Consulter `ready.json` et
`browser-validation.json` pour l'état réellement atteint, sans confondre la
procédure décrite avec sa validation.

## Limites de la recette

Le Business Overview peut utiliser ses snapshots SQL sans accès externe.
Les rapports intégrés Power BI, AD, IA et les requêtes live Parts Fulfillment
nécessitent leurs connexions externes : elles sont volontairement désactivées.
Leurs états indisponibles ne doivent pas être remplacés par des chiffres fictifs
ni interprétés comme une panne BODEFM. Le cache Parts du runtime BODEFM est en
mémoire; un backup SQL ne copie pas ce cache et ne restaure pas FactSalesAllocation.

Cette instance sert d'abord à valider le parcours de connexion et les droits,
puis les parcours applicatifs compatibles avec les données locales. Elle ne
prouve ni l'envoi d'un e-mail réel, ni tous les périmètres Power BI délégués, ni
une parité de performance réseau avec BODEFM. Aucun push ou déploiement distant
n'est autorisé avant le Go de l'utilisateur.
