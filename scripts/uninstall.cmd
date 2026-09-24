@echo off
rem Uninstall skillpm itself (Windows). Works from both cmd and PowerShell; no execution-policy change needed.
rem   uninstall.cmd         remove the tool; installed Skills and %USERPROFILE%\.skillpm are kept
rem   uninstall.cmd -All    also delete %USERPROFILE%\.skillpm (config, state, cache, backups)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %*
exit /b %errorlevel%
