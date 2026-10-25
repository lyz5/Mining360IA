@echo off
set "ROOT=%~dp0..\.."
set "PYTHON=%ROOT%\.venv\Scripts\pythonw.exe"
if not exist "%PYTHON%" set "PYTHON=%ROOT%\..\.venv\Scripts\pythonw.exe"
if not exist "%PYTHON%" exit /b 1
cd /d "%ROOT%"
start "" "%PYTHON%" -m desktop.global_control_center
