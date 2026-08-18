@echo off
set "ROOT=%~dp0..\.."
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_control_center.ps1"
