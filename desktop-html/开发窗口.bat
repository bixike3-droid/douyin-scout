@echo off
rem =====================================================================
rem  Yuanjing - dev window launcher
rem  Pure ASCII on purpose: a Chinese .bat without BOM breaks cmd parsing.
rem  What it does:
rem    1) pick two free ports (api / dev)
rem    2) generate a tiny temp .cmd that exports env vars and runs vite
rem    3) wait until the dev server answers
rem    4) open the Qt window pointed at the dev url
rem =====================================================================
setlocal
cd /d "%~dp0"

set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
set "TMPCMD=%TEMP%\yuanjing-vite-%RANDOM%.cmd"

if not exist "%PY%" (
  echo [x] .venv not found. Run desktop\启动.bat first.
  pause
  exit /b 1
)

for /f "delims=" %%p in ('powershell -NoProfile -Command "$l=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,0); $l.Start(); $p=$l.LocalEndpoint.Port; $l.Stop(); $p"') do set "APIPORT=%%p"
for /f "delims=" %%p in ('powershell -NoProfile -Command "$l=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,0); $l.Start(); $p=$l.LocalEndpoint.Port; $l.Stop(); $p"') do set "DEVPORT=%%p"

if not defined DEVPORT (
  echo [x] Cannot allocate free ports.
  pause
  exit /b 1
)

echo [1/4] api port: %APIPORT%   dev port: %DEVPORT%

rem ---- temp launcher, avoids nested-quote hell in `start cmd /c` ----
> "%TMPCMD%" echo @echo off
>>"%TMPCMD%" echo cd /d "%~dp0"
>>"%TMPCMD%" echo set "SCOUT_API=http://127.0.0.1:%APIPORT%"
>>"%TMPCMD%" echo set "SCOUT_DEV_PORT=%DEVPORT%"
>>"%TMPCMD%" echo call npm run dev

echo [2/4] starting vite...
start "yuanjing-vite" /min cmd /c "%TMPCMD%"

echo [3/4] waiting for dev server...
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
echo.
echo [x] dev server did not start on port %DEVPORT%.
echo     Try: cd desktop-html ^&^& npm install
echo     Also check the "yuanjing-vite" window for errors.
echo.
pause
exit /b 1

:dev_ok
echo [4/4] opening desktop window ^(api %APIPORT%^)...
start "" "%PY%" "%~dp0app.py" --port %APIPORT% --frontend http://127.0.0.1:%DEVPORT%/
echo.
echo Done. You can close this window; vite keeps running in background.
echo Edit files under src\ and the app window refreshes automatically.
timeout /t 4 >nul
exit /b 0
