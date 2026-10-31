@echo off
chcp 65001 >nul
title WeChat Antigravity Sidecar

echo ========================================================
echo   WeChat Antigravity Sidecar (手动按需启动模式)
echo   合盖/休眠自动彻底退出，开盖不自启
echo ========================================================
echo.

set SCRIPT_DIR=%~dp0
set VENV_BIN=%SCRIPT_DIR%.venv\Scripts

:: Ensure agy is in PATH for this session
if exist "%LOCALAPPDATA%\agy\bin\agy.exe" (
    set "PATH=%LOCALAPPDATA%\agy\bin;%PATH%"
)

if exist "%VENV_BIN%\wechat-agy-sidecar.exe" (
    echo [启动] 正在通过虚拟环境启动 Sidecar...
    "%VENV_BIN%\wechat-agy-sidecar.exe" %*
) else (
    echo [提示] 未找到 .venv 虚拟环境，尝试直接使用系统命令...
    wechat-agy-sidecar %*
)

echo.
echo [退出] Sidecar 已停止运行。
pause
