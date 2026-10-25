# 360 Command Center

Tableau de bord local du portefeuille de Papa Djibril Diagne. Il lit le registre
canonique `docs/PROJECT_PORTFOLIO_2026-10-15.json` et ne remplace ni les handoffs
de projet, ni les dépôts sources.

## Ouvrir le tableau de bord

Depuis la racine de `Mining360IA` :

```powershell
python .\command-center\server.py
```

Ouvrir ensuite <http://127.0.0.1:8030/>. Le serveur expose des vues locales des
projets, de leur état Git et du plan Dropbox.

Pour activer le bouton de synchronisation de l’application, copier
`dropbox-sync.local.example.json` en `dropbox-sync.local.json`, renseigner le
dossier local Dropbox, puis ne jamais versionner ce fichier local.

## Synchronisation Dropbox

`sync-documentation-to-dropbox.ps1` est volontairement en lecture/simulation par
défaut. Il ne transfère rien sans `-Execute` et ne supprime aucun fichier Dropbox.

Après installation de Dropbox Desktop, lancer d'abord :

```powershell
.\command-center\sync-documentation-to-dropbox.ps1 -DropboxRoot 'C:\Users\<vous>\Dropbox' -DryRun
```

Après vérification de la liste, lancer :

```powershell
.\command-center\sync-documentation-to-dropbox.ps1 -DropboxRoot 'C:\Users\<vous>\Dropbox' -Execute
```

La synchronisation ne copie que les mémoires de portefeuille explicitement
listées dans `documentation-sync-manifest.json`. Les documents Neemba, données,
exports, secrets, bases, médias et fichiers locaux sont exclus par conception.
Ajouter un document au manifeste est une décision de périmètre : ne pas y ajouter
de contenu Neemba sans autorisation explicite.
