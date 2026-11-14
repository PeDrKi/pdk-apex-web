@echo off
REM Bat/tat: giu Render khong ngu va giu Supabase khong bi tam dung (chay bang GitHub Actions)
REM Logic nam trong deploy\giu-thuc.ps1. Dung: giu-thuc.bat [status|render-on|render-off|supabase-on|supabase-off]
chcp 65001 >nul
if "%~1"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\giu-thuc.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\giu-thuc.ps1" -Action %1
)
pause
