@echo off
setlocal

cd /d "%~dp0\.."

if exist ".venv_dv\Scripts\python.exe" (
  set "PY=.venv_dv\Scripts\python.exe"
) else (
  set "PY=python"
)

echo [SWARM AI STUDIO] Installing app dependencies...
"%PY%" -m pip install -r app\requirements.txt
if errorlevel 1 (
  echo [SWARM AI STUDIO] Dependency install failed.
  exit /b 1
)

echo [SWARM AI STUDIO] Starting UI...
"%PY%" app\main_window.py
