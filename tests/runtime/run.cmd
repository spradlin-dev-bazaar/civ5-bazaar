@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio 9.0\Common7\Tools\vsvars32.bat" >nul
set HERE=%~dp0
set OUT=%HERE%out
set GEN=%OUT%\civgen
if not exist "%OUT%" mkdir "%OUT%"
rem Toys dropped from the list below must not linger: the harness expects toy_missing.dll to be absent.
del /q "%OUT%\*.dll" "%OUT%\*.obj" 2>nul

"%HERE%..\..\.venv\Scripts\python.exe" -m unittest discover -s "%HERE%..\generator" >"%OUT%\unit.log" 2>&1
if errorlevel 1 (type "%OUT%\unit.log" & exit /b 1)
"%HERE%..\..\.venv\Scripts\python.exe" -m unittest discover -s "%HERE%..\release" >>"%OUT%\unit.log" 2>&1
if errorlevel 1 (type "%OUT%\unit.log" & exit /b 1)
"%HERE%..\..\.venv\Scripts\python.exe" -m unittest discover -s "%HERE%..\sdk" >>"%OUT%\unit.log" 2>&1
if errorlevel 1 (type "%OUT%\unit.log" & exit /b 1)
"%HERE%..\..\.venv\Scripts\python.exe" -m unittest discover -s "%HERE%..\claude_plugin" >>"%OUT%\unit.log" 2>&1
if errorlevel 1 (type "%OUT%\unit.log" & exit /b 1)
"%HERE%..\..\.venv\Scripts\python.exe" "%HERE%hook_fixture.py" >"%OUT%\generate.log"
if errorlevel 1 (type "%OUT%\generate.log" & exit /b 1)

rem The two layout defines must match common.LAYOUT_DEFINES, or strings and vectors differ across DLLs.
set FLAGS=/nologo /O2 /Oy /Ob2 /GS- /MD /EHsc /W3 /D_SECURE_SCL=0 /D_HAS_ITERATOR_DEBUGGING=0 /DCIV_HOST_API= /I"%HERE%..\..\host" /I"%GEN%\src\fixture" /I"%GEN%\sdk"
rem CivHostEngine.cpp needs the engine's headers, which the tests replace with a fake engine.
(for %%F in ("%HERE%..\..\host\*.cpp") do if /i not "%%~nxF"=="CivHostEngine.cpp" echo "%%~fF")>"%OUT%\host.rsp"
cl %FLAGS% /Fo"%OUT%\\" /Fe"%OUT%\harness.exe" "%HERE%harness.cpp" "%HERE%test_plugins.cpp" "%HERE%test_lifecycle.cpp" "%HERE%test_plugins_screen.cpp" "%HERE%test_hand_hooks.cpp" "%HERE%test_paths.cpp" "%HERE%test_mods.cpp" "%HERE%test_lua.cpp" "%HERE%test_saves.cpp" "%HERE%test_values.cpp" "%HERE%test_functions.cpp" "%GEN%\src\fixture\fake_engine.cpp" "%GEN%\src\fixture\CivHookTable.cpp" @"%OUT%\host.rsp" >"%OUT%\build.log"
if errorlevel 1 (type "%OUT%\build.log" & exit /b 1)
for %%T in (BASIC SECOND SHAPES CONFLICT NEWER MAJOR NO_VERSION OLDER FAULT_REPLACE FAULT_BEFORE FAULT_KEPT KEPT ENTRY_FAULT ENTRY_BREAK BENCH REENTRANT THREADS NO_ENTRY DECLINE LATE_FAULT BAD_HOOKS THROW VETO NO_SHUTDOWN HAND HAND_SECOND HAND_FAULT HAND_REPLACE EMPTY_NAME LUA SAVE SAVE_SECOND SAVE_TWIN VALUES VALUES_READER TAKE_REPLACE FUNCTION_TWIN KEPT_CALLER) do (
	cl %FLAGS% /LD /DTOY_%%T /Fo"%OUT%\toy_%%T.obj" /Fe"%OUT%\toy_%%T.dll" "%HERE%toy_plugins.cpp" >>"%OUT%\build.log"
	if errorlevel 1 (type "%OUT%\build.log" & exit /b 1)
)
for %%T in (FAULT OVERFLOW) do (
	cl %FLAGS% /Zi /LD /DTOY_%%T /Fo"%OUT%\toy_%%T.obj" /Fd"%OUT%\toy_%%T_compile.pdb" /Fe"%OUT%\toy_%%T.dll" "%HERE%toy_plugins.cpp" /link /DEBUG /PDB:"%OUT%\toy_%%T.pdb" >>"%OUT%\build.log"
	if errorlevel 1 (type "%OUT%\build.log" & exit /b 1)
)
rem These toys link against a DLL that is never built, so Windows cannot load them.
(echo LIBRARY toy_absent_host.dll& echo EXPORTS& echo ToyAbsentFunction)>"%OUT%\toy_absent_host.def"
lib /nologo /machine:x86 /def:"%OUT%\toy_absent_host.def" /out:"%OUT%\toy_absent_host.lib" >>"%OUT%\build.log"
if errorlevel 1 (type "%OUT%\build.log" & exit /b 1)
for %%T in (NEWER_IMPORTS LOAD_FAILS) do (
	cl %FLAGS% /LD /DTOY_%%T /Fo"%OUT%\toy_%%T.obj" /Fe"%OUT%\toy_%%T.dll" "%HERE%toy_plugins.cpp" "%OUT%\toy_absent_host.lib" >>"%OUT%\build.log"
	if errorlevel 1 (type "%OUT%\build.log" & exit /b 1)
)
rem VS2008 Express builds no 64-bit DLL, so a 64-bit one from Windows stands in. A 32-bit cmd sees the 64-bit folder only as
rem Sysnative.
set WIN64=%SystemRoot%\System32
if exist "%SystemRoot%\Sysnative\version.dll" set WIN64=%SystemRoot%\Sysnative
copy /y "%WIN64%\version.dll" "%OUT%\toy_64bit.dll" >nul
if errorlevel 1 (echo could not copy a 64-bit DLL from %WIN64% & exit /b 1)
(echo LIBRARY toy_ordinals.dll& echo EXPORTS& echo CivPluginShutdown @1& echo CivPluginEntry @2& echo CivPluginApiVersion @3 DATA)>"%OUT%\toy_ordinals.def"
cl %FLAGS% /LD /DTOY_ORDINALS /Fo"%OUT%\toy_ordinals.obj" /Fe"%OUT%\toy_ordinals.dll" "%HERE%toy_plugins.cpp" /link /DEF:"%OUT%\toy_ordinals.def" >>"%OUT%\build.log"
if errorlevel 1 (type "%OUT%\build.log" & exit /b 1)
set FAILED=0
"%OUT%\harness.exe" "%OUT%"
if not "%ERRORLEVEL%"=="0" set FAILED=1
rem Fresh runs in reverse order and of each section alone show that no section relies on what another one left loaded.
echo.
echo ==== the same sections in reverse order
"%OUT%\harness.exe" "%OUT%" reverse
if not "%ERRORLEVEL%"=="0" set FAILED=1
echo.
echo ==== each section alone
set SECTIONS=0
for /f "delims=" %%S in ('""%OUT%\harness.exe" "%OUT%" list"') do call :alone "%%S"
if "%SECTIONS%"=="0" (
	echo FAIL  the test program listed no sections
	set FAILED=1
)
endlocal & exit /b %FAILED%

:alone
set /a SECTIONS+=1
"%OUT%\harness.exe" "%OUT%" %1 >"%OUT%\alone.log"
if "%ERRORLEVEL%"=="0" (
	echo PASS  section %~1 runs alone
	exit /b 0
)
echo FAIL  section %~1 runs alone
type "%OUT%\alone.log"
set FAILED=1
exit /b 0
