@echo off
setlocal
cd /d "%~dp0\.."

echo Ban muon chay den Agent may? (Nhap 1, 2, 3 hoac 4):
set /p AGENT_NUM=^> 

if "%AGENT_NUM%"=="1" set STOP_AFTER=agent1
if "%AGENT_NUM%"=="2" set STOP_AFTER=agent2
if "%AGENT_NUM%"=="3" set STOP_AFTER=agent3
if "%AGENT_NUM%"=="4" set STOP_AFTER=agent4

if "%STOP_AFTER%"=="" (
  echo Lua chon khong hop le. Hay nhap 1, 2, 3 hoac 4.
  pause
  exit /b 1
)

python debug_runners\run_partial.py "Bộ cộng ALU 8-bit" --stop-after %STOP_AFTER%
set EXIT_CODE=%ERRORLEVEL%
pause
exit /b %EXIT_CODE%