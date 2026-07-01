@echo off
REM 3-day local backfill. Invoked by the "Cloudflare Dashboard Local Backfill"
REM scheduled task. Pulls 192 h (full CF free-plan retention) to fill any gaps.
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
".venv\Scripts\python.exe" collector.py --hours 192 >> "logs\backfill.log" 2>&1
