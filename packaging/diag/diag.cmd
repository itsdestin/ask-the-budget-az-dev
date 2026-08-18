@echo off
setlocal EnableDelayedExpansion
rem ============================================================================
rem  JLBC Search - one-click diagnostic
rem  Run this from the USB (or copy it next to the app and run it there).
rem  It checks why the app cannot start, writes a report to the USB's
rem  JLBCSearch\diagnostics\ folder, and prints the next step.
rem ============================================================================

echo.
echo   ============================================================
echo    JLBC Search - run a diagnostic on this PC
echo   ============================================================
echo.

rem --- 1. find the app install ---------------------------------------------
set "INSTALL_DIR="
if exist "%LOCALAPPDATA%\JLBC-Search\python\pythonw.exe" (
    set "INSTALL_DIR=%LOCALAPPDATA%\JLBC-Search"
)
if not defined INSTALL_DIR for %%d in ("%~dp0..") do if exist "%%~d\python\pythonw.exe" set "INSTALL_DIR=%%~d"
if not defined INSTALL_DIR for /d %%d in ("C:\Users\*") do if exist "%%d\AppData\Local\JLBC-Search\python\pythonw.exe" set "INSTALL_DIR=%%d\AppData\Local\JLBC-Search"

if not defined INSTALL_DIR (
    echo   Could not find the JLBC Search install (python\pythonw.exe).
    echo   Steps:
    echo     - Install it first (run Install-JLBC-Search.cmd),
    echo     - or copy this script into the same folder as launcher.pyw.
    echo.
    pause
    exit /b 1
)
echo   Install found: %INSTALL_DIR%
echo.

rem --- 2. run the probe with the app's own python --------------------------
set "PROBE=%~dp0diag.pyw"
if not exist "%PROBE%" set "PROBE=%INSTALL_DIR%\diagnostics\diag.pyw"
if not exist "%PROBE%" (
    echo   ERROR: diag.pyw not found next to this script or in the install.
    echo   Copy diag.pyw from the JLBCSearch folder.
    echo.
    pause
    exit /b 1
)

echo   Running the diagnostic (takes a few seconds)...
echo.
"%INSTALL_DIR%\python\python.exe" "%PROBE%"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo   Done. The report is in the "diagnostics" folder.
    echo   Send the files in that folder to whoever maintains this app.
) else (
    echo   The diagnostic did not finish cleanly (exit %RC%).
    echo   Send the "diagnostics" folder to whoever maintains this app anyway.
)
echo.
pause
exit /b %RC%