@echo off
rem Builds the mod, then starts Civilization V with it switched on for you to play. Closing the game puts your
rem files back as they were; saves you make by hand stay. bazaar_check\README.md says more.
call "%~dp0check.cmd" --play || (pause & exit /b 1)
