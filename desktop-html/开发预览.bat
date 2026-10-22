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

echo [1/3] 检查本地 API...
set "READY=%ROOT%\tmp\ready.json"
set "INFO=%ROOT%\tmp\info.txt"
set "APIPORT=8765"
if not exist "%ROOT%\tmp" mkdir "%ROOT%\tmp"
set "INFO_TEXT="
if exist "%READY%" (
  powershell -NoProfile -Command "try { $j = Get-Content '%READY%' -Raw | ConvertFrom-Json; $u = 'http://127.0.0.1:' + $j.port + '/api/bootstrap'; $r = Invoke-WebRequest $u -TimeoutSec 3 -UseBasicParsing -Headers @{ Authorization = ('Bearer ' + $j.token) }; if ($r.StatusCode -eq 200) { Write-Output ('http://127.0.0.1:' + $j.port + ' ' + $j.token) } } catch { }" > "%INFO%"
  set /p INFO_TEXT=<"%INFO%"
)
if defined INFO_TEXT goto have_api

echo       启动新的后端（固定端口 %APIPORT%）...
del /q "%READY%" >nul 2>&1
set "PYTHONPATH=%ROOT%\src"
start "yuanjing-api" /min "%PY%" "%~dp0app.py" --serve-only --port %APIPORT% --ready-file "%READY%" --data-dir "%ROOT%\tmp\webtest"
set /a tries=0
:wait_api
if exist "%READY%" goto read_api
set /a tries+=1
if %tries% GEQ 40 (
  echo [x] 后端没起来。日志: tmp\webtest\data\accounts\main\logs\html-desktop.log
  pause
  exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait_api

:read_api
powershell -NoProfile -Command "$j = Get-Content '%READY%' -Raw | ConvertFrom-Json; Write-Output ('http://127.0.0.1:' + $j.port + ' ' + $j.token)" > "%INFO%"
set /p INFO_TEXT=<"%INFO%"

:have_api
for /f "tokens=1,2" %%a in ("%INFO_TEXT%") do (
  set "SCOUT_API=%%a"
  set "PREVIEW_URL=http://127.0.0.1:5173/#token=%%b"
)

echo [2/3] 后端: %SCOUT_API%
echo [3/3] 前端: npm run dev（热更新，关闭此窗口即停止前端）
echo.
echo    预览地址（每次 token 不同，以这一行为准）:
echo    %PREVIEW_URL%
echo.

start "" "%PREVIEW_URL%"
call npm run dev
endlocal
