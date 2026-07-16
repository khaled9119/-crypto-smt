@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "CLOUDFLARED=%LOCALAPPDATA%\cloudflared\cloudflared.exe"

echo =======================================================
echo   Crypto Smart Money Tracker -- Go Online
echo   (via Cloudflare Tunnel)
echo =======================================================
echo.

rem Check if flask is running
python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000', timeout=2)" >nul 2>&1
if %errorlevel% equ 0 (
    echo  [OK] Flask already running
) else (
    echo  [..] Starting Flask...
    set PYTHONIOENCODING=utf-8
    start /b python web\app.py
    timeout /t 3 /nobreak >nul
    echo  [OK] Flask started
)

echo  [..] Starting Cloudflare Tunnel...

rem Start cloudflared with output to a temp file
set "OUTFILE=%TEMP%\cloudflared_tunnel.txt"
del "%OUTFILE%" 2>nul

start /b "" "%CLOUDFLARED%" tunnel --url http://127.0.0.1:5000 >"%OUTFILE%" 2>&1

rem Wait for URL
echo  [..] Waiting for tunnel URL...
set "URL="
for /l %%i in (1,1,60) do (
    timeout /t 1 /nobreak >nul
    for /f "tokens=2 delims= " %%a in ('findstr "trycloudflare.com" "%OUTFILE%"') do (
        set "URL=%%a"
    )
    if defined URL goto found
)

echo  [ERROR] Timed out waiting for URL
type "%OUTFILE%"
pause
exit /b

:found
echo.
echo =======================================================
echo   PUBLIC URL:  %URL%
echo =======================================================
echo   Share this link with anyone!
echo.
start "" "%URL%"

type "%OUTFILE%" 2>nul
echo.
echo  Press Ctrl+C to stop the tunnel.
echo.

:loop
timeout /t 1 /nobreak >nul
goto loop
