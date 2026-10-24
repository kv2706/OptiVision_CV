@echo off
title OptiVision CV
cd /d "%~dp0"
echo ========================================
echo        OptiVision CV - Startup
echo ========================================
where py >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11+ from https://www.python.org/downloads/
  echo During installation, check "Add Python to PATH".
  pause
  exit /b 1
)
if not exist .venv (
  echo Creating virtual environment...
  py -m venv .venv
)
call .venv\Scripts\activate.bat
echo Installing required packages...
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Starting website at http://127.0.0.1:5000
echo Demo admin login: admin@optivision.local
echo Demo admin password: Admin@12345
echo Press Ctrl+C to stop the server.
python app.py
pause
