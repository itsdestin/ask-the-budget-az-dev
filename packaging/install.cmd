@echo off
setlocal EnableDelayedExpansion
rem ============================================================================
rem  JLBC Insight installer (Plan 5, Task 16 - spec S7/S8)
rem
rem  Everything here is deliberately something a standard user account can do:
rem  no admin rights, no PATH edits, no registry writes, no services. It
rem  creates two shortcuts, records where the shared folder is, and prints
rem  where the logs live. That is the whole install.
rem
rem  Run it by double-clicking, after unzipping the bundle into
rem  %LOCALAPPDATA%\JLBC-Insight.
rem ============================================================================

set "INSTALL_DIR=%~dp0"
if "%INSTALL_DIR:~-1%"=="\" set "INSTALL_DIR=%INSTALL_DIR:~0,-1%"
set "STATE_DIR=%LOCALAPPDATA%\JLBC-Insight"

echo.
echo   JLBC Insight - setup
echo   ====================
echo.
echo   Installing from: %INSTALL_DIR%
echo.

rem --- sanity: refuse to configure a bundle that did not unzip completely ----
rem  A half-extracted zip is a common failure on a slow share, and it produces
rem  symptoms ("it just doesn't open") that look nothing like the cause.
if not exist "%INSTALL_DIR%\python\pythonw.exe" goto :incomplete
if not exist "%INSTALL_DIR%\launcher.pyw"      goto :incomplete
if not exist "%INSTALL_DIR%\webapp\dist\index.html" goto :incomplete
if not exist "%INSTALL_DIR%\models\mineru.json" goto :incomplete

rem --- 1. where is the shared budget folder? --------------------------------
echo   The budget documents live in a shared folder on the network.
echo   Your IT contact or the person who set this up can tell you the path.
echo   It usually looks like:  \\server\share\JLBC-Insight-Data
echo.
set "DATA_DIR="
set /p "DATA_DIR=  Shared folder path (press Enter to decide later): "

if not defined DATA_DIR goto :skip_data
if not exist "%DATA_DIR%\" (
    echo.
    echo   That folder could not be reached right now. Recording it anyway -
    echo   if it is a network drive that is simply not connected yet, the app
    echo   will find it once you are on the network. You can change it later
    echo   from inside the app.
    echo.
)

rem  Written directly rather than through the app because the app is not
rem  running yet. SHAPE COUPLING: app/machine_config.py (Plan 5 Task 10) is the
rem  canonical reader/writer of this file - if its schema changes, this block
rem  changes with it. See packaging/README.md.
if not exist "%STATE_DIR%" mkdir "%STATE_DIR%"
> "%STATE_DIR%\machine.json" (
    echo {
    echo   "data_dir": "!DATA_DIR:\=\\!"
    echo }
)
echo   Recorded shared folder: !DATA_DIR!
:skip_data

rem --- 2. make MinerU's model path absolute ---------------------------------
rem  The bundle ships a placeholder because the install location is not known
rem  at build time, and MinerU requires an absolute path.
"%INSTALL_DIR%\python\python.exe" -c "import json,sys,pathlib; p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text()); d['models-dir']['pipeline']=str(pathlib.Path(sys.argv[2])/'models'/'mineru'); p.write_text(json.dumps(d,indent=2))" "%INSTALL_DIR%\models\mineru.json" "%INSTALL_DIR%" 2>nul
if errorlevel 1 (
    echo   WARNING: could not set the model path. PDF processing may not work
    echo            on this machine. Everything else will.
)

rem --- 3. shortcuts ---------------------------------------------------------
rem  PowerShell + WScript.Shell is the standard no-admin way to create a .lnk.
set "SM_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
call :mkshortcut "%SM_DIR%\JLBC Insight.lnk"
call :mkshortcut "%USERPROFILE%\Desktop\JLBC Insight.lnk"

echo.
echo   Setup complete.
echo.
echo   Start it from:   the Start Menu, or the JLBC Insight icon on your Desktop
echo   Shared folder:   %DATA_DIR%
echo   Log files:       %STATE_DIR%\logs
echo.
echo   If it ever will not start, send the newest file in that logs folder to
echo   whoever supports this app.
echo.
pause
exit /b 0

:mkshortcut
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%~1');" ^
  "$s.TargetPath='%INSTALL_DIR%\python\pythonw.exe';" ^
  "$s.Arguments='\"%INSTALL_DIR%\launcher.pyw\"';" ^
  "$s.WorkingDirectory='%INSTALL_DIR%';" ^
  "$s.IconLocation='%INSTALL_DIR%\python\pythonw.exe,0';" ^
  "$s.Description='JLBC Insight';" ^
  "$s.Save()" >nul 2>&1
if errorlevel 1 (
    echo   WARNING: could not create the shortcut at %~1
) else (
    echo   Created shortcut: %~1
)
exit /b 0

:incomplete
echo.
echo   This folder is missing files that should have been in the zip.
echo   The most likely cause is that the zip did not finish extracting.
echo.
echo   Delete this folder, copy the zip file to your own computer first,
echo   then extract it again and run this installer.
echo.
pause
exit /b 1
