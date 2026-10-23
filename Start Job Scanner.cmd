@echo off
cd /d "%~dp0"
if not exist ".venv-scanner\Scripts\python.exe" (
 echo Run Setup Job Scanner.cmd first.
 pause
 exit /b 1
)
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0.local-tools\pw-browsers"
".venv-scanner\Scripts\python.exe" app.py --scanner-experiment --port 8003 --open-browser
pause
