@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal
set PYTHONIOENCODING=utf-8

echo ============================================================
echo   打包「桌面隐翅虫」为单个 exe（同事不用装 Python）
echo ============================================================
echo.

python build_exe.py
if errorlevel 1 (
    echo.
    echo [!!] 打包失败。常见原因：
    echo      - python 不在 PATH（重装 Python 时勾 Add python.exe to PATH）
    echo      - 缺 PyQt5：pip install PyQt5 Pillow websockets
    echo.
    pause
    exit /b 1
)

echo.
pause
