@echo off
REM 2026-11-23: bare "python" hits the Microsoft Store stub; pin to tools uv venv.
REM Idempotent: if port 5050 is already listening, reuse it (no second instance).
setlocal
cd /d %~dp0

set "PY=D:\tools\Dev\Runtime\uvenvs\tools\Scripts\python.exe"
if not exist "%PY%" (
  echo Python venv not found: %PY%
  pause
  exit /b 1
)

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5050 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if %errorlevel% equ 0 (
  echo [info] qiandao already running on http://127.0.0.1:5050, reuse it.
  exit /b 0
)

echo Starting qiandao web console on http://127.0.0.1:5050 ...
REM 2026-11-08 user decision: launcher must not auto-open a browser
"%PY%" app.py
