@echo off
REM 桌面隐翅虫宠物启动器
setlocal

set "ROOT=%~dp0"
set "PY=%USERPROFILE%\.workbuddy-ai\binaries\python\envs\default\Scripts\python.exe"
set "APP=%ROOT%src\bug_pet.py"

if not exist "%PY%" (
    echo [错误] 找不到 Python 环境: %PY%
    echo 请先安装: pip install PyQt5 Pillow
    pause
    exit /b 1
)

if not exist "%APP%" (
    echo [错误] 找不到主程序: %APP%
    pause
    exit /b 1
)

start "BugPet" "%PY%" "%APP%"