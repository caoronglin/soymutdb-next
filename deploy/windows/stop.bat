@echo off
REM =====================================================================
REM SoyMutDB Stop Script
REM =====================================================================
REM Stops all SoyMutDB services.
REM =====================================================================

setlocal enabledelayedexpansion

echo ========================================
echo   Stopping SoyMutDB
echo ========================================
echo.

echo [1/3] Stopping Worker service...
net stop SoyMutDBWorker 2>nul
if errorlevel 1 (
    echo [INFO] Worker service was not running.
)

echo.
echo [2/3] Stopping API service...
net stop SoyMutDBAPI 2>nul
if errorlevel 1 (
    echo [INFO] API service was not running.
)

echo.
echo [3/3] Stopping Nginx...
net stop SoyMutDBNginx 2>nul
if errorlevel 1 (
    REM Try taskkill if running as process
    taskkill /F /IM nginx.exe 2>nul
    if errorlevel 1 (
        echo [INFO] Nginx was not running.
    ) else (
        echo Nginx process stopped.
    )
)

echo.
echo ========================================
echo   All Services Stopped
echo ========================================
echo.

endlocal
