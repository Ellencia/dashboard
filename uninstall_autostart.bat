@echo off
chcp 65001 >nul
rem 시작프로그램 자동 실행 등록 해제
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Join-Path ([Environment]::GetFolderPath('Startup')) 'ProjectDashboard.lnk'; if(Test-Path $p){Remove-Item $p; Write-Host '[완료] 자동 실행 등록 해제됨.'}else{Write-Host '[안내] 등록된 자동 실행 항목이 없음.'}"
echo.
pause
