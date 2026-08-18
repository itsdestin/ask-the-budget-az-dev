@echo off
setlocal EnableDelayedExpansion
rem ============================================================================
rem  JLBC Search - ONE-CLICK installer (preview run)
rem
rem  This sits on the USB drive NEXT TO the bundle zip. Double-clicking it is
rem  the entire setup: it asks for two folders, extracts the program, fixes up
rem  the model path, creates the shortcuts, and records where the data lives.
rem  No admin rights, no Python, no Java, nothing else to install.
rem
rem  It reuses the same steps as install.cmd, but wraps them so the user never
rem  has to unzip by hand or go hunting for a second script.
rem ============================================================================

set "USB_DIR=%~dp0"
if "%USB_DIR:~-1%"=="\" set "USB_DIR=%USB_DIR:~0,-1%"

echo.
echo   ============================================================
echo    JLBC Search - preview setup
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
set "INSTALL_DEFAULT=%LOCALAPPDATA%\JLBC-Search"
echo   Where should the program live?
echo     Press Enter for the recommended spot:
echo       %INSTALL_DEFAULT%
echo     (or drag a different empty folder here, then Enter)
set "INSTALL_DIR="
set /p "INSTALL_DIR=  Install folder [%INSTALL_DEFAULT%]: "
if not defined INSTALL_DIR set "INSTALL_DIR=%INSTALL_DEFAULT%"
rem strip surrounding quotes if they dragged a folder in
set "INSTALL_DIR=%INSTALL_DIR:"=%"
echo   Installing to: %INSTALL_DIR%
echo.

rem --- Q2: where is the shared data (the corpus)? -----------------------------
echo   Where is the shared budget-data folder?
echo     This is the folder that has the "lancedb" folder inside it
echo     (the search index). On this preview it is usually the "Data"
echo     folder on the USB drive or on the office share.
echo     You can drag the folder here, then press Enter.
echo     Press Enter alone to decide later - the app asks on first run.
set "DATA_DIR="
set /p "DATA_DIR=  Shared data folder (Enter to skip): "
set "DATA_DIR=%DATA_DIR:"=%"
echo.

rem --- extract the bundle -----------------------------------------------------
echo   Extracting (this is a large program, please wait)...
if exist "%INSTALL_DIR%\python\pythonw.exe" (
    echo   A previous install is already here - refreshing it.
)
set "EXTRACT_TMP=%TEMP%\jlbc-search-extract-%RANDOM%%RANDOM%"
mkdir "%EXTRACT_TMP%" 2>nul
rem tar.exe ships with Windows 10 1803+; bsdtar handles the zip fine.
tar -xf "%ZIP%" -C "%EXTRACT_TMP%"
if errorlevel 1 (
    echo   ERROR: extraction failed. Try copying the zip to your Desktop and
    echo   running this script from there instead of off the USB drive.
    pause
    exit /b 1
)

rem The zip holds one top-level folder (JLBC-Search-<version>^). Move its
rem CONTENTS into the install folder, then clean up the temp dir.
for /d %%d in ("%EXTRACT_TMP%\JLBC-Search-*") do (
    mkdir "%INSTALL_DIR%" 2>nul
    xcopy "%%d\*" "%INSTALL_DIR%\" /E /I /Y /Q >nul
)
rd /s /q "%EXTRACT_TMP%" 2>nul

rem --- sanity: refuse to configure a bundle that did not unzip completely ----
if not exist "%INSTALL_DIR%\python\pythonw.exe"      goto :incomplete
if not exist "%INSTALL_DIR%\launcher.pyw"            goto :incomplete
if not exist "%INSTALL_DIR%\webapp\dist\index.html"  goto :incomplete
if not exist "%INSTALL_DIR%\models\mineru.json"      goto :incomplete
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

rem --- this computer does NOT process uploads by default ----------------------
rem  (same default as install.cmd; one designated machine turns it on in-app)
"%INSTALL_DIR%\python\python.exe" -m app.machine_config --set-ingest-enabled false >nul 2>&1

rem --- make MinerU's model path absolute --------------------------------------
"%INSTALL_DIR%\python\python.exe" -c "import json,sys,pathlib; p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text()); d['models-dir']['pipeline']=str(pathlib.Path(sys.argv[2])/'models'/'mineru'); p.write_text(json.dumps(d,indent=2))" "%INSTALL_DIR%\models\mineru.json" "%INSTALL_DIR%" 2>nul

rem --- shortcuts --------------------------------------------------------------
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
echo    Log files:      %LOCALAPPDATA%\JLBC-Search\logs
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
echo   This install is missing files that should have been in the zip.
echo   The most likely cause is that the zip did not finish extracting.
echo   Delete the folder %INSTALL_DIR%, then run this script again.
echo.
pause
exit /b 1
