@echo off
REM ---------------------------------------------------------------------------
REM Build Kresge for Windows:
REM   dist\Kresge\Kresge.exe             - the app (one-folder PyInstaller build)
REM   dist\KresgeSetup-<version>.exe     - the installer (needs Inno Setup 6)
REM
REM Run this from the project root. Requires the build tools:
REM   .venv\Scripts\python -m pip install pyinstaller pillow
REM   winget install JRSoftware.InnoSetup
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo PyInstaller is not installed in the virtual environment. Run:
    echo   .venv\Scripts\python -m pip install pyinstaller pillow
    pause
    exit /b 1
)

REM Read the version from kresge\__init__.py
for /f "delims=" %%v in ('call ".venv\Scripts\python.exe" -c "import kresge; print(kresge.__version__)"') do set "VERSION=%%v"
if not defined VERSION (
    echo Could not read the version from kresge\__init__.py
    pause
    exit /b 1
)

echo.
echo === Building Kresge %VERSION% ===
echo.

".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onedir --windowed ^
  --name Kresge ^
  --icon "kresge\ui\assets\logo.ico" ^
  --add-data "kresge\ui\assets\logo.png;kresge\ui\assets" ^
  --collect-all scapy ^
  --collect-all winsdk ^
  main.py
if errorlevel 1 (
    echo PyInstaller build failed.
    pause
    exit /b 1
)

REM Locate the Inno Setup compiler (per-user or machine-wide install)
set "ISCC="
for %%p in (
    "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
) do if not defined ISCC if exist %%p set "ISCC=%%~p"

if not defined ISCC (
    echo.
    echo Inno Setup 6 not found - skipping the installer.
    echo Install it with:  winget install JRSoftware.InnoSetup
    echo The app itself is in dist\Kresge\
    pause
    exit /b 0
)

"%ISCC%" /Q /DAppVersion=%VERSION% installer\kresge.iss
if errorlevel 1 (
    echo Installer build failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Build complete:
echo    App:        dist\Kresge\Kresge.exe
echo    Installer:  dist\KresgeSetup-%VERSION%.exe
echo ============================================================
echo  Note: per-device hotspot usage still needs the Npcap driver
echo  installed on the target PC, and Administrator rights for
echo  capture/blocking ^(use the "Kresge (Administrator)" shortcut^).
echo.
if not defined CI pause
