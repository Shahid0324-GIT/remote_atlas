@echo off
cd /d "%~dp0"
echo Starting Remote Atlas. Open http://127.0.0.1:8000 in your browser.
python app.py --open-browser
pause
