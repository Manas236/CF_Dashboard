@echo off
REM Hourly Cloudflare rollup collector. Invoked by the "Cloudflare Dashboard Collector"
REM scheduled task. Runs from the project root and appends to logs\collector.log.
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
".venv\Scripts\python.exe" collector.py >> "logs\collector.log" 2>&1
