@echo off
REM =====================================================================
REM SoyMutDB Start Script
REM =====================================================================
REM Starts all SoyMutDB services.
REM =====================================================================

setlocal enabledelayedexpansion

echo ========================================
echo   Starting SoyMutDB
echo ========================================
echo.

REM Check admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Not running as Administrator. Some operations may fail.
    echo.
)

echo [1/3] Starting API service...
net start SoyMutDBAPI
if errorlevel 1 (
    echo [ERROR] Failed to start API service!
    echo Check logs in logs\ directory.
)

echo.
echo [2/3] Starting Worker service...
net start SoyMutDBWorker
if errorlevel 1 (
    echo [WARN] Failed to start Worker service.
    echo This may be normal if no worker is configured.
)

echo.
echo [3/3] Starting Nginx...
net start SoyMutDBNginx 2>nul
if errorlevel 1 (
    REM Try running nginx directly if not a service
    if exist "nginx\nginx.exe" (
        cd nginx
        start /B nginx.exe
        cd ..
        echo Nginx started as background process.
    ) else (
        echo [WARN] Nginx not found.
    )
)

echo.
echo ========================================
echo   SoyMutDB Started
echo ========================================
echo.
echo Web interface: http://localhost/
echo API liveness:  http://localhost/api/v1/health/live
echo API readiness: http://localhost/api/v1/health/ready
echo Admin console: http://localhost/admin/
echo Genome browser: http://localhost/browser/
echo.
echo Run stop.bat to stop all services.
echo.

endlocal
