@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio 9.0\Common7\Tools\vsvars32.bat" >nul
set HERE=%~dp0
set OUT=%HERE%out
if not exist "%OUT%" mkdir "%OUT%"
set FLAGS=/nologo /O2 /Oy /Ob2 /GS- /MD /EHsc /W3 /D_SECURE_SCL=0 /D_HAS_ITERATOR_DEBUGGING=0 /I"%HERE%..\..\host" /I"%HERE%."

cl %FLAGS% /Fo"%OUT%\\" /Fe"%OUT%\harness.exe" "%HERE%harness.cpp" "%HERE%fake_engine.cpp" "%HERE%..\..\host\CivHostRuntime.cpp" >"%OUT%\build.log"
if errorlevel 1 (type "%OUT%\build.log" & exit /b 1)
for %%T in (BASIC SECOND CONFLICT NEWER MAJOR FAULT ENTRY_FAULT BENCH NO_ENTRY) do (
	cl %FLAGS% /LD /DTOY_%%T /Fo"%OUT%\toy_%%T.obj" /Fe"%OUT%\toy_%%T.dll" "%HERE%toy_plugins.cpp" >>"%OUT%\build.log"
	if errorlevel 1 (type "%OUT%\build.log" & exit /b 1)
)
"%OUT%\harness.exe" "%OUT%"
endlocal & exit /b %ERRORLEVEL%
