@echo off
setlocal
cd /d %~dp0

where python >nul 2>nul
if %errorlevel% neq 0 (
  echo Python is not found in PATH.
  pause
  exit /b 1
)

echo Starting new-api Local Web Console on http://127.0.0.1:5050 ...
start "" http://127.0.0.1:5050
python app.py

pause

