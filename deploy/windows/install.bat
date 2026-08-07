@echo off
REM =====================================================================
REM SoyMutDB Windows Installation Script (4 steps)
REM =====================================================================
REM Run as Administrator!
REM
REM This script:
REM   1. Installs API as Windows Service
REM   2. Installs Worker as Windows Service
REM   3. Sets up Nginx as Windows Service (using NSSM)
REM   4. Creates log and data directories
REM =====================================================================

setlocal enabledelayedexpansion

set "INSTALL_DIR=%~dp0"
cd /d "%INSTALL_DIR%"

echo ========================================
echo   SoyMutDB Installation
echo ========================================
echo.

REM Check admin privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] This script must be run as Administrator!
    echo Right-click and select "Run as administrator".
    pause
    exit /b 1
)

echo [INFO] Install directory: %INSTALL_DIR%
echo.

REM Check for .env file
if not exist ".env" (
    echo [INFO] .env file not found, creating from .env.example...
    copy ".env.example" ".env"
    echo.
    echo [WARN] Please edit .env file with your configuration before starting services.
    echo       Then re-run install.bat
    pause
    exit /b 0
)

echo [1/4] Installing SoyMutDB API Service...
if exist "soymutdb-api\winservice_api.py" (
    python "soymutdb-api\winservice_api.py" install
    if errorlevel 1 (
        echo [ERROR] Failed to install API service!
        pause
        exit /b 1
    )
    echo API service installed successfully.
) else (
    echo [WARN] winservice_api.py not found, skipping API service install.
)

echo.
echo [2/4] Installing SoyMutDB Worker Service...
if exist "soymutdb-worker\winservice_worker.py" (
    python "soymutdb-worker\winservice_worker.py" install
    if errorlevel 1 (
        echo [ERROR] Failed to install Worker service!
        pause
        exit /b 1
    )
    echo Worker service installed successfully.
) else (
    echo [WARN] winservice_worker.py not found, skipping Worker service install.
)

echo.
echo [3/4] Setting up Nginx...
if exist "nginx\nginx.exe" (
    REM Check for NSSM (Non-Sucking Service Manager)
    where nssm >nul 2>nul
    if %errorlevel% equ 0 (
        nssm install SoyMutDBNginx "%INSTALL_DIR%nginx\nginx.exe"
        nssm set SoyMutDBNginx AppDirectory "%INSTALL_DIR%nginx"
        nssm set SoyMutDBNginx DisplayName "SoyMutDB Nginx"
        nssm set SoyMutDBNginx Description "SoyMutDB web server and reverse proxy"
        nssm set SoyMutDBNginx AppStdout "%INSTALL_DIR%logs\nginx-stdout.log"
        nssm set SoyMutDBNginx AppStderr "%INSTALL_DIR%logs\nginx-stderr.log"
        nssm set SoyMutDBNginx AppRotateFiles 1
        nssm set SoyMutDBNginx AppRotateOnline 1
        nssm set SoyMutDBNginx AppRotateBytes 10485760
        echo Nginx service installed via NSSM.
    ) else (
        echo [WARN] NSSM not found. Nginx will run as a standalone process.
        echo Download NSSM from: https://nssm.cc/
    )
) else (
    echo [WARN] Nginx not found in nginx\ directory.
)

echo.
echo [4/4] Creating log and data directories...
if not exist "logs" mkdir logs
if not exist "data" mkdir data
if not exist "data\pgdata" mkdir data\pgdata
if not exist "data\chdata" mkdir data\chdata
if not exist "data\redis" mkdir data\redis
if not exist "data\minio" mkdir data\minio

echo.
echo ========================================
echo   Installation Complete!
echo ========================================
echo.
echo Services installed:
echo   - SoyMutDBAPI (port 8000)
echo   - SoyMutDBWorker
echo   - SoyMutDBNginx (port 80) [if NSSM available]
echo.
echo Next steps:
echo   1. Ensure PostgreSQL, ClickHouse, Redis are running
echo   2. Verify .env configuration
echo   3. Run database migrations:
echo      soymutdb-api\alembic upgrade head
echo   4. Start services: start.bat
echo.
echo To uninstall, run: uninstall.bat
echo.
pause

endlocal
