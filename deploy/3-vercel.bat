@echo off
REM Buoc 3: deploy giao dien len Vercel
REM Logic nam trong deploy\deploy.ps1. Xem huong dan: DEPLOY.md
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" -Step vercel
pause
