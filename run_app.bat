@echo off
rem ============================================================
rem  Keiba dashboard web app (local only)
rem  Serves on http://127.0.0.1:8000 and opens your browser.
rem  Close this window to stop the app.
rem ============================================================
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
start "" /b cmd /c "timeout /t 4 /nobreak >nul && explorer http://127.0.0.1:8000"
python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
echo.
echo App stopped.
pause
