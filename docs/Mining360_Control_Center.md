# Mining 360 Control Center

Le Control Center est un client desktop Windows en Python/Tkinter pour piloter l'environnement de developpement Mining 360.

Le Control Center V2 est actif par defaut. Pour revenir temporairement a l'interface historique :

`$env:ENABLE_CONTROL_CENTER_V2 = "Disabled"`

## Demarrage

Double-cliquer sur :

`deployment/windows/Mining360 Control Center.cmd`

Le lanceur utilise `pythonw.exe` afin de ne pas laisser de console ouverte.

## Fonctions

- demarrer Mining 360 avec le script de developpement existant ;
- arreter uniquement les processus identifies comme appartenant a Mining 360 ;
- ouvrir `https://mining360-dev.neemba.local` ;
- afficher l'etat du processus, de HTTPS, Django/Waitress, la base, Active Directory et Power BI ;
- ouvrir les journaux dans `.runlogs/desktop-control`.

Le V2 ajoute un redemarrage complet controle, un registre de services, un verrou d'operation, une progression par etapes, un panneau de diagnostic, un historique expurge des secrets et des cadences de controle distinctes.

Le script `restart_mining360_dev_runtime.ps1` reste une action limitee a Waitress. Il n'est pas utilise comme redemarrage complet de Mining 360.

Vert indique un service operationnel, rouge une indisponibilite, bleu une verification en cours et gris un service non configure ou inconnu.

## Securite

Le Control Center ne stocke aucun mot de passe ou token. Les messages affiches sont expurges des secrets connus. L'arret valide la ligne de commande du processus avant d'utiliser `taskkill`, afin de ne pas fermer un service Windows non lie a Mining 360.

Les controles Active Directory et Power BI utilisent la configuration serveur existante. Ils sont executes en arriere-plan toutes les 30 secondes pour ne pas bloquer l'interface.

Fermer le Control Center ne ferme pas Mining 360. Utiliser le bouton **Arreter l'application** lorsque l'arret des services est souhaite.
