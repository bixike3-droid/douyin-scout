@echo off
chcp 65001 >nul
rem 源码模式启动 WebView2 桌面版（打包版直接双击 exe，不需要这个文件）
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
  echo 请先准备项目 Python 环境：pwsh -File scripts\setup.ps1
  pause
  exit /b 1
)
.venv\Scripts\python.exe -c "import webview, fastapi, uvicorn, clr" >nul 2>&1
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install -e ".[windows-desktop]"
  if errorlevel 1 exit /b 1
)
if not exist "desktop-html\dist\index.html" (
  pushd desktop-html
  call npm ci
  if errorlevel 1 exit /b 1
  call npm run build
  if errorlevel 1 exit /b 1
  popd
)
start "" ".venv\Scripts\pythonw.exe" "desktop-html\windows.py"
