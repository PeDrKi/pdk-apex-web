@echo off
REM Deploy toan bo lan dau: GitHub -> Supabase + Render -> Vercel -> noi lai
REM Logic nam trong deploy\deploy.ps1. Xem huong dan: DEPLOY.md
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\deploy.ps1" -Step all
pause
