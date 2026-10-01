# Rôles simplifiés — Development, 29 septembre 2026

La page Users propose six rôles : Excellence Center, Business Overview, Reporting, Ressources, Admin, Super Admin. Les quatre rôles métier sont cumulables. Admin et Super Admin sont exclusifs entre eux.

| Rôle | Accès |
| --- | --- |
| Excellence Center | Consultation des KPI dans le périmètre autorisé |
| Business Overview | Consultation des performances gouvernées ; aucune permission implicite de publication ou de prévisualisation des mappings non publiés |
| Reporting | Rapports autorisés, avec les restrictions Power BI existantes |
| Ressources | Consultation de la bibliothèque documentaire |
| Admin | Gestion des utilisateurs métier et de leurs accès ; ajouter les rôles métier pour consulter les modules |
| Super Admin | Accès complet, intégrations, configuration sensible et attribution des rôles administrateurs |

Un Admin ne peut pas modifier/désactiver un compte Admin ou Super Admin, s'élever lui-même, attribuer un niveau Business Administrator, ni activer l'héritage des rôles AD. Le dernier Super Admin actif est protégé. Les anciens formulaires de mutation des utilisateurs sont fermés ; toutes les modifications passent par les API contrôlées du panneau Users.

## Préservation et compatibilité

- Aucun compte réel modifié lors de la livraison. Empreintes identiques avant/après pour les dix profils, neuf utilisateurs, scopes, groupes et permissions Django.
- Les comptes sans liste explicite conservent leurs droits historiques. Les anciens administrateurs complets sont affichés comme Super Admin, sans modification automatique de la base.
- Les rôles sélectionnés sont enregistrés à la prochaine sauvegarde utilisateur dans la clé versionnée `platform_roles_v2` du JSON existant. Les autres clés de périmètre sont conservées ; aucune migration de schéma requise.
- Les niveaux métier historiques restent disponibles sous « Advanced data scope » pour ne pas perdre les restrictions existantes. Les droits de lecture Business Overview n'élargissent pas les règles Account/MineSite.
- Les droits historiques AI/Data/Data Source ne sont pas proposés comme nouveaux rôles. Les capacités séparées existantes restent compatibles ; une rétrogradation de Super Admin retire les droits Data/Source implicitement administrateurs. Les routes M360 Chatbot et Mining360 AI ne sont pas fusionnées.
- La reconnexion AD respecte les rôles manuels avant de calculer les attributs Django staff/superuser. Les comptes gérés par groupes AD continuent de suivre ces groupes.

## Vérifications

- 23 tests Django en base de test isolée : rôles, API, refus d'élévation, gestion AD, dernier Super Admin, navigation et restrictions MineSite/RLS.
- Deux tests supplémentaires sans base : compatibilité des anciens profils locaux et rétrogradation du niveau Business Administrator implicite.
- `manage.py check`, `makemigrations --check --dry-run` et vérification syntaxique JavaScript réussis. Aucun nouveau schéma détecté.
- Navigateur Edge : six cases et six filtres métier/administration attendus, anciens niveaux rangés dans les paramètres avancés ; aucune erreur JavaScript détectée.
- Après redémarrage contrôlé, Business Overview, Excellence Center, Reporting, Ressources et M360 Chatbot répondent en 200. Il s'agit d'un contrôle d'ouverture après livraison ; les essais fonctionnels antérieurs et leurs limites restent dans `LOCAL_FUNCTIONAL_VALIDATION_2026-09-29.md`.
- Une seule instance : HTTP 8001 PID 32004, HTTPS 443 PID 30180, worker PID 21616 ; parents Python identifiés. HTTPS contrôlé sur boucle locale avec certificat restauré ; base OK.
- Sessions temporaires supprimées après contrôle ; aucune sauvegarde de cookies, aucun compte de test dans la base réelle.

## Retour arrière et présentation

Les versions de référence et révisées des treize fichiers applicatifs sont conservées dans `.migration-review/roles-release/baseline/` et `revised/`, avec empreintes dans `manifest.json`. La référence vient du checkout isolé déjà vérifié ; les différences inspectées correspondent aux changements de rôles. Les nouveaux modules peuvent rester présents mais inutilisés après restauration des fichiers existants.

Avant tout retour arrière : vérifier que les fichiers courants correspondent encore aux empreintes révisées et qu'aucun rôle réel n'a été réattribué depuis cette livraison. Arrêter uniquement les processus Development identifiés, restaurer uniquement les fichiers du manifeste disposant d'une référence, puis relancer et vérifier HTTP/Users. Ne pas restaurer la base, modifier les secrets ou écraser des changements ultérieurs. Aucun rollback n'a été exécuté.

Pour la démonstration : utiliser `http://127.0.0.1:8001/`, conserver la connexion au réseau NEEMBA et éviter toute réattribution des comptes existants juste avant la présentation. Le nom local historique, le profil Codex non authentifié, le corpus documentaire omis et les deux migrations destructrices en attente restent les limites déjà signalées. Aucun déploiement Production/BODEFM, changement DNS, certificat de confiance ou publication Business Mapping effectué.
