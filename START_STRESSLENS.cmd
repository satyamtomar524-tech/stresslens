@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. See README.md for setup.
  pause
  exit /b 1
)
echo Starting StressLens. Keep this window open; Ctrl+C stops the server.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address=127.0.0.1 --server.headless=false
if errorlevel 1 pause
