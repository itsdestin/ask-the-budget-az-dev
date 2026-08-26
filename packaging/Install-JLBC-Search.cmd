@echo off
setlocal EnableDelayedExpansion
rem ============================================================================
rem  JLBC Search - ONE-CLICK installer
rem
rem  This sits on the USB drive NEXT TO the bundle zip. Double-clicking it is
rem  the entire setup. In order it: finds the zip, asks where the program
rem  should live and where the shared data folder is, stops a copy that is
rem  already running (so Windows is not holding its files), removes the
rem  previous version, extracts the new one, records the data folder, leaves
rem  uploads switched off on this PC unless somebody has already chosen, and
rem  makes the Start-Menu and Desktop shortcuts.
rem
rem  No admin rights, no Python, no Java, nothing else to install.
rem  This is the ONLY installer - there is no second script to run.
rem ============================================================================

set "USB_DIR=%~dp0"
if "%USB_DIR:~-1%"=="\" set "USB_DIR=%USB_DIR:~0,-1%"

echo.
echo   ============================================================
echo    JLBC Search - setup
echo   ============================================================
echo.
echo   This will install JLBC Search on this PC. It asks for two
echo   folders and does everything else itself.
echo.

rem --- find the bundle zip sitting next to this script -----------------------
set "ZIP="
for %%f in ("%USB_DIR%\JLBC-Search-*.zip") do set "ZIP=%%f"
if not defined ZIP (
    echo   ERROR: no JLBC-Search-*.zip found next to this script.
    echo   Put this script in the same folder as the bundle zip and try again.
    echo.
    pause
    exit /b 1
)
echo   Using bundle: %ZIP%
echo.

rem --- Q1: where to install the program --------------------------------------
set "ROOT_DIR=%LOCALAPPDATA%\JLBC-Search"
set "INSTALL_DEFAULT=%ROOT_DIR%\program"
echo   Where should the program live?
echo     Press Enter for the recommended spot:
echo       %INSTALL_DEFAULT%
echo     (or drag a different empty folder here, then Enter)
set "INSTALL_DIR="
set /p "INSTALL_DIR=  Install folder [%INSTALL_DEFAULT%]: "
if not defined INSTALL_DIR set "INSTALL_DIR=%INSTALL_DEFAULT%"
set "INSTALL_DIR=%INSTALL_DIR:"=%"
if "%INSTALL_DIR:~-1%"=="\" set "INSTALL_DIR=%INSTALL_DIR:~0,-1%"
rem  The old QUICKSTART named %ROOT_DIR% itself. Installing the program THERE
rem  would put it beside the chats/memos/pointer again and make every later
rem  upgrade dangerous. Refuse it rather than silently reinstalling the 0.9.1 layout.
if /I "%INSTALL_DIR%"=="%ROOT_DIR%" (
    echo   ERROR: the program must live in a folder INSIDE %ROOT_DIR%,
    echo   not in that folder itself. Press Enter next time to take the default.
    pause
    exit /b 1
)
echo   Installing to: %INSTALL_DIR%
echo.

rem --- Q2: where is the shared data (the corpus)? -----------------------------
echo   Where is the shared budget-data folder?
echo     This is the folder that has the "lancedb" folder inside it
echo     (the search index). You can drag the folder here, then press Enter.
echo     Press Enter alone to decide later - the app asks on first run.
set "DATA_DIR="
set /p "DATA_DIR=  Shared data folder (Enter to skip): "
set "DATA_DIR=%DATA_DIR:"=%"
if defined DATA_DIR if "%DATA_DIR:~-1%"=="\" set "DATA_DIR=%DATA_DIR:~0,-1%"
echo.

rem --- stop a running copy before touching its files ---------------------------
rem  Windows locks python312.dll and every .pyd while pythonw.exe runs, so an
rem  upgrade over a live server fails halfway and leaves a mixed-version tree.
rem  running.json (written by launcher.pyw) carries the pid; an installed
rem  Python is always still on disk when it exists. The image name is checked
rem  so a reused pid never kills a stranger.
set "RUNNING=%ROOT_DIR%\running.json"
set "OLDPID="
if exist "%RUNNING%" (
    set "OLDPY="
    if exist "%INSTALL_DIR%\python\python.exe" set "OLDPY=%INSTALL_DIR%\python\python.exe"
    if exist "%ROOT_DIR%\python\python.exe" set "OLDPY=%ROOT_DIR%\python\python.exe"
    rem  Write the pid to a temp file rather than parse it inside for /f -
    rem  nested quotes inside a for /f command are the classic batch trap.
    if defined OLDPY (
        "!OLDPY!" -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8')).get('pid',''))" "%RUNNING%" > "%TEMP%\jlbc-pid.txt" 2>nul
        set /p OLDPID=<"%TEMP%\jlbc-pid.txt"
        del /q "%TEMP%\jlbc-pid.txt" >nul 2>&1
    )
)
if defined OLDPID (
    tasklist /FI "PID eq %OLDPID%" /FI "IMAGENAME eq pythonw.exe" | find /I "pythonw.exe" >nul
    if not errorlevel 1 (
        echo   JLBC Search is running and must be stopped to upgrade.
        echo   Press any key to stop it. ^(An upload in progress will start
        echo   over afterwards.^)
        pause >nul
        echo   Stopping the running copy of JLBC Search...
        taskkill /PID %OLDPID% /T /F >nul 2>&1
        timeout /t 2 /nobreak >nul
    )
)
if exist "%RUNNING%" del /q "%RUNNING%" >nul 2>&1

rem --- one-time cleanup of the 0.9.1 layout (program files at the root) -------
if exist "%ROOT_DIR%\python\pythonw.exe" (
    echo   Removing the old program files from %ROOT_DIR% ...
    for %%d in (python site-packages jre models app harness store retrieval chunking citation identity memo ingest webapp data samples scripts funds primer) do (
        if exist "%ROOT_DIR%\%%d" rmdir /s /q "%ROOT_DIR%\%%d"
    )
    for %%f in (launcher.pyw install.cmd QUICKSTART.md VERSION MANIFEST.json) do (
        if exist "%ROOT_DIR%\%%f" del /q "%ROOT_DIR%\%%f"
    )
)

rem --- replace the program folder ---------------------------------------------
rem  Deleted ONLY when it is recognisably ours (launcher.pyw + VERSION inside);
rem  a typed folder that is something else is never touched.
if exist "%INSTALL_DIR%\launcher.pyw" if exist "%INSTALL_DIR%\VERSION" (
    echo   Removing the previous version...
    rmdir /s /q "%INSTALL_DIR%"
)
rem  That rmdir fails and says nothing when Windows is still holding
rem  python312.dll - the stop step above was skipped, or 2 s was not long
rem  enough for taskkill to release it. tar then fails and the extraction
rem  message blamed the USB drive, which is never the cause of THAT.
rem
rem  It also fails HALFWAY: the unlocked files go first, launcher.pyw and
rem  VERSION among them, so the guard above can never match again. Without
rem  this second, unguarded attempt the folder is unremovable for ever - the
rem  user closes the app, runs the installer again, and is told it is "still
rem  open" about a closed app, on every run, permanently. The retry is
rem  deliberately unguarded: the guard files are exactly what a half-finished
rem  delete takes first, and this is the folder the user just named to
rem  install into, which is about to be written to either way.
if not exist "%INSTALL_DIR%\python\python.exe" goto :folder_clear
rmdir /s /q "%INSTALL_DIR%" 2>nul
if not exist "%INSTALL_DIR%\python\python.exe" goto :folder_clear

rem  Still there, so something really is holding it. Ask Windows WHICH -
rem  the leftover folder alone is not evidence that the app is open, and a
rem  message that is only sometimes true is what sent the user in circles.
tasklist /FI "IMAGENAME eq pythonw.exe" | find /I "pythonw.exe" >nul
if errorlevel 1 goto :folder_stuck
echo.
echo   JLBC Search is still open. Close it, then run this installer again.
echo.
pause
exit /b 1

:folder_stuck
echo.
echo   Couldn't clear the old program folder:
echo     %INSTALL_DIR%
echo   Delete it, then run this installer again.
echo.
pause
exit /b 1

:folder_clear
mkdir "%INSTALL_DIR%" 2>nul
echo   Extracting into the install folder (36,000 files; please wait)...
rem  tar.exe ships with Windows 10 1803+; bsdtar handles the zip fine.
rem  Extract DIRECTLY into the install folder (no temp dir + xcopy pass) -
rem  the old two-step wrote every file twice, doubling the time Windows
rem  Defender spends scanning the tree. `--strip-components=1` drops the
rem  zip's top-level `JLBC-Search-<version>/` so the app lands at the root
rem  of the install folder.
tar -xf "%ZIP%" -C "%INSTALL_DIR%" --strip-components=1
if errorlevel 1 (
    echo   ERROR: extraction failed. Copy the zip to your Desktop and run this
    echo   script from there instead of off the USB drive.
    pause
    exit /b 1
)

rem --- sanity: refuse to configure a bundle that did not unzip completely ----
if not exist "%INSTALL_DIR%\python\pythonw.exe"      goto :incomplete
if not exist "%INSTALL_DIR%\launcher.pyw"            goto :incomplete
if not exist "%INSTALL_DIR%\webapp\dist\index.html"  goto :incomplete
if not exist "%INSTALL_DIR%\VERSION"                 goto :incomplete
echo   Extracted OK.
echo.

rem --- record the shared data folder ------------------------------------------
if not defined DATA_DIR goto :skip_data
"%INSTALL_DIR%\python\python.exe" -m app.machine_config --set-data-dir "%DATA_DIR%"
if errorlevel 1 (
    echo   WARNING: could not record the shared folder. You can set it from
    echo            inside the app the first time you run it.
) else (
    echo   Recorded shared data folder: %DATA_DIR%
)
:skip_data

rem --- ingest default: recorded only if this PC has never chosen ---------------
"%INSTALL_DIR%\python\python.exe" -m app.machine_config --default-ingest-enabled false >nul 2>&1

rem --- shortcuts ---------------------------------------------------------------
set "SM_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
call :mkshortcut "%SM_DIR%\JLBC Search.lnk"
call :mkshortcut "%USERPROFILE%\Desktop\JLBC Search.lnk"

echo.
echo   ============================================================
echo    Setup complete.
echo   ============================================================
echo.
echo    Start it from:  the Start Menu, or the JLBC Search icon on
echo                    your Desktop.
if defined DATA_DIR echo    Data folder:    %DATA_DIR%
echo    Log files:      %ROOT_DIR%\logs
echo.
echo    If it will not start, send the newest file in that logs
echo    folder to whoever supports the app.
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
  "$s.Description='JLBC Search';" ^
  "$s.Save()" >nul 2>&1
if errorlevel 1 (
    echo   WARNING: could not create the shortcut at %~1
) else (
    echo   Created shortcut: %~1
)
exit /b 0

:incomplete
echo.
echo   The install didn't finish. Run this installer again.
echo.
pause
exit /b 1
