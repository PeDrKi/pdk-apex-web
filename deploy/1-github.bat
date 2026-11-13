@echo off
REM Buoc 1: tao repo GitHub va day ma nguon len
REM Logic nam trong deploy\deploy.ps1. Xem huong dan: DEPLOY.md
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" -Step github
pause
