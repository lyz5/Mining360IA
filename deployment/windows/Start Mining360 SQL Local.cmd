@echo off
setlocal
set "ROOT=%~dp0..\.."
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

set "DJANGO_SETTINGS_MODULE=Mining360IA.settings_sqlserver_local"
set "MINING360_LOCAL_SQLSERVER=1"
set "MINING360_DATABASE_ENGINE=mssql"
set "MINING360_APP_SQL_SERVER=localhost\MSSQL_IA"
set "MINING360_APP_SQL_DRIVER=ODBC Driver 18 for SQL Server"
set "MINING360_APP_SQL_EXTRA_PARAMS=Encrypt=optional;TrustServerCertificate=yes;Connection Timeout=15"

if not exist "%PYTHON%" exit /b 1
cd /d "%ROOT%"
"%PYTHON%" manage.py runserver 127.0.0.1:8001
