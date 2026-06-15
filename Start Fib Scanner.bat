@echo off
cd /d "%~dp0"
echo Starting Googy Boys Scanner...
start "Googy Boys server" cmd /c ".venv\Scripts\python.exe serve.py 8765 public"
timeout /t 2 >nul
start "" http://localhost:8765
echo.
echo The scanner is now open in your browser at http://localhost:8765
echo Leave the small server window open while you use it. Close it to stop.
