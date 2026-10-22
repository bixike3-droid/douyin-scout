@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [x] 没找到 .venv，请先运行 desktop\启动.bat 准备环境
  pause
  exit /b 1
)

echo [1/3] 启动本地 API 服务...
if not exist "%ROOT%\tmp" mkdir "%ROOT%\tmp"
del /q "%ROOT%\tmp\ready.json" >nul 2>&1
set "PYTHONPATH=%ROOT%\src"
start "yuanjing-api" /min "%PY%" "%~dp0app.py" --serve-only --ready-file "%ROOT%\tmp\ready.json" --data-dir "%ROOT%\tmp\webtest"

echo [2/3] 等待服务就绪（最多 30 秒）...
set /a tries=0
:wait
if exist "%ROOT%\tmp\ready.json" goto ready
set /a tries+=1
if %tries% GEQ 30 (
  echo [x] 服务没起来，查看日志: tmp\webtest\data\accounts\main\logs\html-desktop.log
  pause
  exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait

:ready
for /f "delims=" %%i in ('powershell -NoProfile -Command "$j=Get-Content \"%ROOT%\tmp\ready.json\" -Raw | ConvertFrom-Json; Write-Output ($j.port.ToString() + ' ' + $j.token)"') do set "INFO=%%i"
for /f "tokens=1,2" %%a in ("%INFO%") do (
  set "PORT=%%a"
  set "TOKEN=%%b"
)
set "SCOUT_API=http://127.0.0.1:%PORT%"
echo [3/3] 后端端口: %PORT%
echo.
echo    预览地址（每次 token 不同，复制这一行）:
echo    http://127.0.0.1:5173/#token=%TOKEN%
echo.
start "" "http://127.0.0.1:5173/#token=%TOKEN%"
call npm run dev
endlocal
