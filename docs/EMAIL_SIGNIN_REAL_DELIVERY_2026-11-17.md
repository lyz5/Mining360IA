# Codes de connexion par e-mail réel — instance locale

## État et autorisation

L'utilisateur a demandé de passer aux vrais e-mails puis a autorisé la poursuite
jusqu'à la fin. L'application reste sur `http://localhost:8016/`. Aucun push Git,
déploiement, changement d'authentification ou redémarrage BODEFM n'a été effectué.

Les codes sont désormais envoyés par la connexion Office 365 Outlook existante
de **papa.diagne@neemba.com**, vérifiée « Connected » dans Edge/Power Automate.
Les autres intégrations de la copie restent désactivées et bloquées.

## Flow dédié

Nom : **Mining360 - Email sign-in codes**.
Identifiant constaté : `201425da92cb47d8897d17703c6f2bea`.
Environnement : celui de la connexion d'entreprise existante. Aucun identifiant
de connexion n'a été inventé. Le flow DAX historique n'est pas modifié ni réutilisé.

Le flow reçoit un objet JSON avec `recipient`, `subject`, `body`, envoie le message
avec Office 365 Outlook « Send an email (V2) », puis retourne HTTP 200 **uniquement
après** le succès de l'action Outlook. Le sujet est fixé à « Your Mining360 sign-in
code ». Les entrées et sorties du déclencheur et de l'action Outlook sont masquées
dans l'historique avec Secure inputs / Secure outputs. Le schéma des trois champs
a été généré et contrôlé avant l'enregistrement final.

L'URL d'appel signée reste secrète et est stockée chiffrée dans l'intégration
Notification de code `email-signin`, dans la base locale. Ne jamais la copier dans
le frontend, la documentation, Git ou le chat. Le mode HTTP du flow est « Anyone »
avec URL signée; la possession de cette URL est donc un accès sensible à protéger.

## Instance locale

Le drapeau privé `real_email_enabled: true` du fichier d'instance active
`LOCAL_PREVIEW_REAL_EMAIL`. Il ne change aucune variable du serveur BODEFM.
La politique `deployment.local_mail_policy.EmailEgressPolicy` autorise uniquement
un POST TLS vérifié vers l'URL exacte du flow configuré, sans redirection.
Les adresses réseau nécessaires ne sont autorisées que pendant cette requête et
dans son thread. Les requêtes Graph, Power BI, autres flows et autres bases SQL
restent bloquées. La configuration ODBC reste forcée sur la seule base locale.

Le bandeau de recette affiche **Real email delivery**. L'ancienne boîte de codes
locale ne montre plus les anciens messages; elle indique que le code arrive par
vrai e-mail. Aucun nouveau code n'est écrit dans les fichiers de capture.

La vérification des comptes reste inchangée : compte actif existant et unique,
lié à un utilisateur actif, sinon message explicite et aucun envoi. Aucun rôle,
scope, utilisateur, mapping ou calcul de Revenue n'est modifié par ce raccordement.

## Tests et limites vérifiées

- **45 tests SQL Server réussis**, incluant compte absent, CSRF, concurrence,
  permissions, URL exacte autorisée, rejet d'autres URLs/méthodes/redirections,
  vérification TLS et fermeture de l'autorisation réseau après erreur.
- Deux vrais e-mails de test, uniquement du compte propriétaire vers lui-même.
  Les deux envois sont confirmés par le flow après succès Outlook.
- Premier parcours : demande via les vues Django, envoi réel confirmé en 4,089 s,
  puis connexion normale avec le code aléatoire généré, hash consommé/effacé,
  rôle et scope inchangés, session de recette déconnectée.
- Ce premier test utilise le code en mémoire côté serveur pour vérifier le login;
  le code n'est ni affiché ni écrit dans les preuves. Il ne constitue pas un test
  de lecture du message reçu dans Outlook.
- Second parcours : requête HTTP vers le vrai serveur localhost, nouvel envoi réel
  confirmé, bannière correcte, aucune capture locale du code, session fermée.
- Edge confirme toujours le refus d'une adresse absente sans champ code ni envoi,
  aux formats 1440 et 390 px, sans erreur JavaScript.
- **Réception dans la boîte de réception non indépendamment confirmée** : le succès
  Outlook établit l'acceptation de l'envoi, pas sa visibilité dans Inbox ou Spam.
  Les codes de ces essais expirent et une nouvelle demande sera nécessaire pour
  une connexion ultérieure.

Preuves privées : `.runlogs/email-real-20261116/configuration-receipt.json`,
`real-send-result.json`, `runtime-email-result.json` et définitions des trois étapes
lues depuis le concepteur. Le dossier daté conserve le début de l'intervention du
16 novembre; ce document consigne sa reprise du 17. Les tests généraux restent
dans `.runlogs/email-code-signin-20261116/`.

Avant toute production : validation utilisateur, revue du diff et des limites
historiques, commit/push ciblés puis Go distinct pour BODEFM, avec son mécanisme
de sauvegarde et de rollback. Le fonctionnement local n'autorise pas cette promotion.
