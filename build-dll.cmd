@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio 9.0\Common7\Tools\vsvars32.bat" >nul
set INCLUDE=%~dp0tools\shims;%INCLUDE%
cd /d "%~dp0CvGameCoreSource"
vcbuild /nologo /useenv Expansion2.vs2008.sln "Mod|Win32"
endlocal & exit /b %ERRORLEVEL%
