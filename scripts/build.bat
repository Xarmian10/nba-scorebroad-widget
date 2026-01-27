@echo off
setlocal

REM Build the PySide6 NBA scoreboard widget (one-dir). Requires venv.
if not exist "..\.venv\Scripts\pyinstaller.exe" (
    echo Please create and activate .venv with PyInstaller installed.
    exit /b 1
)

cd /d "%~dp0.."
echo Building with PyInstaller...
".venv\Scripts\pyinstaller.exe" --clean --noconfirm build.spec

echo Done. Output in .\dist\nba-scoreboard
endlocal








