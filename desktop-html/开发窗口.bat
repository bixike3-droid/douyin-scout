@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
set "APIPORT=8765"
set "DEVPORT=5173"

if not exist "%PY%" (
  echo [x] 没找到 .venv，请先运行 desktop\启动.bat 准备环境
  pause
  exit /b 1
)

echo [1/3] 检查前端开发服务（%DEVPORT%）...
set "HASDEV="
for /f "delims=" %%i in ('powershell -NoProfile -Command "try { $r = Invoke-WebRequest 'http://127.0.0.1:%DEVPORT%/' -TimeoutSec 2 -UseBasicParsing; if ($r.StatusCode -eq 200) { 'yes' } } catch { }"') do set "HASDEV=%%i"

if defined HASDEV (
  echo       已存在，直接复用
) else (
  echo       启动 Vite（热更新）...
  start "yuanjing-vite" /min cmd /c "cd /d ""%~dp0"" && npm run dev"
  set /a tries=0
  :wait_dev
  set "READYDEV="
  for /f "delims=" %%i in ('powershell -NoProfile -Command "try { $r = Invoke-WebRequest 'http://127.0.0.1:%DEVPORT%/' -TimeoutSec 2 -UseBasicParsing; if ($r.StatusCode -eq 200) { 'yes' } } catch { }"') do set "READYDEV=%%i"
  if defined READYDEV goto dev_ready
  set /a tries+=1
  if %tries% GEQ 40 (
    echo [x] 前端没起来：%DEVPORT% 被占用或 npm 报错
    echo     先关掉其它 node / python 黑窗口再试
    pause
    exit /b 1
  )
  timeout /t 1 /nobreak >nul
  goto wait_dev
)
:dev_ready

echo [2/3] 启动桌面窗口（内部会起本地 API，端口 %APIPORT%）...
echo [3/3] 修改 src 下的文件会自动刷新这个窗口
echo.

start "" "%PY%" "%~dp0app.py" --port %APIPORT% --frontend http://127.0.0.1:%DEVPORT%/
endlocal
