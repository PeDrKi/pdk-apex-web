@echo off
REM Chạy backend (cổng 8000) và frontend dev (cổng 5173) trong 2 cửa sổ riêng.
cd /d "%~dp0"
if not exist backend\.venv (
  python -m venv backend\.venv
  backend\.venv\Scripts\pip install -r backend\requirements-dev.txt
)
if not exist frontend\node_modules (
  pushd frontend & call npm install & popd
)
start "APEX backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\uvicorn app.main:app --reload --port 8000"
start "APEX frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
timeout /t 4 >nul
start http://localhost:5173
