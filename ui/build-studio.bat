@echo off
setlocal

cd /d "%~dp0"

echo ==========================================
echo  AI Task Runner - Workflow Studio Build
echo ==========================================
echo.

where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js was not found.
    echo Install Node.js LTS first, then run this file again.
    exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm was not found.
    echo Reinstall Node.js with npm enabled.
    exit /b 1
)

if not exist "studio-src\package.json" (
    echo [ERROR] ui\studio-src\package.json was not found.
    exit /b 1
)

pushd "studio-src"

if exist "package-lock.json" (
    echo [1/2] Installing dependencies with npm ci...
    call npm ci
) else (
    echo [1/2] Installing dependencies with npm install...
    call npm install
)

if errorlevel 1 (
    echo.
    echo [ERROR] npm dependency installation failed.
    popd
    exit /b 1
)

echo.
echo [2/2] Building Workflow Studio...
call npm run build

if errorlevel 1 (
    echo.
    echo [ERROR] Workflow Studio build failed.
    popd
    exit /b 1
)

popd

if not exist "static\workflow-studio-app\index.html" (
    echo.
    echo [ERROR] Build finished but static\workflow-studio-app\index.html was not created.
    exit /b 1
)

echo.
echo [OK] Workflow Studio build completed.
echo Output:
echo   %~dp0static\workflow-studio-app\
echo.

exit /b 0
