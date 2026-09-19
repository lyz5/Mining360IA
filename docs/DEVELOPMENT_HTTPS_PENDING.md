# HTTPS Development — plan préparé, non appliqué

**Mise à jour du 19 septembre 2026 après autorisation explicite : la partie locale a été appliquée et validée.** Entrée hosts vers `127.0.0.1`, certificat existant importé dans `CurrentUser\Root` après vérification de son empreinte. Aucun certificat régénéré. Connexion TLS 1.3 validée, `/health/` HTTP 200 et page de connexion HTTP 200 dans Microsoft Edge avec validation TLS active. Le Control Center détecte HTTPS, Django et la base en ligne. Le fichier hosts initial a été sauvegardé dans `.runlogs/hosts-before-local-https-*.bak`. L'accès depuis d'autres postes reste non configuré et non testé. Les paragraphes ci-dessous décrivent le plan initial ; sa partie réseau reste à appliquer uniquement si demandée.

État actuel : **application locale opérationnelle, HTTPS non configuré**.

La passerelle réutilise le certificat restauré et écoute seulement `127.0.0.1:443`, vers Waitress sur `127.0.0.1:8001`. Le démarrage n'ajoute rien au magasin de confiance et ne génère aucun certificat.

Certificat existant : `.runlogs/dev-https/mining360-dev.crt.pem` ; clé privée conservée à son emplacement existant, jamais à publier. Le SAN couvre `mining360-dev.neemba.local` et `localhost`. Expiration : 12 septembre 2027 à 18:36:02 UTC.

Empreinte SHA-256 publique du certificat : `c91d32602af708b43a272b36784c3677895a3483ba12b8ec0cbe812f9129ed7e`.

## Usage sur cette machine uniquement

Après autorisation de modifier DNS/hosts et confiance :

1. Faire résoudre `mining360-dev.neemba.local` vers `127.0.0.1`, par exemple avec une entrée dans le fichier hosts Windows. Aucun ajout n'a été effectué.
2. Conserver les écoutes loopback actuelles. Le certificat existant couvre déjà le nom ; il n'est pas nécessaire de le régénérer.
3. Vérifier l'empreinte du certificat public ci-dessus, puis l'importer explicitement dans le magasin de confiance utilisateur approuvé. L'outil `setup_dev_https.py` possède une option `--install-trust`, séparée du démarrage. Ne pas lancer l'outil sans revoir ses conditions de génération/renouvellement ; un import explicite du certificat existant évite toute régénération accidentelle.
4. Vérifier la résolution, puis `https://mining360-dev.neemba.local/health/` sans désactiver la validation TLS. Vérifier aussi le navigateur et les redirections d'authentification.

## Usage depuis d'autres postes

1. Choisir une adresse serveur stable accessible aux clients. Adresse Wi-Fi observée le 19 septembre : `172.20.10.2` ; adresse Cloudflare WARP : `100.96.4.173`. Ces observations ne prouvent ni leur stabilité ni leur accessibilité depuis les clients. Ne pas utiliser `127.0.0.1` dans leur DNS/hosts.
2. Préparer l'enregistrement DNS du nom vers l'adresse serveur retenue, ou des entrées hosts sur chaque client.
3. Adapter explicitement le paramètre `--listen` de la passerelle à l'adresse réseau retenue. Le lanceur réparé conserve volontairement `127.0.0.1`. Waitress peut rester en loopback sur 8001 derrière la passerelle.
4. Prévoir une règle réseau entrante limitée au périmètre autorisé, seulement après approbation ; aucune règle n'a été ajoutée.
5. Utiliser un certificat approuvé couvrant le nom. Distribuer seulement le certificat public/la chaîne de confiance aux clients autorisés, jamais la clé privée. Installer la confiance selon la politique de l'organisation.
6. Tester depuis chaque catégorie de client la résolution, TLS avec validation active, `/health/`, connexion utilisateur et routes métier. Vérifier que 8001 n'est pas exposé directement.

Tant que ces vérifications ne sont pas terminées, conserver l'affichage d'état partiel et ne pas annoncer HTTPS opérationnel.
