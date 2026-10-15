@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

REM 自动探测本机 Tailscale IP（探测不到才用下面的兜底值）。
REM 下面是占位符，不是真实地址——仓库是公开的，别把真 IP 写进来。
set HOST_IP=100.64.0.1
set TS_EXE="C:\Program Files\Tailscale\tailscale.exe"
if exist %TS_EXE% (
    for /f "delims=" %%I in ('%TS_EXE% ip -4 2^>nul') do set HOST_IP=%%I
) else (
    for /f "delims=" %%I in ('tailscale ip -4 2^>nul') do set HOST_IP=%%I
)
echo [host] Tailscale IP = %HOST_IP%
echo [host] guest should connect to ws://%HOST_IP%:8765

set BUG_RELAY_URL=ws://%HOST_IP%:8765
set PYTHONIOENCODING=utf-8

REM 先启 relay（优先用打包好的 exe，无需 Python），再启本机宠物 overlay
if exist "%~dp0dist_relay\隐翅虫中继.exe" (
    start /min cmd /c ""%~dp0dist_relay\隐翅虫中继.exe""
) else (
    start /min cmd /c "python src/net_relay.py"
)
timeout /t 1 /nobreak >nul

REM 宠物端：优先托管 venv Python（源码运行），没有则用打包好的 exe（无需 Python）
set "PY=%USERPROFILE%\.workbuddy-ai\binaries\python\envs\default\Scripts\python.exe"
if exist "%PY%" (
    start "BugPet" "%PY%" "%~dp0src\room_overlay.py"
) else if exist "%~dp0dist\桌面隐翅虫.exe" (
    start "BugPet" "%~dp0dist\桌面隐翅虫.exe"
) else (
    echo [错误] 找不到 Python 环境，也没有 dist\桌面隐翅虫.exe
    echo 请先运行 build_full_pkg.bat 打包，或安装 Python + PyQt5
    pause
)
endlocal
