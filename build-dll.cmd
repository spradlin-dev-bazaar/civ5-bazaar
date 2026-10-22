@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio 9.0\Common7\Tools\vsvars32.bat" >nul
set INCLUDE=%~dp0tools\shims;%INCLUDE%
if not "%~1"=="" if /i not "%~1"=="bench" (echo usage: build-dll.cmd [bench] & exit /b 1)
if /i "%~1"=="bench" set CL=/DCIV_TURN_BENCH /I"%~dp0host"
cd /d "%~dp0CvGameCoreSource"
rem The bench switch only changes CvGame.cpp, and vcbuild cannot see it, so always recompile that file.
pushd CvGameCoreDLL_Expansion2
copy /b CvGame.cpp +,, >nul
set TOUCHED=%ERRORLEVEL%
popd
if not "%TOUCHED%"=="0" (echo Could not mark CvGame.cpp for recompiling. & exit /b 1)
vcbuild /nologo /useenv Expansion2.vs2008.sln "Mod|Win32"
endlocal & exit /b %ERRORLEVEL%
