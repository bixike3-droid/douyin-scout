@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
  echo 请先准备项目 Python 环境。
  pause
  exit /b 1
)
.venv\Scripts\python.exe -c "import PySide6.QtWebEngineWidgets, fastapi, uvicorn, websockets" >nul 2>&1
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install -e ".[web-desktop,codex]"
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
start "" ".venv\Scripts\pythonw.exe" "desktop-html\app.py"
