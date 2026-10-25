# Archive chiffrée Neemba dans Dropbox

Autorisation utilisateur enregistrée le **24 octobre 2026**. La destination
autorisée est le dossier `Dropbox/360-Recovery`. Cette opération crée une
sauvegarde chiffrée ; elle ne supprime, ne fait tourner et ne déploie aucun
secret.

## Règles de sécurité

- La phrase de passe est saisie directement par le propriétaire dans 7-Zip. Elle
  ne doit apparaître ni dans ce document, ni dans un terminal, ni dans un script.
- Utiliser le format **7z**, le chiffrement **AES-256** et cocher
  **Chiffrer les noms de fichiers**.
- Ne pas mettre de fichier temporaire, CSV, export de mots de passe ou copie en
  clair dans Dropbox.
- Conserver les emplacements sources jusqu'à un test de restauration réussi.
- Une archive 7z est une sauvegarde de récupération, pas un gestionnaire de
  mots de passe : ne pas l'ouvrir ou l'extraire pour un usage courant.

## Création dans 7-Zip

1. Ouvrir 7-Zip File Manager et naviguer vers les seuls fichiers ou dossiers
   secrets Neemba explicitement autorisés.
2. Les sélectionner, puis choisir **Ajouter**.
3. Enregistrer l'archive dans `Dropbox/360-Recovery` sous un nom neutre, par
   exemple `Neemba-Recovery-YYYY-MM.7z`.
4. Définir : format `7z`, méthode de chiffrement `AES-256`, phrase de passe
   personnelle, et activer **Chiffrer les noms de fichiers**.
5. Créer l'archive, attendre la fin de synchronisation Dropbox, puis utiliser
   **Tester** dans 7-Zip. Le test doit réussir sans afficher les valeurs.

## Récupération après perte de machine

1. Réinstaller 7-Zip depuis sa source officielle.
2. Récupérer l'archive depuis Dropbox.
3. La copier sur un support local chiffré avant extraction.
4. Saisir la phrase de passe hors connexion et restaurer uniquement les éléments
   nécessaires dans un emplacement contrôlé.

## Limites et suivi

Le chiffrement protège l'archive, mais la perte de la phrase de passe rend la
récupération impossible. Le propriétaire doit conserver cette phrase hors ligne
dans un moyen sûr qu'il contrôle. Toute suppression des sources ou toute rotation
des secrets nécessite une décision distincte après un test de restauration.
