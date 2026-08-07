@echo off
REM =====================================================================
REM SoyMutDB Windows Installer Build Script (6 steps)
REM =====================================================================
REM Requires:
REM   - Conda (Miniconda or Anaconda)
REM   - Python 3.14 (for API) and 3.13 (for Worker)
REM   - PyInstaller
REM   - Node.js 24 + pnpm 10
REM =====================================================================

setlocal enabledelayedexpansion

set "PROJECT_ROOT=%~dp0..\.."
set "BUILD_DIR=%PROJECT_ROOT%\build\windows"
set "DIST_DIR=%PROJECT_ROOT%\dist\windows"

echo ========================================
echo   SoyMutDB Windows Package Builder
echo ========================================
echo.

REM Check if conda is available
where conda >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Conda not found. Please install Miniconda or Anaconda first.
    echo Download: https://docs.conda.io/en/latest/miniconda.html
    exit /b 1
)

echo [1/6] Creating build directories...
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"

echo.
echo [2/6] Building API service with PyInstaller...
call conda activate soymutdb-api
if errorlevel 1 (
    echo [WARN] soymutdb-api conda environment not found, creating it...
    call conda env create -f "%PROJECT_ROOT%\deploy\conda\environment-api.yml"
    call conda activate soymutdb-api
)

pip install pyinstaller >nul
cd /d "%PROJECT_ROOT%\deploy\windows"
pyinstaller --clean --workpath "%BUILD_DIR%\api" --distpath "%DIST_DIR%" api.spec
if errorlevel 1 (
    echo [ERROR] API build failed!
    exit /b 1
)
echo API build complete.

echo.
echo [3/6] Building Worker service with PyInstaller...
call conda activate soymutdb-worker
if errorlevel 1 (
    echo [WARN] soymutdb-worker conda environment not found, creating it...
    call conda env create -f "%PROJECT_ROOT%\deploy\conda\environment-worker.yml"
    call conda activate soymutdb-worker
)

pip install pyinstaller >nul
pyinstaller --clean --workpath "%BUILD_DIR%\worker" --distpath "%DIST_DIR%" worker.spec
if errorlevel 1 (
    echo [ERROR] Worker build failed!
    exit /b 1
)
echo Worker build complete.

echo.
echo [4/6] Building frontend apps...
cd /d "%PROJECT_ROOT%"

where pnpm >nul 2>nul
if %errorlevel% equ 0 (
    call pnpm install
    call pnpm --filter @soymutdb/web build
    call pnpm --filter @soymutdb/admin build
    call pnpm --filter @soymutdb/jbrowse build
) else (
    echo [WARN] pnpm not found, skipping frontend build.
    echo Install Node.js 24 and pnpm 10 to build frontend.
)

REM Copy frontend builds to dist
if exist "%PROJECT_ROOT%\apps\web\dist" (
    xcopy /E /I /Y "%PROJECT_ROOT%\apps\web\dist" "%DIST_DIR%\web"
)
if exist "%PROJECT_ROOT%\apps\admin\dist" (
    xcopy /E /I /Y "%PROJECT_ROOT%\apps\admin\dist" "%DIST_DIR%\admin"
)
if exist "%PROJECT_ROOT%\apps\jbrowse\dist" (
    xcopy /E /I /Y "%PROJECT_ROOT%\apps\jbrowse\dist" "%DIST_DIR%\jbrowse"
)

echo.
echo [5/6] Copying configuration and service files...
copy "%PROJECT_ROOT%\.env.example" "%DIST_DIR%\.env.example"
copy "%PROJECT_ROOT%\deploy\windows\winservice_api.py" "%DIST_DIR%\soymutdb-api\"
copy "%PROJECT_ROOT%\deploy\windows\winservice_worker.py" "%DIST_DIR%\soymutdb-worker\"
copy "%PROJECT_ROOT%\deploy\windows\install.bat" "%DIST_DIR%\"
copy "%PROJECT_ROOT%\deploy\windows\uninstall.bat" "%DIST_DIR%\"
copy "%PROJECT_ROOT%\deploy\windows\start.bat" "%DIST_DIR%\"
copy "%PROJECT_ROOT%\deploy\windows\stop.bat" "%DIST_DIR%\"

REM Copy Nginx config
if exist "%PROJECT_ROOT%\infra\nginx" (
    xcopy /E /I /Y "%PROJECT_ROOT%\infra\nginx" "%DIST_DIR%\nginx"
)

echo.
echo [6/6] Creating version file...
echo SoyMutDB Windows Package > "%DIST_DIR%\VERSION.txt"
echo Version: 2.0.0 >> "%DIST_DIR%\VERSION.txt"
echo Built: %date% %time% >> "%DIST_DIR%\VERSION.txt"
echo. >> "%DIST_DIR%\VERSION.txt"
echo Components: >> "%DIST_DIR%\VERSION.txt"
echo   - API Service (FastAPI + Python 3.14) >> "%DIST_DIR%\VERSION.txt"
echo   - Worker Service (Celery + Python 3.13) >> "%DIST_DIR%\VERSION.txt"
echo   - Web Frontend (React + Vite) >> "%DIST_DIR%\VERSION.txt"
echo   - Admin Console (React + Vite) >> "%DIST_DIR%\VERSION.txt"
echo   - Genome Browser (JBrowse 2) >> "%DIST_DIR%\VERSION.txt"

echo.
echo ========================================
echo   Build Complete!
echo ========================================
echo.
echo Output directory: %DIST_DIR%
echo.
echo To install on target machine:
echo   1. Copy the entire directory to target
echo   2. Run install.bat as Administrator
echo   3. Configure .env file
echo   4. Run start.bat
echo.

endlocal
