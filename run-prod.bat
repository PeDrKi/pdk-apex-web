@echo off
REM Build frontend rồi chạy 1 server duy nhất (backend phục vụ luôn giao diện) ở cổng 8000.
cd /d "%~dp0"
if not exist backend\.venv python -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements.txt
pushd frontend & call npm ci & call npm run build & popd
cd backend
.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
