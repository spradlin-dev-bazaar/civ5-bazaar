@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio 9.0\Common7\Tools\vsvars32.bat" >nul
set INCLUDE=%~dp0tools\shims;%INCLUDE%
"%~dp0.venv\Scripts\python.exe" "%~dp0tools\generator\analyze.py" || exit /b 1
"%~dp0.venv\Scripts\python.exe" "%~dp0tools\generator\generate.py" || exit /b 1
cd /d "%~dp0CvGameCoreSource\BuildTemp\civgen\src"
vcbuild /nologo /useenv Expansion2.civgen.sln "Mod|Win32"
endlocal & exit /b %ERRORLEVEL%
