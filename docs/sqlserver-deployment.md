# Mining360 SQL Server deployment

Mining360 production state is stored in the dedicated `Mining360App` database.
`MiningProd` remains an external operational source and must not be used as the
Django application database. The legacy `Mining360` mirror database is not the
Django database either.

## Required machine environment

Configure these as machine-level variables on BODEFM. Keep credentials out of
Git and out of application configuration exports.

```text
MINING360_DATABASE_ENGINE=mssql
MINING360_APP_SQL_SERVER=BODEFM
MINING360_APP_SQL_DATABASE=Mining360App
MINING360_APP_SQL_PORT=1433
MINING360_APP_SQL_USER=<service account>
MINING360_APP_SQL_PASSWORD=<secret>
MINING360_APP_SQL_DRIVER=ODBC Driver 18 for SQL Server
MINING360_APP_SQL_EXTRA_PARAMS=Encrypt=optional;TrustServerCertificate=yes;Connection Timeout=15
MINING360_SECRET_KEY=<stable production secret>
MINING360_DEBUG=0
MINING360_ALLOWED_HOSTS=bodefm,<production DNS name>
MINING360_SQL_CONFIG_STORE=0
```

Use a Windows service identity and integrated authentication instead of SQL
credentials when IT makes that account available. In that case omit the user
and password variables.

## Deployment sequence

```powershell
git pull
python -m pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py check --deploy
```

The service must start only after `migrate` succeeds. Do not copy `db.sqlite3`
to BODEFM after the initial migration.

## Initial migration

Keep the original SQLite file as a read-only rollback artifact and run:

```powershell
$env:MINING360_LEGACY_SQLITE_PATH = "C:\migration\db.sqlite3"
python manage.py migrate_application_to_sqlserver --preview `
  --report knowledge_population_reports\sqlserver_migration_preview.json
python manage.py migrate_application_to_sqlserver --apply `
  --replace-empty-target --batch-size 20 `
  --report knowledge_population_reports\sqlserver_migration_apply.json
```

The command validates every managed model count before declaring the transfer
complete. It does not call OpenAI or any other paid API.

## Rollback

1. Stop the Mining360 web service.
2. Preserve `Mining360App` for diagnosis; do not overwrite `MiningProd`.
3. Restore the latest SQL Server backup of `Mining360App`.
4. Revert the application release through Git.
5. Run `python manage.py migrate --noinput` and restart the service.

SQLite is not a production rollback target after SQL Server cutover.
