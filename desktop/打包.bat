@echo off
chcp 65001 >nul
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo 请先运行 desktop\启动.bat 准备环境。
    pause
    exit /b 1
)

echo [1/3] 准备桌面依赖与打包工具...
.venv\Scripts\python.exe -m pip install -e ".[desktop]" pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo 依赖安装失败。
    pause
    exit /b 1
)

echo [2/3] 打包原生桌面程序（onedir，减少杀软误报）...
REM onedir 不再自解压到临时目录；版本信息写进 exe 属性，避免“未知发布者+无描述”
.venv\Scripts\python.exe -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --name 源镜 ^
    --distpath dist/yuanjing ^
    --onedir ^
    --windowed ^
    --icon "src/scout/desktop/assets/yuanjing.ico" ^
    --version-file "scripts/version_info.txt" ^
    --add-data "config/default.yaml;config" ^
    --add-data "src/scout/desktop/assets;scout/desktop/assets" ^
    --add-data "src/scout/db/migrations;scout/db/migrations" ^
    --collect-all playwright ^
    --collect-all imageio_ffmpeg ^
    --collect-all pypdfium2 ^
    --collect-all pypdfium2_raw ^
    --collect-all py7zr ^
    --collect-all pillow_heif ^
    --exclude-module PySide6.QtWebEngineCore ^
    --exclude-module PySide6.QtWebEngineWidgets ^
    --exclude-module PySide6.QtWebEngineQuick ^
    desktop\app.py
if errorlevel 1 (
    echo 打包失败，请查看上面的错误。
    pause
    exit /b 1
)

echo [3/3] 附使用说明并生成 SHA256...
copy /y "desktop\使用说明.txt" "dist\yuanjing\源镜\使用说明.txt" >nul
powershell -NoProfile -Command "Get-FileHash 'dist\yuanjing\源镜\源镜.exe' -Algorithm SHA256 | ForEach-Object { \"$($_.Hash)  源镜.exe\" } | Set-Content -Encoding UTF8 'dist\yuanjing\源镜\SHA256.txt'"

echo 完成：dist\yuanjing\源镜\
echo 分发时把整个「源镜」文件夹压缩成 zip，用户解压后双击 源镜.exe。
echo 如有代码签名证书，可执行： scripts\sign_exe.ps1 -Pfx 证书.pfx -Password 密码
pause
