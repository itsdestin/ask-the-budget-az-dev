@echo off
rem ============================================================================
rem  JLBC Search - one-click diagnostic (run from the USB drive root)
rem  Thin wrapper: finds the JLBCSearch folder on this drive, then hands off
rem  to its diag.cmd. Kept deliberately tiny so nothing here can flash-fail.
rem ============================================================================
setlocal EnableDelayedExpansion

set "J="
if exist "%~dp0JLBCSearch\diag.cmd" set "J=%~dp0JLBCSearch\diag.cmd"
if not defined J if exist "%CD%\JLBCSearch\diag.cmd" set "J=%CD%\JLBCSearch\diag.cmd"
if not defined J (
    for %%d in (C D E F G H I J) do if exist "%%d:\JLBCSearch\diag.cmd" set "J=%%d:\JLBCSearch\diag.cmd"
)
if not defined J (
    echo   Could not find the JLBCSearch folder on this drive.
    echo   Run this from the USB drive next to the JLBCSearch folder.
    echo.
    pause
    exit /b 1
)

call "%J%" %*
exit /b %ERRORLEVEL%