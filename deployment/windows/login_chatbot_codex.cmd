@echo off
"%~dp0..\..\..\.venv\Scripts\python.exe" "%~dp0login_chatbot_codex.py" %*
exit /b %errorlevel%
