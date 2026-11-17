# Connexion par e-mail et code — recette locale

Statut : développement local, non publié. L'utilisateur a explicitement demandé
de ne rien publier ni activer sur BODEFM avant son Go.

La branche `feature/email-code-signin-20261116` part de la référence BODEFM
`f81a3ad37e8b956f4a932a22db3320ab156095f5`. Elle est dans le worktree
`.release-worktrees/email-code-signin`, distinct de l'ancien brouillon d'accès
anonyme `.release-worktrees/temporary-network-access`, qui ne doit pas être utilisé.

## Comportement

`/login/` conserve son comportement existant tant que
`MINING360_EMAIL_CODE_LOGIN_ENABLED` vaut faux (valeur par défaut). Si le drapeau
est actif, GET redirige vers `/email-sign-in/`; le lien
`/login/?method=password` conserve la connexion existante.

Le code est envoyé uniquement à une adresse e-mail ou UPN d'un profil Config →
Users actif, relié à un compte Django actif et identifié sans ambiguïté. Aucun
nouvel utilisateur n'est créé. Les rôles, scopes et permissions Config ne sont
pas modifiés. À la demande explicite de l'utilisateur du 16 novembre, une adresse
absente affiche : « No Mining360 account is registered for this email address.
Please contact your administrator. » Aucun challenge ni message n'est créé dans
ce cas; le formulaire conserve l'adresse saisie. Un compte désactivé, non relié
ou ambigu affiche « This account is not enabled for email sign-in. Please contact
your administrator. » Il n'est pas présenté comme absent. Les limites de fréquence
précèdent cette vérification et la session perd son ancien challenge en cas de
refus. La vérification du code contrôle à nouveau la boîte et l'activité du compte.

Le code contient huit chiffres, expire après dix minutes, est lié à la session
du navigateur et utilisable une seule fois. Cinq tentatives au maximum; les
tentatives mal formées comptent aussi. La base stocke un hash salé du code et des
empreintes HMAC de l'adresse et du nonce. Le code n'est jamais stocké en clair
dans la session ou la base et son hash est effacé après consommation/verrouillage.

Les demandes sont limitées par adresse (six par quinze minutes, délai de soixante
secondes) et par pair réel (120 par quinze minutes). Aucun X-Forwarded-For fourni
par le client n'est utilisé. Derrière IIS, ce dernier plafond porte sur le pair
loopback partagé et doit être pris en compte lors de la recette de charge.

La connexion utilise le compte existant et les sessions Django normales.
« Keep me signed in » reste facultatif. Désactiver le drapeau invalide les
sessions du nouveau backend; les backends Windows et mot de passe existants
restent dans leur ordre initial. CSRF, redirection interne, cache privé et
masquage des paramètres sensibles sont préservés.

## Livraison réelle, à configurer après accord

**Mise à jour après accord :** l'envoi réel fonctionne désormais sur l'instance
locale via un flow dédié et la connexion Outlook du propriétaire. Deux envois
réels et la connexion par code ont passé les contrôles; 45 tests SQL réussissent.
La capture locale est désactivée. Voir
[EMAIL_SIGNIN_REAL_DELIVERY_2026-11-17.md](EMAIL_SIGNIN_REAL_DELIVERY_2026-11-17.md)
pour la preuve, les limites et les changements de politique réseau. Les constats
initiaux d'absence de transport ci-dessous décrivent la phase précédente.

L'intégration Notification de code `email-signin` accepte :

- un relais SMTP authentifié avec STARTTLS ou SSL;
- un flow d'entreprise dédié à l'envoi d'e-mails, avec URL secrète chiffrée.

Contrat du flow : `recipient`, `subject`, `body`. Le flow doit répondre HTTP 200
ou 204 **après** l'envoi réussi; 202 et redirections sont refusés. Ne pas réutiliser
le flow existant qui exécute les requêtes DAX. Les URLs du flow sont limitées aux
hôtes HTTPS Power Platform/Logic Apps reconnus. Le sender doit être autorisé par
la véritable connexion de messagerie. Le contrôle Config valide la structure,
indique explicitement qu'il n'a envoyé aucun e-mail et ne prétend pas avoir testé
la boîte.

Aucune connexion réelle de messagerie n'a été créée ou activée. L'autorisation
ancienne d'utiliser l'adresse Neemba de l'utilisateur comme sender ne prouve pas
qu'un relais ou une connexion Outlook fonctionnent. Aucun mot de passe de boîte
ne doit être demandé dans le chat. La connexion Graph existante n'avait pas le
droit applicatif Mail.Send lors de l'inspection; ne pas la traiter comme un
transport disponible.

Dans la recette locale, le backend Django `filebased` capture le message dans un
dossier privé. Aucun envoi réel n'est effectué. Voir
[la procédure de l'instance isolée](BODEFM_LOCAL_PREVIEW_2026-11-16.md).

## Schéma et conservation

La migration `0150_email_code_signin` crée uniquement `email_login_challenge` et
`email_login_rate_lock`. Elle dépend du graphe source 0147 exporté de BODEFM et
n'écrase pas les noms 0148/0149 déjà présents dans certains historiques SQL.
Le test d'application et de retour arrière doit porter sur la copie locale avant
toute promotion.

`manage.py prune_email_signin` ne supprime que les challenges expirés depuis plus
de trois jours et les anciens compteurs. Aucune tâche serveur n'a été installée.

## Contrôles exécutés

- 41 tests passent sur une base SQL Server 2022 locale jetable : codes, expiration,
  tentatives, relecture des droits, CSRF, sessions, chiffrement, permissions Config,
  conservation, livraison simulée et protections du lanceur local.
- La concurrence SQL vérifie que deux validations simultanées donnent exactement
  un succès. SQLite ne valide pas ce verrou et saute ce test.
- Suite élargie : 81 tests, huit échecs et un test de concurrence sauté sous
  SQLite. Les huit mêmes échecs existent dans la référence BODEFM non modifiée
  (45 tests de référence), liés à d'anciennes attentes AD/Users et au rôle `ai`
  retiré. Ne pas décrire la suite historique comme entièrement verte; ces tests
  et les rôles n'ont pas été réécrits dans cette mission.
- Le dry-run des migrations révèle aussi un décalage DowntimeCheckingRun/Finding
  déjà présent dans la référence. Aucune migration Downtime n'a été générée.

Le message explicite de compte absent est validé dans Edge en 1440/390 px, sans
champ code, sans nouveau message capturé et sans erreur JavaScript. La preuve est
`local-instance/account-check-validation.json`, avec captures `account-not-found-*`.

Preuves privées : `.runlogs/email-code-signin-20261116/`. Les données, e-mails de
test, clés locales, backups et captures métier restent hors Git.

La migration a passé application → retour arrière → application sur la copie SQL,
avec empreintes du Revenue et des droits inchangées. Edge valide le message
capturé, le rejet d'un code erroné, la connexion avec le code valide, Config et
le Business Overview HTTP 200. Login en 1440/390 px sans débordement, zéro erreur
JavaScript; cœur Business Overview chargé en 4,247 secondes après connexion.
Le test navigateur a permis de corriger `Referrer-Policy` en `same-origin` pour
les formulaires; CSRF reste actif et rejette les origines nulles et étrangères.
Voir [MDN](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy).

Avant un Go de production : faire valider la recette locale par l'utilisateur, vérifier
l'envoi réel avec un transport autorisé, revoir le diff ciblé, préparer un commit
identifié et un paquet avec backup/rollback. Un test local ou un push Git ne vaut
pas autorisation de déploiement.
