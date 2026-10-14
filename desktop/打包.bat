@echo off
chcp 65001 >nul
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo 请先运行 desktop\启动.bat 准备环境。
    pause
    exit /b 1
)

echo [1/2] 准备桌面依赖与打包工具...
.venv\Scripts\python.exe -m pip install -e ".[desktop]" pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo 依赖安装失败。
    pause
    exit /b 1
)

echo [2/2] 打包原生桌面程序...
REM 只携带默认配置与数据库迁移，用户配置由程序保存在 userdata。
.venv\Scripts\python.exe -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --name 源镜 ^
    --distpath dist/yuanjing ^
    --onefile ^
    --windowed ^
    --icon "src/scout/desktop/assets/yuanjing.ico" ^
    --add-data "config/default.yaml;config" ^
    --add-data "src/scout/desktop/assets;scout/desktop/assets" ^
    --add-data "src/scout/db/migrations;scout/db/migrations" ^
    --collect-all playwright ^
    --exclude-module PySide6.QtWebEngineCore ^
    --exclude-module PySide6.QtWebEngineWidgets ^
    --exclude-module PySide6.QtWebEngineQuick ^
    desktop\app.py
if errorlevel 1 (
    echo 打包失败，请查看上面的错误。
    pause
    exit /b 1
)

echo 完成：dist\yuanjing\源镜.exe
echo 分发程序即可，用户数据和设置将在首次运行时建立。
echo 默认进入源镜传播工作台，保留抖音登录、采集及历史分析。
pause
