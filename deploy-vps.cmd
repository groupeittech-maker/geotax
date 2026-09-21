@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy-vps.ps1" %*
exit /b %ERRORLEVEL%
