@echo off
cd /d "C:\Users\r-ito\keiba-dashboard"
python do_git.py > git_result.txt 2>&1
type git_result.txt
pause
