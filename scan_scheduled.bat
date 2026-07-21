@echo off
REM Run by Windows Task Scheduler twice daily (6:30am & 4:30pm AEST).
REM Scans ASX + NASDAQ + Crypto (both scanners) and updates the journal.
cd /d "%~dp0"
echo. >> scan.log
echo ============================================================ >> scan.log
echo [%date% %time%] Scan started >> scan.log
".venv\Scripts\python.exe" -m scanner.run --journal >> scan.log 2>&1
echo [%date% %time%] Scan finished (exit %errorlevel%) >> scan.log
