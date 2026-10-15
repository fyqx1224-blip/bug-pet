@echo off
REM Interactive Room Overlay launcher
setlocal
set "ROOT=%~dp0"
set "PY=%USERPROFILE%\.workbuddy-ai\binaries\python\envs\default\Scripts\python.exe"
set "APP=%ROOT%src\room_overlay.py"
if not exist "%PY%" ( echo [错误] 找不到 Python 环境: %PY% & pause & exit /b 1 )
if not exist "%APP%" ( echo [错误] 找不到主程序: %APP% & pause & exit /b 1 )
start "BugRoom" "%PY%" "%APP%"
