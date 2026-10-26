# Accès SSH BODEFM — 26 octobre 2026

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

L'agent SSH local observé ne contenait qu'une clé PythonAnywhere et aucune clé
privée BODEFM validée. L'absence de cette clé locale ne remet pas en cause
l'identité du serveur ni l'accès par mot de passe confirmé ci-dessus.

## Règles d'exploitation

- Utiliser exactement `RESDELMAS\diagnepa` pour les opérations BODEFM ; ne pas
  déduire une identité `NEEMBA\diagnepa`.
- Vérifier l'empreinte hôte avant de remplacer une entrée `known_hosts`.
- Ne jamais transmettre, inscrire ou sauvegarder un mot de passe dans Git,
  Dropbox, un script ou une conversation.
- Une future clé dédiée BODEFM est souhaitable, mais ne doit être créée et
  autorisée côté serveur qu'avec validation du propriétaire et en préservant
  les accès existants.
- Toute intervention de production reste soumise aux préflights, sauvegardes,
  contrôles de runtime et rollback documentés pour BODEFM.
