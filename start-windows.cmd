@echo off
setlocal
cd /d "%~dp0"
py -3.14 -c "import sys" >nul 2>nul
if errorlevel 1 (
    python "%~dp0scripts\start.py" %*
) else (
    py -3.14 "%~dp0scripts\start.py" %*
)
set "workbench_exit=%errorlevel%"
if not "%workbench_exit%"=="0" (
    echo Startup failed. See the error above and docs\windows-deployment.md.
    pause
)
exit /b %workbench_exit%
