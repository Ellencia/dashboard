@echo off
chcp 65001 >nul
rem 윈도우 시작 시 대시보드가 자동 실행되도록 시작프로그램에 바로가기 등록
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_autostart.ps1"
echo.
pause
