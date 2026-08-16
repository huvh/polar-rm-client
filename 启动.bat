@echo off
setlocal
cd /d "%~dp0"
title POLAR-RM Custom Client

rem ------------------------------------------------------------------
rem Frozen field package: START-POLAR-RM.bat + POLAR-RM.exe owns the
rem fail-closed startup preflight. This launcher also supports that
rem layout when the exe is placed next to it.
rem Source tree: launch main.py with an interpreter that already exists
rem on this machine. Never creates a venv and never installs packages.
rem ------------------------------------------------------------------

if exist "POLAR-RM.exe" goto frozen

if not exist "main.py" (
    echo Neither POLAR-RM.exe nor main.py was found.
    echo Keep this launcher in the client root folder.
    pause
    exit /b 1
)

set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=%~dp0.venv\Scripts\python.exe"
if not defined PYEXE (
    where py >nul 2>nul && set "PYEXE=py -3"
)
if not defined PYEXE (
    where python >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
    echo No Python interpreter was found on this machine.
    echo This launcher never creates a Python environment or downloads packages.
    echo Install Python 3.11+ yourself, or use START-POLAR-RM.bat from the
    echo self-contained field candidate package.
    pause
    exit /b 1
)

echo [POLAR-RM] Source mode: %PYEXE% main.py %*
rem The app only looks at bin\ffmpeg.exe or %POLAR_FFMPEG%. Reuse a ffmpeg
rem that is already installed on this machine; nothing is downloaded.
if not exist "%~dp0bin\ffmpeg.exe" (
    for /f "delims=" %%F in ('where ffmpeg 2^>nul') do (
        if not defined POLAR_FFMPEG set "POLAR_FFMPEG=%%F"
    )
)
%PYEXE% "%~dp0main.py" %*
if errorlevel 1 (
    echo POLAR-RM exited with an error.
    pause
)
exit /b %errorlevel%

:frozen
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
