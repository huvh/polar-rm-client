@echo off
setlocal
cd /d "%~dp0"
title POLAR-RM Custom Client

if not exist "POLAR-RM.exe" (
    echo POLAR-RM.exe was not found.
    echo Use START-POLAR-RM.bat from the self-contained field candidate package.
    echo This launcher never creates a Python environment or downloads packages.
    pause
    exit /b 1
)

if /I "%~1"=="--replay-field-log" goto launch
"%~dp0POLAR-RM.exe" --preflight --official --codec-selftest --preflight-output "%~dp0user_data\logs\startup-preflight.json"
if errorlevel 1 (
    echo Startup preflight failed. See user_data\logs\startup-preflight.json.
    pause
    exit /b 2
)

:launch
"%~dp0POLAR-RM.exe" %*
if errorlevel 1 echo POLAR-RM exited with an error.
pause
exit /b %errorlevel%
