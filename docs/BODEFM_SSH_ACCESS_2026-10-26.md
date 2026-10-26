# Accès SSH BODEFM — 26 octobre 2026

## Etat actuel de la connexion dediee

The following verified setup supersedes the earlier note that a dedicated key
was still pending:

- Local private key: `%USERPROFILE%\.ssh\mining360_bodefm_control`.
- Public-key fingerprint: `SHA256:ie7VUR5IMAtW9UNrCD0AivkiAtBeQR9mbKWVmRpn6DI`.
- The private key is restricted by Windows ACLs to the current user, SYSTEM and
  local Administrators.
- BODEFM uses `C:\ProgramData\ssh\administrators_authorized_keys` for this
  administrator account. The key was added there without removing existing
  entries; the existing SYSTEM and Administrators ACLs were preserved.
- Strict-key SSH was verified with `hostname`; the result was `BODEFM`.
- The client uses the existing `bodefm` known-hosts alias and the verified
  server fingerprint recorded below. Password authentication is disabled in
  the Control Center SSH command.

The private key is not stored in Git, Dropbox, this document, or Control Center
event logs. No password is stored by the Control Center.

The local Control Center's BODEFM panel provides status refresh and a confirmed
Mining360 restart. Restart checks the scheduled-task action and SYSTEM identity,
refuses active/unverifiable processing and unknown port owners, restarts only
`Mining360RuntimeServiceRecovery`, and checks application/database/public HTTPS
health afterward.

## Connexion vérifiée

Une connexion SSH en lecture seule vers BODEFM a été vérifiée le 26 octobre 2026.

| Élément | Valeur vérifiée |
| --- | --- |
| Hôte | `bodefm` (`172.17.0.111`) |
| Compte SSH | `RESDELMAS\diagnepa` |
| Empreinte hôte ED25519 | `SHA256:kfmGwjv+cmHBNzs+GN1OZyq4PaC1j56SzvyOsFPJdkA` |
| Commande de contrôle | `hostname` |
| Résultat | `BODEFM` |

L'empreinte ci-dessus a été affichée par le client SSH et explicitement acceptée
depuis la session utilisateur. Elle doit être comparée avant toute nouvelle
acceptation d'une clé hôte différente.

## Authentification actuelle

La connexion vérifiée a utilisé l'authentification par mot de passe du compte
`RESDELMAS\diagnepa`. Le mot de passe n'est pas conservé dans ce dépôt, dans la
documentation, dans les journaux ou dans une configuration applicative.

Au moment de ce premier contrôle, l'agent SSH ne contenait aucune clé BODEFM.
La clé dédiée créée ensuite et son authentification stricte sont documentées
dans la section d'état actuel en tête de ce document.

## Règles d'exploitation

- Utiliser exactement `RESDELMAS\diagnepa` pour les opérations BODEFM ; ne pas
  déduire une identité `NEEMBA\diagnepa`.
- Vérifier l'empreinte hôte avant de remplacer une entrée `known_hosts`.
- Ne jamais transmettre, inscrire ou sauvegarder un mot de passe dans Git,
  Dropbox, un script ou une conversation.
- La clé dédiée décrite en tête de document est maintenant autorisée pour ce
  compte. Préserver cette entrée et toutes les autres clés lors d'une rotation.
- Toute intervention de production reste soumise aux préflights, sauvegardes,
  contrôles de runtime et rollback documentés pour BODEFM.
