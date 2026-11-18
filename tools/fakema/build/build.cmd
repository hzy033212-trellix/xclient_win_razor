@echo off
rem Wrapper so the build can be started from cmd/Explorer without changing the
rem PowerShell execution policy. All arguments are forwarded.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-FakeMaXClient.ps1" %*
exit /b %ERRORLEVEL%
