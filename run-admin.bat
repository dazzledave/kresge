@echo off
REM Launch Kresge elevated (Administrator) so the Hotspot tab can measure
REM per-device usage. Per-device usage ALSO requires the Npcap driver
REM (https://npcap.com). Without Npcap, the app still runs but shows device
REM presence only.
cd /d "%~dp0"

REM Already elevated? Then just launch. Otherwise re-launch this script via UAC.
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

if not exist ".venv\Scripts\pythonw.exe" (
    echo Virtual environment not found. Run setup first:
    echo   python -m venv .venv
    echo   .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)

REM pythonw.exe = no console window (tray app).
start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py"
