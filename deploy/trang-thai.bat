@echo off
REM Xem dia chi da deploy va kiem tra web con chay khong
REM Logic nam trong deploy\deploy.ps1. Xem huong dan: DEPLOY.md
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" -Step status
pause
