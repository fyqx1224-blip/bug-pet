@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal
set PYTHONIOENCODING=utf-8

echo ============================================================
echo   打包「壁纸联机包」：exe + 房间壁纸 + 一键应用 + 说明书
echo ============================================================
echo.

python build_full_pkg.py
if errorlevel 1 (
    echo.
    echo [!!] 打包失败。先确认 build_exe.bat 能单独跑通。
    echo.
    pause
    exit /b 1
)

echo.
pause
