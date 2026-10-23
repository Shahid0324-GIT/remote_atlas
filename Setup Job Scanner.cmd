@echo off
cd /d "%~dp0"
if not exist ".venv-scanner\Scripts\python.exe" python -m venv .venv-scanner
if errorlevel 1 goto failed
".venv-scanner\Scripts\python.exe" -m pip install -r requirements-scanner.txt
if errorlevel 1 goto failed
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0.local-tools\pw-browsers"
".venv-scanner\Scripts\python.exe" -m playwright install chromium --only-shell
if errorlevel 1 goto failed
echo Setup complete. Open Start Job Scanner.cmd to try the experimental scanner.
pause
exit /b 0
:failed
echo Setup failed. Check the message above. You can still use public feeds without Playwright.
pause
exit /b 1
