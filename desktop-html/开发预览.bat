@echo off
rem Browser-based dev preview (fallback). ASCII only, see 开发窗口.bat note.
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
set "TMPCMD=%TEMP%\yuanjing-preview-%RANDOM%.cmd"

if not exist "%PY%" (
  echo [x] .venv not found. Run desktop\启动.bat first.
  pause
  exit /b 1
)

for /f "delims=" %%p in ('powershell -NoProfile -Command "$l=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,0); $l.Start(); $p=$l.LocalEndpoint.Port; $l.Stop(); $p"') do set "APIPORT=%%p"
for /f "delims=" %%p in ('powershell -NoProfile -Command "$l=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,0); $l.Start(); $p=$l.LocalEndpoint.Port; $l.Stop(); $p"') do set "DEVPORT=%%p"

if not exist "%ROOT%\tmp" mkdir "%ROOT%\tmp"
del /q "%ROOT%\tmp\ready.json" >nul 2>&1

echo [1/4] starting api on %APIPORT% ...
set "PYTHONPATH=%ROOT%\src"
start "yuanjing-api" /min "%PY%" "%~dp0app.py" --serve-only --port %APIPORT% --ready-file "%ROOT%\tmp\ready.json" --data-dir "%ROOT%\tmp\webtest"

set /a n=0
:wait_api
if exist "%ROOT%\tmp\ready.json" goto api_ok
set /a n+=1
if %n% GEQ 60 goto api_fail
timeout /t 1 /nobreak >nul
goto wait_api

:api_fail
echo [x] api did not start.
pause
exit /b 1

:api_ok
> "%TMPCMD%" echo @echo off
>>"%TMPCMD%" echo cd /d "%~dp0"
>>"%TMPCMD%" echo set "SCOUT_API=http://127.0.0.1:%APIPORT%"
>>"%TMPCMD%" echo set "SCOUT_DEV_PORT=%DEVPORT%"
>>"%TMPCMD%" echo call npm run dev

echo [2/4] starting vite on %DEVPORT% ...
start "yuanjing-vite" /min cmd /c "%TMPCMD%"

set /a n=0
:wait_dev
set "ALIVE="
for /f "delims=" %%i in ('powershell -NoProfile -Command "try { $r = Invoke-WebRequest http://127.0.0.1:%DEVPORT%/ -TimeoutSec 2 -UseBasicParsing; if ($r.StatusCode -eq 200) { Write-Output 1 } } catch { }"') do set "ALIVE=%%i"
if "%ALIVE%"=="1" goto dev_ok
set /a n+=1
if %n% GEQ 60 goto dev_fail
timeout /t 1 /nobreak >nul
goto wait_dev

:dev_fail
echo [x] dev server did not start.
pause
exit /b 1

:dev_ok
for /f "delims=" %%i in ('powershell -NoProfile -Command "$j = Get-Content \"%ROOT%\tmp\ready.json\" -Raw ^| ConvertFrom-Json; Write-Output $j.token"') do set "TOKEN=%%i"
echo.
echo [3/4] open in browser:
echo    http://127.0.0.1:%DEVPORT%/#token=%TOKEN%
echo.
start "" "http://127.0.0.1:%DEVPORT%/#token=%TOKEN%"
echo [4/4] vite is running. Close this window to stop the api.
echo.
pause
