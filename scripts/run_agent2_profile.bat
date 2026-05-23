@echo off
setlocal
if "%~1"=="" (
  echo Usage: scripts\run_agent2_profile.bat demo^|dev^|strict^|nightly
  exit /b 2
)
python scripts\run_agent2_profile.py %1