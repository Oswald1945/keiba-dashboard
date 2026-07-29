@echo off
rem Generate JV-based CSV sets (shutuba/past/hanro/wood) for a validation sample.
rem Output goes to jv_out\ . Double-click once; then Claude runs the A/B comparison.
setlocal
set PY=python "%~dp0jv_export.py"
%PY% --date 20251228 --jyo 06 --r 11
%PY% --date 20260222 --jyo 05 --r 11
%PY% --date 20260524 --jyo 05 --r 11
%PY% --date 20260530 --jyo 08 --r 11
%PY% --date 20260523 --jyo 08 --r 10
%PY% --date 20260523 --jyo 08 --r 7
%PY% --date 20260523 --jyo 04 --r 11
%PY% --date 20260523 --jyo 08 --r 12
%PY% --date 20260530 --jyo 05 --r 5
%PY% --date 20260530 --jyo 05 --r 11
echo.
echo === all done. Output in jv_out\ ===
pause
