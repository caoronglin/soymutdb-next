@echo off
REM =====================================================================
REM SoyMutDB Windows Uninstallation Script
REM =====================================================================
REM Run as Administrator!
REM =====================================================================

setlocal enabledelayedexpansion

echo ========================================
echo   SoyMutDB Uninstallation
echo ========================================
echo.
echo WARNING: This will remove SoyMutDB Windows Services.
echo          Your data files will NOT be deleted.
echo.
set /p CONFIRM="Are you sure you want to uninstall? (yes/no): "
if /i not "%CONFIRM%"=="yes" (
    echo Uninstallation cancelled.
    exit /b 0
)

echo.

REM Check admin privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] This script must be run as Administrator!
    pause
    exit /b 1
)

echo [1/4] Stopping services...
net stop SoyMutDBWorker 2>nul
net stop SoyMutDBAPI 2>nul
net stop SoyMutDBNginx 2>nul
echo Services stopped.

echo.
echo [2/4] Removing Worker service...
python soymutdb-worker\winservice_worker.py remove 2>nul
if errorlevel 1 (
    sc delete SoyMutDBWorker 2>nul
)
echo Worker service removed.

echo.
echo [3/4] Removing API service...
python soymutdb-api\winservice_api.py remove 2>nul
if errorlevel 1 (
    sc delete SoyMutDBAPI 2>nul
)
echo API service removed.

echo.
echo [4/4] Removing Nginx service...
where nssm >nul 2>nul
if %errorlevel% equ 0 (
    nssm remove SoyMutDBNginx confirm 2>nul
) else (
    sc delete SoyMutDBNginx 2>nul
)
echo Nginx service removed.

echo.
echo ========================================
echo   Uninstallation Complete
echo ========================================
echo.
echo Data and configuration files have been preserved.
echo To completely remove all data, manually delete the installation directory.
echo.
pause

endlocal
