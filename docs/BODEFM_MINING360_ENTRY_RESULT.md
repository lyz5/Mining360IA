# Entrée https://bodefm/mining360

La demande de nouveau nom DNS a été remplacée par l'adresse `https://bodefm/mining360`.

## Réalisé

Ajout sur BODEFM d'une règle IIS dans le seul fichier `C:\inetpub\Mining360Proxy\web.config`, pour le site Mining360. Les chemins exacts `/mining360` et `/mining360/`, sur l'hôte HTTPS `bodefm`, redirigent temporairement (302) vers `https://bodefm/`. La navigation conserve ensuite les routes existantes de l'application, notamment `/login/` : il s'agit d'une adresse d'entrée, pas d'un déplacement de toute l'application sous le préfixe `/mining360`.

Les règles précédentes sont conservées. Aucun déploiement de code applicatif, aucune modification de base, de DNS, de certificat, de confiance TLS, de pare-feu ou de paramètre Django. Aucun redémarrage global IIS.

Connexion utilisée : SSH, `RESDELMAS\diagnepa`, empreinte du serveur vérifiée contre la configuration approuvée restaurée. Aucune clé privée affichée ou copiée.

## Testé

- `/mining360` et `/mining360/` : 302 vers `https://bodefm/`.
- Accueil existant : 302 vers `/login/?next=/`, inchangé.
- Page de connexion : 200 et formulaire présent.
- `/health/` : 200, application Mining360 et base `ok`.
- `http://172.17.0.111/Miningprod` : même 301 vers `/Miningprod/` avant/après.
- `/Miningprod/` : même 302 vers sa page `Authorization/Login.aspx` avant/après.
- Empreinte du `web.config` Miningprod inchangée ; liaisons et pool du Default Web Site inchangés. Miningprod reste dans `Default Web Site / DefaultAppPool` ; Mining360 reste dans son site et pool propres.

Les tests HTTPS ont vérifié le nom et le certificat en utilisant explicitement le certificat public actif récupéré par la connexion SSH authentifiée. Aucun magasin de confiance système n'a été modifié et aucune validation TLS n'a été désactivée.

## Limites

Le certificat BODEFM reste auto-signé : le navigateur peut toujours afficher l'alerte de confiance signalée auparavant. L'ajout d'une route ne résout pas cette alerte. Les parcours métier après authentification n'ont pas été rejoués sur Production ; les protections et routes applicatives restent inchangées.

## Retour arrière

Sauvegarde distante : `C:\Mining360\backups\entry-url-20260919-051149\web.config.before` (horodatage du serveur). Une copie de remplacement a également été conservée dans ce dossier.

Pour annuler, restaurer uniquement cette sauvegarde vers `C:\inetpub\Mining360Proxy\web.config`, après contrôle qu'aucune modification ultérieure n'est intervenue. Ne pas restaurer la configuration IIS globale ni redémarrer tous les sites.

Preuves dans l'espace de travail : `bodefm-entry-change.json`, `bodefm-entry-before.json`, `bodefm-entry-after.json`. Script de changement livré : `deployment/windows/add_bodefm_mining360_entry.ps1` (gardes sur serveur, empreintes et topologie ; refuse une réapplication sur une configuration déjà modifiée).
