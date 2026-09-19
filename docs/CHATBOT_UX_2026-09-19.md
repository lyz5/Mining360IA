# Conversations et dictée — Development, 19 septembre 2026

## Réalisé

- Historique de l’application vidé à la demande de l’utilisateur : 64 conversations et 377 messages dans le chatbot unifié, dont les copies importées ; suppression également des 28 conversations et 278 messages originaux de Mining360 AI, pour empêcher leur réimportation.
- Sauvegarde préalable SQLite (`quick_check = ok`) et exports CSV dans `../../local-backups/before-chatbot-history-reset-20260919/`. Les sauvegardes antérieures sont conservées. Il ne s’agit pas d’un effacement des sauvegardes ou des journaux du fournisseur Codex.
- Menu `⋯` de chaque conversation : renommer, archiver/restaurer, supprimer avec confirmation. Recherche des titres, historique accessible sur mobile et ajout immédiat des nouvelles conversations à la liste.
- Suppression définitive des messages et données associés dans l’application, limitée au propriétaire. Une conversation en cours doit être annulée avant suppression. Les exports du chatbot sont supprimés uniquement sous leur répertoire configuré.
- Renommer ou archiver pendant une réponse ne peut plus être écrasé par la sauvegarde finale du worker.
- **Entrée envoie**, **Maj+Entrée insère une nouvelle ligne**. Les événements de composition du clavier sont respectés ; double soumission bloquée ; brouillon rétabli en cas d’échec d’envoi.
- Bouton **Dicter**, sélection français/anglais, texte provisoire visible, résultats définitifs insérés au curseur sans remplacer la saisie clavier. Possibilité d’écrire pendant la dictée, de terminer/interrompre puis reprendre. Envoi pendant la dictée : attendre la dernière transcription avant une seule soumission.

## Audio

La dictée utilise `SpeechRecognition` du navigateur, sans clé API OpenAI ni nouvel endpoint de transcription de Mining360. Le navigateur peut envoyer l’audio à son fournisseur de reconnaissance ; cette information est affichée avant l’utilisation du micro. [Documentation SpeechRecognition (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition).

Le bouton démarre uniquement sur action de l’utilisateur ; la permission du navigateur reste nécessaire. Les refus, absence de micro, indisponibilité réseau et limites de longueur sont gérés sans effacer le texte. Limite d’une session de dictée : 90 secondes. Si l’API manque, indication explicite et alternative de saisie vocale Windows `Win+H`. Aucun enregistrement audio n’est conservé par ce nouveau parcours applicatif.

## Testé

- **62 tests Django réussis** : contrats, isolation, droits, import, suppression et non-réimportation, renommage, archives, concurrence avec la finalisation d’un worker. Résultat : `../../chatbot-ux-tests-20260919/test-results.json`.
- `manage.py check`, `manage.py migrate --check`, redémarrage contrôlé Development et `/health/` : OK.
- **30 tables protégées inchangées**, contrôle des clés étrangères SQLite : OK.
- Edge réel : historique initial vide ; clavier Entrée/Maj+Entrée ; titre accentué ; archiver/restaurer ; supprimer puis API 404 ; parcours envoi → worker → réponse ; mise en page mobile sans débordement.
- Événements vocaux synthétiques dans Edge : conservation du texte tapé pendant la dictée, pas de duplication d’un résultat vocal, inclusion du dernier fragment avant envoi, refus du micro sans perte du texte.
- L’API vocale native est exposée par Edge sur cette machine. Les conversations synthétiques ont été supprimées après les tests.
- Captures : `.runlogs/chatbot-ux/`. Résultats navigateur : `../../chatbot-ux-browser.json`.

## Non testé / Bloqué

- La reconnaissance acoustique avec le microphone physique de l’utilisateur et le service vocal réel du navigateur n’a pas été testée. Les tests vocaux ont simulé les résultats de transcription ; ils ne prouvent pas la disponibilité du fournisseur vocal dans le réseau de l’utilisateur.
- L’authentification du moteur Codex, signalée comme bloquée pendant la fusion précédente, n’a pas été modifiée ni revalidée par cette intervention.

## Risques / Prochaine action

Autoriser le microphone lorsque le navigateur le demande, dicter quelques mots, les compléter au clavier puis utiliser Entrée. En cas de refus du fournisseur vocal, le clavier reste utilisable et l’erreur est affichée. La disponibilité de la dictée dépend du navigateur et de sa configuration.

Production, DNS, certificats et paramètres de sécurité inchangés. Aucun ancien dossier supprimé.
