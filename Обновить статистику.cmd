@echo off
cd /d "%~dp0"
venv\Scripts\python.exe update_stats.py
echo.
pause
