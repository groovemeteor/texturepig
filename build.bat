@echo off
REM Texture Pig - Windows Build Script
REM This script compiles Qt resources and builds the Windows executable

setlocal enabledelayedexpansion

echo ============================================
echo    Texture Pig - Windows Build Script
echo ============================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH
    echo Please install Python 3.9+ and add it to your PATH
    pause
    exit /b 1
)

REM Get the script directory
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo [1/4] Checking dependencies...
python -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo      PySide6 not found. Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies
        pause
        exit /b 1
    )
) else (
    echo      Dependencies OK
)

echo.
echo [2/4] Compiling Qt resources...
pyside6-rcc ui/resources.qrc -o ui/icons_rc.py
if errorlevel 1 (
    echo      Trying alternative method...
    python -c "import PySide6; import os; print(os.path.dirname(PySide6.__file__))" > temp_path.txt
    set /p PYSIDE_PATH=<temp_path.txt
    del temp_path.txt
    "!PYSIDE_PATH!\rcc.exe" ui/resources.qrc -o ui/icons_rc.py
    if errorlevel 1 (
        echo ERROR: Failed to compile Qt resources
        pause
        exit /b 1
    )
)
echo      Qt resources compiled successfully

echo.
echo [3/4] Building executable with PyInstaller...
echo      This may take several minutes...
pyinstaller --clean -y TexturePig.spec
if errorlevel 1 (
    echo ERROR: PyInstaller build failed
    pause
    exit /b 1
)

echo.
echo [4/4] Build complete!
echo.
echo ============================================
echo    Build Output:
echo ============================================
echo.
echo    Single EXE:    dist\TexturePig.exe
echo    Folder build:  dist\TexturePig\
echo.
echo    Run the app:   dist\TexturePig.exe
echo                   or dist\TexturePig\TexturePig.exe
echo.
echo ============================================

pause
