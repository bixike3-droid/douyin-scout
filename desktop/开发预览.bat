@echo off
chcp 65001 >nul
cd /d "%~dp0\.."

echo.
echo ============================================================
echo   源镜 · 开发预览（改代码自动重载）
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo   尚未准备环境：请先双击 desktop\启动.bat 完成首次安装。
    echo.
    pause
    exit /b 1
)

echo   启动中……
echo   - 修改 src\scout\ 下的 .py、desktop\app.py 或 config\default.yaml
echo     后，窗口会在安全状态自动重载。
echo   - 任务运行中、有未保存输入或企业资料有改动时，会等待安全后再重载。
echo.

.venv\Scripts\python.exe desktop\app.py --dev-mode

if not %errorlevel%==0 (
    echo.
    echo   程序异常退出，错误码 %errorlevel%
    pause
)
