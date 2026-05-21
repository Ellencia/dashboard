@echo off
chcp 65001 >nul
rem 윈도우 시작 시 대시보드가 자동 실행되도록 시작프로그램에 바로가기 등록
cd /d "%~dp0"
set "DASHDIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$q=[char]34; $bs=[char]92; $dir=$env:DASHDIR.TrimEnd($bs); $ws=New-Object -ComObject WScript.Shell; $startup=[Environment]::GetFolderPath('Startup'); $sc=$ws.CreateShortcut((Join-Path $startup 'ProjectDashboard.lnk')); $sc.TargetPath=(Get-Command pythonw).Source; $sc.Arguments=($q+(Join-Path $dir 'main.py')+$q); $sc.WorkingDirectory=$dir; $sc.Save(); Write-Host ('등록 위치: '+(Join-Path $startup 'ProjectDashboard.lnk'))"
echo.
echo [완료] 다음 윈도우 부팅부터 대시보드가 자동 실행됨.
pause
