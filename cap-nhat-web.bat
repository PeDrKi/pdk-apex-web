@echo off
REM Dua thay doi moi len web: commit + push (Render tu build) + deploy lai Vercel
REM Logic nam trong deploy\deploy.ps1. Xem huong dan: DEPLOY.md
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\deploy.ps1" -Step update
pause
