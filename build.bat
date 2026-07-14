@echo off
REM ---------------------------------------------------------------------------
REM Build Kresge into a single standalone Windows executable: dist\Kresge.exe
REM
REM Run this from the project root. Requires the build tools:
REM   .venv\Scripts\python -m pip install pyinstaller pillow
REM ---------------------------------------------------------------------------
cd /d "%~dp0"

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo PyInstaller is not installed in the virtual environment. Run:
    echo   .venv\Scripts\python -m pip install pyinstaller pillow
    pause
    exit /b 1
)

".venv\Scripts\pyinstaller.exe" --noconfirm --onefile --windowed ^
  --name Kresge ^
  --icon "kresge\ui\assets\logo.ico" ^
  --add-data "kresge\ui\assets\logo.png;kresge\ui\assets" ^
  --collect-all scapy ^
  --collect-all winsdk ^
  main.py

echo.
echo ============================================================
echo  Build complete:  dist\Kresge.exe
echo ============================================================
echo  Note: per-device hotspot usage still needs the Npcap driver
echo  installed on the target PC, and Administrator rights ^(right-
echo  click Kresge.exe, Run as administrator^) for capture/blocking.
echo.
pause
