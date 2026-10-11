@echo off
chcp 65001 >nul
cd /d "%~dp0\.."

echo.
echo ============================================================
echo   douyin-scout
echo ============================================================
echo.

REM 找 Python
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

echo   没有找到 Python 3.11 或更高版本。
echo.
echo   请先安装：https://www.python.org/downloads/
echo   安装时务必勾选 "Add python.exe to PATH"。
echo.
pause
exit /b 1

:found

REM 首次运行：建虚拟环境并装依赖
if not exist ".venv\Scripts\python.exe" (
    echo   首次运行，正在准备环境（约 2-4 分钟，只需一次）...
    echo.
    %PY% -m venv .venv
    if not %errorlevel%==0 (
        echo   建虚拟环境失败。
        pause
        exit /b 1
    )
    .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
    echo   正在安装依赖...
    .venv\Scripts\python.exe -m pip install --quiet -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
    .venv\Scripts\python.exe -m pip install --quiet pywebview -i https://pypi.tuna.tsinghua.edu.cn/simple
    if not %errorlevel%==0 (
        echo.
        echo   依赖安装失败。检查网络后重试。
        pause
        exit /b 1
    )
    echo   正在下载浏览器内核（约 150MB）...
    .venv\Scripts\python.exe -m playwright install chromium
    echo.
    echo   环境准备完成。
    echo.
)

echo   启动中...
echo.

REM 用 pythonw 可以完全隐藏命令行窗口；调试时用 python 看日志。
REM 现在先用 python，稳定之后再切 pythonw。
.venv\Scripts\python.exe desktop\app.py

if not %errorlevel%==0 (
    echo.
    echo   程序异常退出，错误码 %errorlevel%
    pause
)
