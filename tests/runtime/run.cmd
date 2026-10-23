@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio 9.0\Common7\Tools\vsvars32.bat" >nul
set HERE=%~dp0
set OUT=%HERE%out
set GEN=%OUT%\civgen
if not exist "%OUT%" mkdir "%OUT%"
rem Toys dropped from the list below must not linger: the harness expects toy_missing.dll to be absent.
del /q "%OUT%\*.dll" "%OUT%\*.obj" 2>nul

"%HERE%..\..\.venv\Scripts\python.exe" "%HERE%hook_fixture.py" >"%OUT%\generate.log"
if errorlevel 1 (type "%OUT%\generate.log" & exit /b 1)

rem The two layout defines must match common.LAYOUT_DEFINES, or strings and vectors differ across DLLs.
set FLAGS=/nologo /O2 /Oy /Ob2 /GS- /MD /EHsc /W3 /D_SECURE_SCL=0 /D_HAS_ITERATOR_DEBUGGING=0 /DCIV_HOST_API= /I"%HERE%..\..\host" /I"%GEN%\src\fixture" /I"%GEN%\sdk"
cl %FLAGS% /Fo"%OUT%\\" /Fe"%OUT%\harness.exe" "%HERE%harness.cpp" "%GEN%\src\fixture\fake_engine.cpp" "%GEN%\src\fixture\CivHookTable.cpp" "%HERE%..\..\host\CivHostRuntime.cpp" "%HERE%..\..\host\CivHostOrder.cpp" "%HERE%..\..\host\CivHostSetup.cpp" >"%OUT%\build.log"
if errorlevel 1 (type "%OUT%\build.log" & exit /b 1)
for %%T in (BASIC SECOND SHAPES CONFLICT NEWER MAJOR FAULT FAULT_REPLACE FAULT_BEFORE ENTRY_FAULT ENTRY_BREAK BENCH REENTRANT THREADS NO_ENTRY) do (
	cl %FLAGS% /LD /DTOY_%%T /Fo"%OUT%\toy_%%T.obj" /Fe"%OUT%\toy_%%T.dll" "%HERE%toy_plugins.cpp" >>"%OUT%\build.log"
	if errorlevel 1 (type "%OUT%\build.log" & exit /b 1)
)
"%OUT%\harness.exe" "%OUT%"
endlocal & exit /b %ERRORLEVEL%
