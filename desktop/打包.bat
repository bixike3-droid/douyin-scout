@echo off
chcp 65001 >nul
cd /d "%~dp0\.."

echo.
echo ============================================================
echo   打包成独立 exe（双击即用，用户不需要装 Python）
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo   先运行一次 启动.bat 把环境准备好。
    pause
    exit /b 1
)

echo   [1/3] 安装打包工具...
.venv\Scripts\python.exe -m pip install --quiet pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple

echo   [2/3] 打包（首次约 3-6 分钟）...
REM --add-data 把前端页面和本地助手包带进去，否则运行时找不到。
REM --collect-all 收齐 playwright / webview 的隐式依赖，漏了会在别人机器上崩。
.venv\Scripts\python.exe -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --name douyin-scout ^
    --onefile ^
    --add-data "src/scout/web/static;scout/web/static" ^
    --add-data "config;config" ^
    --collect-all webview ^
    --collect-all playwright ^
    --hidden-import uvicorn.logging ^
    --hidden-import uvicorn.loops.auto ^
    --hidden-import uvicorn.protocols.http.auto ^
    --hidden-import uvicorn.protocols.websockets.auto ^
    --hidden-import uvicorn.lifespan.on ^
    desktop\app.py

if not %errorlevel%==0 (
    echo.
    echo   打包失败，看上面的错误。
    pause
    exit /b 1
)

echo.
echo   [3/3] 完成
echo.
echo   exe 在： dist\douyin-scout.exe
echo.
echo   注意：这个 exe 还需要两样东西才能跑：
echo     1. 同目录下的 config 文件夹（含 default.yaml 和你的 llm.local.yaml）
echo     2. Playwright 的浏览器（首次运行会自动下载）
echo.
echo   要分发给别人，把 dist\douyin-scout.exe 和 config 一起打包。
echo.
pause
