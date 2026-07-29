@echo off
rem ============================================================
rem  Keiba dashboard - allow access from your phone (same Wi-Fi)
rem
rem  This opens the app to OTHER DEVICES on your local network.
rem  There is NO password. Use it only on a network you trust
rem  (your home Wi-Fi), and close this window when finished.
rem
rem  The admin screens stay blocked for phones by design:
rem  admin actions are accepted only from this PC (127.0.0.1).
rem
rem  For normal use on this PC only, use run_app.bat instead.
rem ============================================================
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo.
echo  This PC's addresses (use one starting with 192.168 or 172):
ipconfig | findstr /C:"IPv4"
echo.
echo  On your phone (same Wi-Fi), open:  http://^<that address^>:8000
echo.
echo  Press Ctrl+C or close this window to stop.
echo.

python -m uvicorn app.backend.main:app --host 0.0.0.0 --port 8000
echo.
echo App stopped.
pause
