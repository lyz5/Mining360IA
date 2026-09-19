# Nouveau nom interne de Mining360 sur BODEFM

**Décision la plus récente : nouveau nom DNS abandonné au profit de `https://bodefm/mining360`.** L'adresse d'entrée a été ajoutée et testée ; elle redirige vers l'accueil existant. Voir `BODEFM_MINING360_ENTRY_RESULT.md`. Les propositions DNS ci-dessous sont historiques et n'ont pas été appliquées.

## Accès SSH retrouvé et vérifié

La clé SSH de l'ancienne machine a été retrouvée dans le dossier `.ssh` de la sauvegarde OneDrive. Elle a été utilisée sur place, sans publication ni copie de son contenu. La paire publique/privée concorde et l'empreinte du serveur correspond exactement à celle approuvée dans le DeploymentTarget restauré. Connexion effective sur BODEFM : `RESDELMAS\diagnepa`, administrateur. Les refus SMB/WinRM antérieurs ne signifiaient donc pas l'absence de tout accès distant.

Inventaire distant confirmé : `/Miningprod` appartient au `Default Web Site`, chemin `C:\inetpub\wwwroot\Miningprod`, pool `DefaultAppPool`. Mining360 utilise le site et pool `Mining360`, chemin `C:\inetpub\Mining360Proxy`. La réponse HTTP initiale de `/Miningprod` est 301 ; ce statut n'est pas un test fonctionnel complet de l'application.

La lecture administrative des zones DNS via WMI sur `172.17.0.205` et `172.17.0.206` est refusée (`UnauthorizedAccessException`) depuis cette session SSH. Cela ne prouve pas que le compte n'a aucun droit DNS dans un autre contexte d'authentification ; un accès réseau secondaire peut nécessiter une authentification distincte. Aucun changement de délégation ou de droits n'a été tenté. Le module DnsServer est absent et n'a pas été installé.

Autorité interne référencée dans le magasin de certificats : `jadelmas-BODVAAD01-CA`. La consultation LDAP de l'annuaire des autorités a échoué depuis la session SSH ; sa disponibilité et les droits d'émission ne sont pas confirmés. Aucun certificat couvrant `mining360-prod.intern` n'a été trouvé.

Aucune mutation distante effectuée : ni DNS, ni IIS, ni certificats, ni paramètres d'application, ni redémarrage. Les fichiers de configuration des deux applications ont été empreintés en lecture seule. Preuves locales à la racine de l'espace de travail : `bodefm-ssh-access.json`, `bodefm-inventory.json`, `bodefm-dependencies.json`, `bodefm-dns-access.json`.

## Décision ultérieure — nom définitif demandé

L'utilisateur a retenu **`https://mining360-prod.intern/`**, pour tous les équipements du réseau, et autorisé la poursuite. Les propositions `.local` et `.jadelmas.com` ci-dessous sont historiques et ne doivent pas être appliquées. Toutes les nouvelles valeurs DNS, SAN, URL de base, hôtes autorisés et origines CSRF doivent utiliser `mining360-prod.intern`.

Application protégée explicitement : **`http://172.17.0.111/Miningprod`**. Ne modifier ni ses fichiers, ni son application/pool IIS, ni ses liaisons. Aucun redémarrage IIS global. L'inventaire doit identifier son rattachement réel avant mutation ; son URL seule ne prouve pas son site, notamment en présence de réécriture ou de répertoires virtuels.

Vérification DNS ciblée : les serveurs `172.17.0.205` et `172.17.0.206` ont chacun retourné `DNS_ERROR_RCODE_NAME_ERROR` pour `intern` (SOA) et `mining360-prod.intern` (A). Aucun espace DNS `intern` utilisable n'a été établi par ces réponses. Lire les zones/redirecteurs et leurs droits avant de choisir la création d'une zone appropriée ; ne pas créer arbitrairement deux zones indépendantes ni modifier les résolveurs des clients.

Préparation actuelle : script de lecture seule `deployment/windows/inspect_bodefm_intern.ps1`, à exécuter dans la session RDP BODEFM. Il inventorie les sites/applications/pools/répertoires virtuels, les certificats publics et les zones DNS si le module est disponible. Il n'installe aucun module, ne modifie aucun paramètre, ne lit ni clé privée ni mot de passe. La configuration DNS, l'émission du certificat et l'ajout IIS restent non appliqués, en attente de cet inventaire et d'accès administratifs disponibles.

Demande : accès au site par `https://mining360-prod.local/`. Le nom Windows BODEFM reste inchangé. Cette préparation ne constitue pas une application sur le serveur.

## Cible

| Élément | Valeur à préparer |
|---|---|
| Serveur existant | BODEFM, adresse observée `172.17.0.111` |
| URL interne souhaitée | `https://mining360-prod.local` |
| Nom DNS du certificat (SAN) | `mining360-prod.local` |
| Binding HTTPS IIS | Nom d'hôte `mining360-prod.local`, port 443, certificat approprié ; conserver les bindings existants |
| `MINING360_PUBLIC_BASE_URL` | `https://mining360-prod.local` |
| `MINING360_ALLOWED_HOSTS` | Ajouter `mining360-prod.local` aux valeurs actuelles, sans les écraser |
| `MINING360_CSRF_TRUSTED_ORIGINS` | Ajouter `https://mining360-prod.local` aux valeurs actuelles |
| Retour Entra, si cette connexion est utilisée | `https://mining360-prod.local/auth/callback/` |
| Retour après déconnexion, si utilisé | `https://mining360-prod.local/login/` |

## Ordre d'application

1. Confirmer le périmètre : cette machine seulement ou postes de l'entreprise. Pour cette machine, une entrée hosts `172.17.0.111 mining360-prod.local` suffit à la résolution. Pour plusieurs postes, préparer la résolution DNS interne avec l'administrateur DNS. Une entrée hosts locale ne configure pas les autres postes.
2. Obtenir un accès administrateur authentifié au serveur. Lire les bindings IIS, le certificat actuel, les paramètres non secrets et le mécanisme de démarrage réellement utilisés ; ne pas déduire leur état des seuls scripts du dépôt.
3. Sauvegarder la configuration IIS et les valeurs à modifier. Conserver l'accès `https://bodefm/` pendant la transition. Ne pas modifier la base ni déployer une nouvelle version de l'application.
4. Faire émettre un certificat couvrant exactement `mining360-prod.local`, de préférence par l'autorité interne approuvée. Vérifier dates, SAN et chaîne. Installer le certificat et sa clé sur BODEFM ; la clé privée ne doit jamais être distribuée aux clients. Une simple modification DNS ne corrige pas le certificat actuel.
5. Ajouter le binding HTTPS et les paramètres applicatifs ci-dessus en conservant les autres noms/origines et les protections existantes (cookies sécurisés, redirection HTTPS, permissions, authentification). Ne pas utiliser le script de configuration du domaine public sans adaptation : il remplace plusieurs listes et suppose un autre scénario de publication.
6. Si Entra est utilisé, faire enregistrer et valider les URI de retour correspondantes avant de basculer l'URL de connexion. Ne pas modifier automatiquement l'enregistrement Entra ni les règles d'accès.
7. Appliquer la résolution choisie et la chaîne de confiance approuvée aux clients concernés. Recharger uniquement les composants identifiés qui nécessitent la prise en compte des paramètres, avec possibilité de revenir aux anciennes valeurs.
8. Vérifier depuis les clients : résolution, certificat avec validation TLS active, `/health/`, connexion/déconnexion, redirections restant sur le nouveau nom, formulaires CSRF et routes métier. Aucun contournement TLS ne vaut validation.

## État de la préparation

### Informations confirmées par la session RDP utilisateur

- Compte distant : `RESDELMAS\diagnepa` ; ordinateur BODEFM ; domaine `jadelmas.com`.
- Périmètre demandé : tous les équipements du réseau, pas uniquement le poste de restauration.
- DNS de l'interface Ethernet0 : `172.17.0.205` et `172.17.0.206`. Cela n'établit pas encore leurs zones hébergées, leurs droits d'administration ni la configuration DNS des autres clients.
- Site IIS : `Mining360`, démarré, chemin `C:\inetpub\Mining360Proxy`.
- Bindings actuels à préserver : `http *:80:mining360.neemba.local`, `https *:443:`, `http *:80:bodefm`. Le Default Web Site possède séparément `http *:80:`.
- Certificats du magasin machine personnel signalés : localhost (2029), certificat SAN `172.17.0.111` (2035), certificat SAN `bodefm.jadelmas.com` et `bodefm` (2028). Aucun ne couvre le nom demandé ; leur seule présence ne prouve ni le binding actif ni leur chaîne de confiance.
- Point de conception : `.local` est un suffixe spécial mDNS ([RFC 6762](https://www.rfc-editor.org/rfc/rfc6762)). Il ne convient pas comme choix par défaut pour garantir la résolution DNS classique de tous les types d'équipements. Proposition soumise à l'utilisateur : `mining360-prod.jadelmas.com`, dans le domaine existant, sous réserve de vérification de la zone et de la disponibilité du nom. Aucun changement de nom n'est appliqué sans son choix.
- Valeurs DNS préparées si la proposition est retenue : zone `jadelmas.com`, nom `mining360-prod`, type A, adresse `172.17.0.111`. Créer sur le serveur autoritatif approprié après contrôle d'absence de conflit ; vérifier la réponse des deux DNS et leur réplication, sans créer arbitrairement deux zones indépendantes.
- Le certificat devra couvrir le nom finalement retenu et être reconnu par chaque catégorie de client ; l'appartenance au réseau ne garantit pas la confiance de l'autorité interne sur les équipements non gérés.

- BODEFM est joignable sur les ports 80, 443, 22 et 3389.
- Le certificat actuellement présenté sur `https://bodefm/` n'est pas reconnu par cette machine (auto-signé).
- La tentative d'administration PowerShell distante avec l'identité Windows actuelle a échoué : `NetworkPathNotFound`.
- Aucun changement DNS, hosts, certificat, IIS, application ou base n'a été appliqué pour ce nouveau nom.
- En attente : choix final du nom, droits d'administration DNS et certificat approprié. L'utilisateur dispose d'une session RDP ; les outils locaux de l'assistant ne disposent toujours pas de cette session authentifiée. Ne transmettre aucun mot de passe ni clé privée dans la conversation.
- Le domaine public `mining360.neemba.com` est hors périmètre et n'est pas encore configuré.
