@echo off
setlocal
cd /d "%~dp0"
call "%~dp0studio\run_studio.bat"
exit /b %errorlevel%
