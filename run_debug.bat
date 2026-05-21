@echo off
chcp 65001 >nul
rem 디버그 실행: 오류 메시지를 콘솔에 그대로 보여줌
cd /d "%~dp0"
python main.py
echo.
echo --- 위젯 창이 안 떴거나 오류가 났다면 위 메시지를 확인 ---
pause
