@echo off
rem 프로젝트 대시보드 실행 (콘솔 창 없이 조용히)
rem PySide6 가 설치된 PPS venv 의 pythonw 를 절대경로로 사용
cd /d "%~dp0"
start "" "C:\Programming_STC\PPS\pps_venv\Scripts\pythonw.exe" main.py
