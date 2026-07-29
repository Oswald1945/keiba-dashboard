@echo off
rem Export past-runs / Hanro / Wood CSVs for one race from race.db into jv_out\.
rem Jyo code: 01Sapporo 02Hakodate 03Fukushima 04Niigata 05Tokyo
rem           06Nakayama 07Chukyo 08Kyoto 09Hanshin 10Kokura
setlocal
set /p D=Race date YYYYMMDD (e.g. 20251228):
set /p J=Jyo code 01-10 (e.g. 06):
set /p R=Race number (e.g. 11):
python "%~dp0jv_export.py" --date %D% --jyo %J% --r %R%
echo.
echo (output in jv_out\ folder)
pause
