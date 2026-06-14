@echo off
cd /d "%~dp0"
echo Starting Fib Scanner...
start "Fib Scanner server" cmd /c "python -m http.server 8765 --directory public"
timeout /t 2 >nul
start "" http://localhost:8765
echo.
echo The scanner is now open in your browser at http://localhost:8765
echo Leave the small server window open while you use it. Close it to stop.
