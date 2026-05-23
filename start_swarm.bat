@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

echo ============================================
echo Semiconductor Swarm AI - Interactive Startup
echo ============================================
echo.

set /p REQ=Project Requirements: 
set /p PROJECT=Project Name ^(RTL-safe, blank = auto^): 
set /p OUT=Output Directory Path: 

if "%REQ%"=="" (
  echo ERROR: Project Requirements is required.
  exit /b 1
)

if "%OUT%"=="" set OUT=outputs\swarm_out
if "%PROJECT%"=="" set PROJECT=auto
set THREAD=%PROJECT%:%OUT%

echo.
echo [System] Dang khoi dong Agent 1 Architect...
python main.py "%REQ%" --project-name "%PROJECT%" --output-dir "%OUT%" --output-policy merge --checkpoint-db ".swarm\swarm_checkpoints.sqlite" --thread-id "%THREAD%"
if errorlevel 1 exit /b %errorlevel%

:PLAN_REVIEW
echo.
set /p CHANGE=Sep co muon thay doi gi nua khong? (Go ok de duyet): 
if "%CHANGE%"=="" set CHANGE=ok

if /i "%CHANGE%"=="ok" (
  echo [Approved] Xac nhan Plan. Bat dau chuyen giao cho Agent 2 ^(RTL Designer^)...
) else (
  echo [System] Dang goi lai Agent 1 de cap nhat Plan theo yeu cau: %CHANGE%...
)

python main.py --resume --resume-phase plan --notes "%CHANGE%" --project-name "%PROJECT%" --output-dir "%OUT%" --output-policy merge --checkpoint-db ".swarm\swarm_checkpoints.sqlite" --thread-id "%THREAD%"
if errorlevel 1 exit /b %errorlevel%

if /i not "%CHANGE%"=="ok" goto PLAN_REVIEW

:CODE_REVIEW
echo.
set /p RTL_OK=Sep da review RTL/Formal chua? (ok/reject): 
if "%RTL_OK%"=="" set RTL_OK=ok
if /i "%RTL_OK%"=="reject" (
  echo [Rejected] Dung workflow theo quyet dinh review.
  python main.py --reject --resume-phase code --project-name "%PROJECT%" --output-dir "%OUT%" --output-policy merge --checkpoint-db ".swarm\swarm_checkpoints.sqlite" --thread-id "%THREAD%"
  exit /b %errorlevel%
)

echo [Approved] RTL/Formal da duoc duyet. Bat dau DV/Physical...
python main.py --resume --resume-phase code --notes ok --project-name "%PROJECT%" --output-dir "%OUT%" --output-policy merge --checkpoint-db ".swarm\swarm_checkpoints.sqlite" --thread-id "%THREAD%"
if errorlevel 1 exit /b %errorlevel%

echo.
echo Done. Output: %OUT%
echo Status log: %OUT%\status.log
pause