# Migration des secrets Neemba vers le coffre KeePassXC de 360

> **Remplacée le 24 octobre 2026.** Le choix retenu est une archive 7z chiffrée
> dans Dropbox. Cette procédure est conservée uniquement comme historique ; ne
> pas y ajouter de secrets.

Autorisation utilisateur enregistrée le **24 octobre 2026**. Ce document ne
contient aucune valeur secrète ; il décrit seulement le périmètre de migration
vers `360-Secrets.kdbx`.

## Règles impératives

- Ne jamais créer de CSV, TXT, JSON, capture, archive non chiffrée ou copie
  intermédiaire des secrets.
- Saisir ou coller chaque valeur directement dans KeePassXC déverrouillé, puis
  effacer le presse-papiers.
- Conserver les sources existantes jusqu'à validation de chaque accès ; cette
  migration n'autorise ni suppression, ni rotation, ni déploiement.
- Ne pas afficher de mot de passe, token, clé privée ou chaîne de connexion à
  l'écran, dans un terminal, un journal ou cette documentation.

## Structure du coffre

Créer le groupe racine `Mining360`, avec les sous-groupes suivants :

1. `BODEFM Infrastructure` — accès administratifs, hôtes et procédures de
   récupération.
2. `Mining360 Application` — secret Django, clés de chiffrement et paramètres
   d'exécution sensibles.
3. `Data & Power BI` — identités SQL, Power BI et connecteurs autorisés.
4. `Integrations` — OpenAI, Power Automate et autres intégrations actives.
5. `Certificates & Private Keys` — références aux certificats, leur emplacement
   sécurisé et leurs dates d'expiration ; joindre un fichier privé uniquement
   après évaluation du risque et test de restauration.
6. `Recovery` — références aux mécanismes de récupération, sans codes secrets
   en clair hors du coffre.

## Migration d'une entrée

1. Ouvrir `360-Secrets.kdbx` dans KeePassXC avec la phrase maîtresse détenue
   par Papa Djibril Diagne.
2. Créer une entrée dans le sous-groupe approprié.
3. Renseigner un nom fonctionnel, l'URL ou l'hôte si utile, l'identifiant et la
   valeur secrète. Ajouter propriétaire, environnement, date de rotation et
   emplacement source dans les notes, sans reproduire de valeur dans les notes.
4. Vérifier que l'entrée est enregistrée et que le coffre Dropbox se synchronise.
5. Tester l'accès seulement dans son environnement autorisé ; ne pas changer la
   valeur ou le secret pendant cette migration.

## Validation finale

Après migration, vérifier sur une seconde copie du coffre que les groupes et
entrées sont présents. Le test doit confirmer l'ouverture du coffre et la
présence des entrées, sans imprimer leurs valeurs. Les sources historiques ne
sont supprimées qu'après une décision séparée, documentée et réversible.
