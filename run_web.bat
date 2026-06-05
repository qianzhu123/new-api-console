@echo off
setlocal
cd /d %~dp0

where python >nul 2>nul
if %errorlevel% neq 0 (
  echo Python is not found in PATH.
  pause
  exit /b 1
)

echo Stopping the previous service on port 5050 ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$attempt = 0; while ($attempt -lt 20) { $processIds = @(Get-NetTCPConnection -LocalPort 5050 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique); if ($processIds.Count -eq 0) { exit 0 }; foreach ($processId in $processIds) { Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Milliseconds 250; $attempt++ }; Write-Error 'Port 5050 is still in use after stopping previous services.'; exit 1"
if %errorlevel% neq 0 (
  pause
  exit /b 1
)

echo Starting new-api Local Web Console on http://127.0.0.1:5050 ...
start "" http://127.0.0.1:5050
python app.py

pause

