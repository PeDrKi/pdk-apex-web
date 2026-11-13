#!/usr/bin/env bash
# Build frontend rồi chạy 1 server duy nhất (backend phục vụ luôn giao diện) ở cổng ${PORT:-8000}.
set -euo pipefail
cd "$(dirname "$0")"
[ -d backend/.venv ] || python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)
cd backend
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers "${WEB_CONCURRENCY:-2}" --proxy-headers
