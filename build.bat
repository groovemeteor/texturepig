@echo off
REM Texture Pig - Windows Build Script
REM Compiles Qt resources, builds the app (onedir), and packages an installer.

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

echo [1/5] Checking dependencies...
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
echo [2/5] Compiling Qt resources...
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
pyside6-rcc ui/resources.qrc -binary -o ui/resources.rcc
echo      Qt resources compiled successfully

echo.
echo [3/5] Building executable with PyInstaller...
echo      This may take a few minutes...
pyinstaller --clean -y TexturePig.spec
if errorlevel 1 (
    echo ERROR: PyInstaller build failed
    pause
    exit /b 1
)

echo.
echo [4/5] Building installer...
set "ISCC="
where ISCC >nul 2>&1 && set "ISCC=ISCC"
if "!ISCC!"=="" if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if "!ISCC!"=="" if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if "!ISCC!"=="" if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if "!ISCC!"=="" (
    echo      Inno Setup not found - skipping installer step.
    echo      Install it from https://jrsoftware.org/isinfo.php to build TexturePigSetup-*.exe,
    echo      or: winget install JRSoftware.InnoSetup
) else (
    "!ISCC!" installer.iss
    if errorlevel 1 (
        echo ERROR: Installer build failed
        pause
        exit /b 1
    )
)

echo.
echo [5/5] Build complete!
echo.
echo ============================================
echo    Build Output:
echo ============================================
echo.
echo    App folder:    dist\TexturePig\   (run dist\TexturePig\TexturePig.exe)
echo    Installer:     installer_output\TexturePigSetup-*.exe
echo.
echo ============================================

pause
