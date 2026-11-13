@echo off
REM Buoc 2: tao Supabase va dich vu Render, cho backend chay
REM Logic nam trong deploy\deploy.ps1. Xem huong dan: DEPLOY.md
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" -Step render
pause
