@echo off
rem Windows runs no PowerShell script by default; Bypass allows this one run.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0release.ps1"
exit /b %ERRORLEVEL%
