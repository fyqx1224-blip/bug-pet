@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal
REM 把下面的占位地址换成房主发给你的地址（形如 ws://100.x.y.z:8765）
set BUG_RELAY_URL=ws://100.64.0.1:8765
set PYTHONIOENCODING=utf-8
python src/room_overlay.py
endlocal
