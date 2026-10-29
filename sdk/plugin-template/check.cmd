@echo off
rem Builds the mod, then plays checks.toml in Civilization V with nobody at the keyboard. bazaar_check\README.md says
rem what it needs and does.
setlocal
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHON="
for %%p in ("py -3" python) do if not defined PYTHON call %%~p -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PYTHON=%%~p"
if not defined PYTHON (echo The checks need Python 3.11 or newer: install it from python.org. & exit /b 1)
call "%~dp0build.cmd" || exit /b 1
cd /d "%~dp0"
call %PYTHON% -m bazaar_check checks.toml
endlocal & exit /b %ERRORLEVEL%
