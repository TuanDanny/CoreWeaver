@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0\.."

set BACKEND_PORT=8000
set FRONTEND_PORT=5173
set PYTHON_EXE=.venv_dv\Scripts\python.exe
set PYTHONPATH=%CD%\src;%PYTHONPATH%

if exist "%PYTHON_EXE%" goto PYTHON_READY

where python >nul 2>nul
if errorlevel 1 (
  echo Missing .venv_dv\Scripts\python.exe and python is not available on PATH
  exit /b 1
)
set PYTHON_EXE=python

:PYTHON_READY

call :CHECK_PORTS
if errorlevel 1 exit /b 1

echo Installing backend requirements...
"%PYTHON_EXE%" -m pip install -r studio\backend\requirements.txt
if errorlevel 1 exit /b 1

echo Installing frontend dependencies...
pushd studio\frontend
if not exist node_modules npm install
if errorlevel 1 exit /b 1
popd

echo Starting SWARM AI STUDIO backend...
start "SWARM Studio Backend" /D "%CD%" "%PYTHON_EXE%" -m uvicorn studio.backend.server:app --host 127.0.0.1 --port %BACKEND_PORT%

echo Starting SWARM AI STUDIO frontend...
start "SWARM Studio Frontend" /D "%CD%\studio\frontend" npm run dev

echo Open http://127.0.0.1:%FRONTEND_PORT%
exit /b 0

:CHECK_PORTS
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\studio\scripts\stop_stale_studio_ports.ps1" -Root "%CD%" -PortsCsv "%BACKEND_PORT%,%FRONTEND_PORT%"
exit /b %errorlevel%
