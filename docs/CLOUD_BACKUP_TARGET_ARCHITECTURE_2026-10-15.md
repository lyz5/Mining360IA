# Architecture cloud cible pour la continuité des projets

Décision recommandée le 15 octobre 2026.

## Décision

Utiliser **un tenant Microsoft Azure personnel dont Papa Djibril Diagne est le
propriétaire et le responsable de facturation**, créé avec une adresse personnelle
durable, jamais avec l'adresse Neemba, comme plateforme centrale de continuité.
Ce tenant doit rester accessible après un changement d'employeur ou de poste.

Il comprend :

- **Azure Blob Storage** pour les sauvegardes de code, bases, médias, documents,
  exports, configurations non secrètes et preuves ;
- **Azure Key Vault** pour les mots de passe, jetons, clés de chiffrement,
  certificats privés et accès de secours ;
- **Microsoft Entra ID** avec MFA et RBAC pour contrôler les accès ;
- GitHub comme source de collaboration du code, complété par des bundles Git et
  archives de restauration dans Blob Storage.

Azure constitue ici une plateforme commune, pas un dossier unique ni un serveur
unique. Un abonnement créé sur le portail Azure est hébergé dans le tenant Entra
du compte propriétaire ; la propriété de facturation et les rôles Azure doivent
être contrôlés avec le compte personnel.

## Propriété personnelle et périmètres obligatoires

| Périmètre | Projets | Propriété | Règle |
| --- | --- | --- | --- |
| `PDD-PERSONAL` | Mayite, DSTV, site Pacdigitale, Marketing Digital, mémoire et documentation personnelle | Papa Djibril Diagne, compte et paiement personnels | aucune dépendance à l'adresse, au téléphone, au poste ou au tenant Neemba |
| `PDD-NEEMBA-AUTHORIZED` | copies autorisées de Mining 360, MiningProd, AGENTS.md, documentation et travaux MBA contenant des éléments Neemba | Papa Djibril Diagne, dans une souscription et un coffre séparés | aucune donnée, base, secret, code ou documentation confidentielle Neemba sans autorisation de conservation hors des systèmes Neemba |

La demande de continuité personnelle ne transfère pas la propriété intellectuelle
ou les obligations de confidentialité. Si Neemba n'autorise pas la conservation
d'un élément dans le compte personnel, cet élément reste dans les systèmes
Neemba. Le coffre personnel conserve alors un paquet de connaissance portable et
assaini : méthodes génériques, procédures personnelles, inventaire des compétences
et documentation sans données, secrets, URL internes, code propriétaire ou valeurs
métier confidentielles.

Cette séparation permet de garder un seul propriétaire personnel et une seule
plateforme, tout en empêchant le mélange des droits, des secrets et des règles de
conservation.

## Serveur de travail cloud personnel

Pour retrouver aussi l'environnement de développement après la perte du poste,
ajouter une **machine virtuelle Azure Windows** personnelle et chiffrée. Elle sert
de poste de reprise et peut héberger Git, les outils, IIS et les environnements de
développement autorisés. Elle ne doit pas être la sauvegarde unique.

La VM doit avoir :

- un disque système et un disque de données séparés ;
- le chiffrement des disques, l'accès administratif restreint et aucun port RDP
  exposé directement à Internet ;
- une extinction automatique lorsqu'elle n'est pas utilisée ;
- une sauvegarde dans un Recovery Services vault avec suppression réversible,
  immutabilité et alertes ;
- une reconstruction automatisable à partir des manifestes, dépôts et archives ;
- uniquement les composants Neemba dont l'utilisation hors poste professionnel a
  été autorisée.

Une VM facilite le travail, mais Blob Storage, Key Vault et les backups immuables
restent les sources de reprise.

## Configuration Azure recommandée

Créer un compte de stockage **StorageV2** par périmètre avec :

- réplication **RA-GZRS** lorsque la région et le budget le permettent ;
- accès public aux blobs désactivé ;
- authentification Entra ID, RBAC au moindre privilège et MFA ;
- clés d'accès partagées désactivées lorsque les outils de sauvegarde sont
  compatibles avec Entra ID ;
- pare-feu réseau et point privé pour le périmètre Neemba si son architecture le
  permet ;
- versioning des blobs ;
- suppression réversible des blobs et conteneurs pendant **90 jours** ;
- restauration ponctuelle et journal des changements lorsque disponibles pour le
  type de compte retenu ;
- politique d'immutabilité WORM sur les générations mensuelles validées ;
- journalisation Azure Monitor des accès et alertes sur suppressions, changement
  de politique et échec de sauvegarde ;
- règles de cycle de vie vers le niveau Cool pour les générations anciennes.

RA-GZRS combine la redondance de zone dans la région principale avec une copie
asynchrone dans une région secondaire et permet la lecture de cette copie. La
réplication seule ne protège pas contre une suppression logique ou un écrasement,
car l'opération est aussi répliquée. Le versioning, la suppression réversible et
l'immutabilité restent donc nécessaires.

Créer un **Key Vault** par périmètre avec :

- RBAC Azure ;
- suppression réversible à 90 jours ;
- protection contre la purge ;
- rotation et dates d'expiration pour les secrets qui le permettent ;
- journalisation des accès ;
- deux comptes administrateurs de secours protégés par MFA, sans utiliser le
  compte quotidien comme seul moyen de récupération.

Les secrets ne doivent jamais être rangés comme fichiers lisibles dans Blob
Storage, OneDrive, GitHub ou les manifestes. Les archives de données sensibles
doivent être chiffrées avant transfert ; la clé de déchiffrement doit rester dans
Key Vault ou dans un moyen de secours séparé du stockage.

## Organisation des sauvegardes

```text
continuity/
  manifests/
    portfolio/
    workstation/
    checksums/
  mining360/
    source/
    database/
    media/
    exports/
    evidence/
  miningprod/
    source/
    database/
    iis-config/
    evidence/
  mayite/
    source/
    database/
    media/
  dstv/
    source/
    database/
    media/
  pacdigitale/
    source/
    database/
    uploads/
    wordpress-inventory/
  marketing-digital/
    source/
    raw-exports/
    creatives/
    evidence/
  mba/
    deliverables/
    courses/
    references/
    research-data/
  workstation/
    software-manifest/
    restore-runbooks/
```

Chaque génération doit comporter un manifeste non secret indiquant le projet, la
date, le type de sauvegarde, le commit Git, la base, la taille, l'empreinte SHA-256,
le résultat du contrôle d'intégrité et la date du dernier test de restauration.

## Couverture par projet

| Projet | Contenu minimal à préserver |
| --- | --- |
| Mining 360 | bundle Git et changements réconciliés, backup SQLite cohérent puis SQL Server natif, médias, exports nécessaires, configurations non secrètes, preuves, clé de chiffrement dans Key Vault |
| MiningProd | source, backup natif de `Miningprod_test`, scripts et métadonnées, inventaire IIS, ACL et bindings sans secrets, documentation des browsers |
| Mayite | dépôt, dump MySQL, médias, manifestes de dépendances et procédure de restauration |
| DSTV | dépôt, dump MySQL, médias, manifestes de dépendances et procédure de restauration |
| Pacdigitale | thème, export MySQL WordPress, `wp-content/uploads`, inventaire plugins/thèmes et configuration non secrète |
| Marketing Digital | dépôt privé, exports Meta bruts, créations, rapports, captures et preuves ; tokens et accès dans Key Vault |
| MBA | Word/PDF, cours, références, anciens mémoires, données de recherche anonymisées et consentements selon leurs règles de confidentialité |

Une base SQLite active ne doit pas être copiée directement dans un dossier
synchronisé. Produire une sauvegarde cohérente avec l'API SQLite, contrôler
`PRAGMA quick_check`, puis chiffrer et transférer le fichier validé. Pour SQL
Server, MySQL et WordPress, utiliser les sauvegardes natives documentées dans le
runbook de continuité.

## Cadence et conservation cible

| Génération | Cadence | Conservation cible |
| --- | --- | --- |
| Critique incrémentale | quotidienne | 30 jours |
| Complète vérifiée | hebdomadaire | 12 semaines |
| Scellée et immuable | mensuelle | 12 mois |
| Archive annuelle | annuelle | 5 ans, sous réserve des politiques de confidentialité |

Une sauvegarde n'est validée qu'après contrôle des empreintes et test de lecture.
Une restauration à blanc d'au moins un projet doit être réalisée chaque mois ; un
exercice complet du portefeuille doit être réalisé chaque trimestre et avant tout
changement de poste.

## Rôle de OneDrive et GitHub

Un OneDrive personnel reste adapté aux documents Office en cours, grâce à
l'historique de versions, à la corbeille et à Files Restore. Il ne doit pas être
la seule sauvegarde des bases actives, des gros fichiers WAL, des médias, des clés
ou des archives de reprise. Le OneDrive professionnel Neemba ne doit contenir que
les éléments professionnels autorisés et ne doit jamais être la seule copie des
projets personnels.

GitHub reste la source du code versionné. Il ne contient ni bases, ni médias, ni
secrets. Chaque dépôt doit aussi être exporté périodiquement sous forme de bundle
Git dans Azure afin de permettre une reprise si le compte ou le service distant
est indisponible. Le dépôt Marketing Digital doit recevoir un remote privé.

## Défense contre la perte totale

Le stockage Azure central réduit fortement la dépendance au poste, mais un seul
cloud ne constitue pas une garantie absolue. Les générations mensuelles critiques
doivent aussi être copiées sur un support chiffré hors ligne, conservé dans un
lieu distinct. Le modèle cible est donc : données de travail locales, copie Azure
géorépliquée et versionnée, plus copie hors ligne périodique.

## Mise en œuvre par étapes

1. Créer une adresse Microsoft personnelle durable et un tenant Azure dont Papa
   Djibril Diagne détient la propriété et la facturation.
2. Créer deux abonnements ou, au minimum, deux groupes de ressources et comptes de
   stockage séparés : `PDD-PERSONAL` et `PDD-NEEMBA-AUTHORIZED`.
3. Configurer un second compte de secours personnel, MFA, codes de récupération
   hors ligne et alertes de facturation ; ne dépendre d'aucun moyen Neemba.
4. Provisionner StorageV2, Key Vault, RBAC, rétention, immutabilité et
   journalisation dans chaque périmètre.
5. Créer la VM Windows personnelle de reprise et son Recovery Services vault.
6. Produire les sauvegardes cohérentes des projets personnels. Pour Mining 360 et
   MiningProd, inventorier d'abord ce qui est autorisé à quitter Neemba.
7. Téléverser une première génération complète avec manifestes SHA-256.
8. Restaurer cette génération sur un emplacement vierge et consigner le résultat.
9. Automatiser les sauvegardes quotidiennes et les alertes, puis tester la
   restauration mensuellement.

La création des ressources Azure entraîne une facturation personnelle. Le transfert
de données Neemba nécessite en plus une autorisation de Neemba. Cette architecture
ne vaut pas autorisation de transfert.

## Références officielles

- Microsoft, [Azure Storage redundancy](https://learn.microsoft.com/en-us/azure/storage/common/storage-redundancy).
- Microsoft, [Disaster recovery and storage account failover](https://learn.microsoft.com/en-us/azure/storage/common/storage-disaster-recovery-guidance).
- Microsoft, [Immutable storage for Azure Blob Storage](https://learn.microsoft.com/azure/storage/blobs/immutable-time-based-retention-policy-overview).
- Microsoft, [Enable soft delete for blobs](https://learn.microsoft.com/en-us/azure/storage/blobs/soft-delete-blob-enable).
- Microsoft, [Azure Key Vault soft-delete overview](https://learn.microsoft.com/en-us/azure/key-vault/general/soft-delete-overview).
- Microsoft, [Secure access to a key vault](https://learn.microsoft.com/en-us/azure/key-vault/general/secure-your-key-vault).
- Microsoft, [Version history overview](https://learn.microsoft.com/sharepoint/version-overview).
- Microsoft, [Safeguarding your data in SharePoint and OneDrive](https://learn.microsoft.com/en-us/sharepoint/safeguarding-your-data).
- Microsoft, [Transfer billing ownership of an Azure subscription](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/billing-subscription-transfer).
- Microsoft, [Secure your Azure Backup deployment](https://learn.microsoft.com/en-us/azure/backup/secure-backup).

