@echo off
REM Launch Kresge using the project virtual environment.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Virtual environment not found. Run setup first:
    echo   python -m venv .venv
    echo   .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)
REM pythonw.exe runs without a console window (tray app).
start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py"
