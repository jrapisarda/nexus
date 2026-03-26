@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

where uv >nul 2>nul
if errorlevel 1 (
    echo [NEXUS] uv was not found on PATH.
    echo Install uv or open a shell where uv is available, then run this script again.
    exit /b 1
)

echo [NEXUS] Starting engine and API from %ROOT%

start "NEXUS Engine" cmd /k "cd /d ""%ROOT%"" && uv run nexus-engine"
start "NEXUS API" cmd /k "cd /d ""%ROOT%"" && uv run nexus-api"

echo [NEXUS] Engine and API launched in separate windows.
echo [NEXUS] Dashboard: http://localhost:8000/dashboard

endlocal
