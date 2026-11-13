@echo off
REM Buoc 4: dat TRUSTED_ORIGINS tren Render, bien SITE_URL tren GitHub, kiem tra cuoi
REM Logic nam trong deploy\deploy.ps1. Xem huong dan: DEPLOY.md
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" -Step connect
pause
