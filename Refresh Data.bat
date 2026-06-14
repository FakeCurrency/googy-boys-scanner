@echo off
cd /d "%~dp0"
echo Running the scanner for ASX + NASDAQ. This can take several minutes for the full ASX...
echo.
python -m scanner.run --journal
echo.
echo Done. Refresh your browser (or re-open Start Fib Scanner) to see the latest results.
pause
