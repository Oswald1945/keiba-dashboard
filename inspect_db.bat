@echo off
rem Inspect race.db structure -> writes db_schema.txt next to this file.
setlocal
set SCRIPT_DIR=%~dp0
python "%SCRIPT_DIR%inspect_db.py"
echo.
echo (db_schema.txt in this folder)
pause
