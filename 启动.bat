@echo off
setlocal
cd /d "%~dp0"
title POLAR-RM Custom Client

rem ====================================================================
rem POLAR-RM launcher  --  ASCII ONLY, on purpose.
rem
rem cmd.exe reads .bat files using the console OEM codepage (GBK/936 on
rem Simplified Chinese Windows, 437/1252 elsewhere). Non-ASCII bytes in a
rem UTF-8 .bat get re-split on those codepages and can swallow the first
rem character of the next line (a real failure seen here: "exit /b" parsed
rem as "xit"), which breaks the script before it can report anything.
rem So: keep this file pure ASCII and put Chinese documentation in README.
rem
rem Goals:
rem   1. Double-click on any Windows machine -> client starts.
rem   2. Missing dependencies are provisioned automatically into a
rem      project-local .venv-polar. The user's own .venv is never touched
rem      or deleted.
rem   3. Interpreters are validated by actually running them. A .venv whose
rem      base interpreter was removed still has python.exe on disk but dies
rem      with "No Python at ...", so file existence proves nothing.
rem   4. Only requirements-core.txt is installed on first run. openvino is
rem      large and imported lazily (only for Tongji local vision), so it
rem      must not block startup.
rem ====================================================================

if exist "POLAR-RM.exe" goto frozen

if not exist "main.py" (
    echo [X] Neither POLAR-RM.exe nor main.py was found next to this launcher.
    echo     Keep this launcher in the client root folder.
    pause
    exit /b 1
)

set "PYEXE="
set "BASE="
set "PYARGS="
set "BASEARGS="

rem ---- 1) look for an interpreter that already has the dependencies ------
if exist "%~dp0.venv-polar\Scripts\python.exe" (
    set "CAND=%~dp0.venv-polar\Scripts\python.exe"
    call :probe_path
)
if defined PYEXE goto ready

if exist "%~dp0.venv\Scripts\python.exe" (
    set "CAND=%~dp0.venv\Scripts\python.exe"
    call :probe_path
)
if defined PYEXE goto ready

set "CAND=py"
set "CANDARGS=-3"
call :probe_bare
if defined PYEXE goto ready

set "CAND=python"
set "CANDARGS="
call :probe_bare
if defined PYEXE goto ready

rem ---- 2) nothing provisioned yet: auto-create the project venv ----------
if not defined BASE goto no_python

echo [POLAR-RM] Python found, but client dependencies are not installed yet.
echo            Auto-provisioning .venv-polar (your existing .venv is untouched).
echo            First run downloads PySide6 / OpenCV / numpy / paho-mqtt / pyserial
echo            and can take a few minutes.
call :provision
if defined PYEXE goto ready

echo.
echo [X] Automatic dependency installation failed - usually no network access
echo     or no reachable package index. Run these once by hand, then double-click
echo     this launcher again (the third line uses a China mirror):
echo.
echo         "%BASE%" %BASEARGS% -m venv "%~dp0.venv-polar"
echo         "%~dp0.venv-polar\Scripts\python.exe" -m pip install -r requirements-core.txt
echo         "%~dp0.venv-polar\Scripts\python.exe" -m pip install -r requirements-core.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
pause
exit /b 3

:no_python
echo [X] No usable Python 3 interpreter was found on this machine.
echo     The client needs Python 3.10 or newer (3.12 recommended). Install it,
echo     then double-click this launcher again - dependencies are installed
echo     automatically, you do not need to run pip yourself.
echo     Alternatively use the self-contained field package:
echo     START-POLAR-RM.bat + POLAR-RM.exe.
pause
exit /b 1

rem ====================================================================
rem Auto-provision: create venv, install core deps (default index, then a
rem China mirror). On success PYEXE points at the new venv interpreter.
rem ====================================================================
:provision
rem A .venv-polar left over from a moved/renamed Python install still has
rem python.exe on disk but dies when run. Reusing it makes pip install fail
rem forever with no way to recover, so verify it actually runs first. If it
rem does not, move it aside (never delete user data) and build a fresh one.
if not exist "%~dp0.venv-polar\Scripts\python.exe" goto provision_create
"%~dp0.venv-polar\Scripts\python.exe" -c "import sys" >nul 2>nul
if not errorlevel 1 goto provision_pip
echo            Existing .venv-polar is broken (base interpreter gone); rebuilding.
set "BROKEN="
for /l %%N in (1,1,4) do if not defined BROKEN (
    if not exist "%~dp0.venv-polar.broken-%%N" set "BROKEN=%~dp0.venv-polar.broken-%%N"
)
if not defined BROKEN set "BROKEN=%~dp0.venv-polar.broken-old"
move "%~dp0.venv-polar" "%BROKEN%" >nul 2>nul
if exist "%~dp0.venv-polar\Scripts\python.exe" exit /b 1

:provision_create
"%BASE%" %BASEARGS% -m venv "%~dp0.venv-polar" >nul 2>nul
if not exist "%~dp0.venv-polar\Scripts\python.exe" exit /b 1

:provision_pip
set "VPY=%~dp0.venv-polar\Scripts\python.exe"
echo            [1/2] Upgrading pip ...
"%VPY%" -m pip install --upgrade pip --disable-pip-version-check -q >nul 2>nul

echo            [2/2] Installing core requirements ...
"%VPY%" -m pip install -r "%~dp0requirements-core.txt" --disable-pip-version-check -q
if not errorlevel 1 goto provision_verify

echo            Default index failed, retrying with the Tsinghua mirror ...
"%VPY%" -m pip install -r "%~dp0requirements-core.txt" --disable-pip-version-check -q -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 exit /b 1

:provision_verify
"%VPY%" -c "import PySide6, cv2, numpy, paho.mqtt.client, serial" >nul 2>nul || exit /b 1
rem Never write set "PYEXE="%VPY%"" - nested quotes leak a trailing quote
rem into the variable. Store the bare path and quote it at :ready instead.
set "PYEXE=%VPY%"
set "PYARGS="
exit /b 0

rem ====================================================================
rem Interpreter probes. CAND is the interpreter command for this call.
rem   runs "import sys"      -> remembered as BASE (can create a venv)
rem   also runs "import PySide6" -> used as PYEXE (ready to launch)
rem ====================================================================
:probe_path
set "CANDARGS="
call :probe_bare
exit /b 0

:probe_bare
"%CAND%" %CANDARGS% -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul || exit /b 0
if not defined BASE (
    set "BASE=%CAND%"
    set "BASEARGS=%CANDARGS%"
)
"%CAND%" %CANDARGS% -c "import PySide6, cv2, numpy, paho.mqtt.client, serial" >nul 2>nul && (
    set "PYEXE=%CAND%"
    set "PYARGS=%CANDARGS%"
)
exit /b 0

rem ====================================================================
rem Launch
rem ====================================================================
:ready
rem Executable and launcher arguments are separate. Quote only the executable.

echo [POLAR-RM] Source mode: "%PYEXE%" %PYARGS% main.py %*

rem The app only looks at bin\ffmpeg.exe or %POLAR_FFMPEG%. Reuse an ffmpeg
rem already installed on this machine; nothing is downloaded. Without it the
rem video source is unavailable but the UI still starts.
if not exist "%~dp0bin\ffmpeg.exe" (
    for /f "delims=" %%F in ('where ffmpeg 2^>nul') do (
        if not defined POLAR_FFMPEG set "POLAR_FFMPEG=%%F"
    )
)
"%PYEXE%" %PYARGS% "%~dp0main.py" %*
set "RC=%errorlevel%"
if not "%RC%"=="0" (
    echo POLAR-RM exited with code %RC%. Scroll up for the log.
    pause
)
exit /b %RC%

rem ====================================================================
rem Self-contained field package: POLAR-RM.exe owns the fail-closed preflight
rem ====================================================================
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
