@echo off
setlocal EnableDelayedExpansion
rem ============================================================================
rem  JLBC Search - one-click diagnostic + repair
rem  Run from the USB (or RUN-DIAGNOSTIC.cmd at the USB root). It:
rem    1. copies the app's newest server log into JLBCSearch\diagnostics\,
rem    2. compares the network copy of the corpus against the USB seed,
rem    3. reports missing / half-copied files in plain terms,
rem    4. offers to repair the network copy from the USB, then re-checks.
rem ============================================================================

echo.
echo   ============================================================
echo    JLBC Search - check why the app won't start
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
    echo   The script cannot run the app's own open-check without it, and the
    echo   log cannot be copied. If the app IS installed it lives at:
    echo     %LOCALAPPDATA%\JLBC-Search\python\pythonw.exe
    echo   If that folder does not exist, run Install-JLBC-Search.cmd first.
    echo.
)

rem --- 2. run the diagnostic with the app's own python ----------------------
set "PROBE=%~dp0diag.pyw"
if not exist "%PROBE%" if defined INSTALL_DIR (
    if exist "%INSTALL_DIR%\diagnostics\diag.pyw" set "PROBE=%INSTALL_DIR%\diagnostics\diag.pyw"
)
if not exist "%PROBE%" (
    echo   ERROR: diag.pyw not found next to this script.
    echo   Copy the whole JLBCSearch folder from the USB drive.
    echo.
    pause
    exit /b 1
)

if defined INSTALL_DIR (
    set "PY=%INSTALL_DIR%\python\python.exe"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo   ERROR: no Python found. Install the app first, then run this again.
        echo.
        pause
        exit /b 1
    )
    set "PY=python"
)

echo   Running the diagnostic (copies the log, compares the corpus)...
echo.
"%PY%" "%PROBE%" %*
set "RC=%ERRORLEVEL%"
echo.
echo   Done. Files saved in the "diagnostics" folder next to this script.
echo   If the app still will not start, send that folder to whoever
echo   supports this app.
echo.
pause
exit /b %RC%