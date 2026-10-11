@echo off
chcp 65001 >nul
title douyin-scout 本地助手
cd /d "%~dp0"

echo.
echo ============================================================
echo   douyin-scout 本地助手
echo ============================================================
echo.

REM 找 Python。优先用 py 启动器，其次 python。
where py >nul 2>&1
if %errorlevel%==0 (
    set PY=py -3
    goto :found
)
where python >nul 2>&1
if %errorlevel%==0 (
    set PY=python
    goto :found
)

echo   没有找到 Python。
echo.
echo   这个助手需要 Python 才能运行。请先安装：
echo     https://www.python.org/downloads/
echo.
echo   安装时记得勾选 "Add Python to PATH"。
echo.
pause
exit /b 1

:found
echo   使用 %PY%
echo.

REM 检查 playwright
%PY% -c "import playwright" >nul 2>&1
if not %errorlevel%==0 (
    echo   首次运行，正在安装依赖（约 1-2 分钟）...
    echo.
    %PY% -m pip install --quiet playwright -i https://pypi.tuna.tsinghua.edu.cn/simple
    if not %errorlevel%==0 (
        echo.
        echo   依赖安装失败。请检查网络后重试。
        pause
        exit /b 1
    )
    echo   正在下载浏览器内核（约 150MB，可能会慢）...
    %PY% -m playwright install chromium
)

echo   启动助手...
echo.
%PY% agent.py

echo.
echo   助手已停止。
pause
