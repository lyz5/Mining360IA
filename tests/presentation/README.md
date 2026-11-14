# Banc de présentation isolé

Ce dossier ne fait pas partie des routes ou des imports de l'application.
Les valeurs de `fixtures.py` sont exclusivement des données de test, avec des
clés synthétiques. Ne pas les utiliser comme fallback de production.

Depuis la copie de travail `.release-worktrees/responsive`, avec le Python du
venv local autorisé :

```powershell
& 'C:\Users\diagnepa\Documents\MBA\Mining360IA\.venv\Scripts\python.exe' tests/presentation/run_checks.py
& 'C:\Users\diagnepa\Documents\MBA\Mining360IA\.venv\Scripts\python.exe' tests/presentation/fixture_server.py
```

Le second processus se lie uniquement à `127.0.0.1:8765`, utilise une base SQLite
privée sous `.ui-test-artifacts`, refuse les mutations des pages et bloque
requests, pyodbc et les sockets sortantes. Les seules écritures sont les données
de préparation et sessions locales. Les tests Django synchronisent les modèles
dans une base de test ; ils ne certifient pas les migrations ou SQL Server.

Les navigateurs et leurs scripts sont exécutés dans un autre terminal :

```powershell
& 'C:\Users\diagnepa\Documents\MBA\Mining360IA\.venv\Scripts\python.exe' tests/presentation/browser_check.py --variant legacy
& 'C:\Users\diagnepa\Documents\MBA\Mining360IA\.venv\Scripts\python.exe' tests/presentation/browser_check.py --variant responsive
& 'C:\Users\diagnepa\Documents\MBA\Mining360IA\.venv\Scripts\python.exe' tests/presentation/interactions.py
& 'C:\Users\diagnepa\Documents\MBA\Mining360IA\.venv\Scripts\python.exe' tests/presentation/behavior_check.py
& 'C:\Users\diagnepa\Documents\MBA\Mining360IA\.venv\Scripts\python.exe' tests/presentation/catalog_check.py
& 'C:\Users\diagnepa\Documents\MBA\Mining360IA\.venv\Scripts\python.exe' tests/presentation/measure_and_compare.py
& 'C:\Users\diagnepa\Documents\MBA\Mining360IA\.venv\Scripts\python.exe' tests/presentation/build_report.py
```

`browser_check.py --pages ... --widths ...` permet les reprises ciblées. Le
rapport assemble ces reprises sans masquer les cas non vérifiés. Le catalogue
lit l'index privé des captures à la racine canonique ; une copie externe doit
adapter ce chemin et fournir l'index. Les reprises et comparaisons de mesure sont
enregistrées séparément, puis rapprochées dans le bilan.

L'en-tête `X-Presentation-Test` est interprété **uniquement par ce banc** pour
produire les variantes legacy/layout/theme. L'application ne l'utilise pas pour
ses flags, identités ou autorisations. Aucun endpoint de connexion de test n'est
ajouté à Django. Les captures portent `LOCAL UI TEST FIXTURES`.

La simulation d'un clavier par réduction du viewport ne remplace pas un téléphone
physique. Aucun envoi IA, sauvegarde, publication, synchronisation ou déploiement
réel n'est testé. Les sources Power BI/AD réelles restent hors de ce banc.
