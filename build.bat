@echo off
REM Texture Pig - Windows Build Script
REM Compiles Qt resources, builds the app (onedir), and packages an installer.
REM
REM Layout note: sources live in src\texture_pig\, build inputs in packaging\.
REM Outputs land at the repo root: dist\TexturePig\ and installer_output\.

setlocal enabledelayedexpansion

echo ============================================
echo    Texture Pig - Windows Build Script
echo ============================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH
    echo Please install Python 3.10+ and add it to your PATH
    pause
    exit /b 1
)

REM Run from the repo root (this script's directory)
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "QRC=src\texture_pig\ui\resources.qrc"
set "RCC_PY=src\texture_pig\ui\icons_rc.py"
set "RCC_BIN=src\texture_pig\ui\resources.rcc"

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
pyside6-rcc "%QRC%" -o "%RCC_PY%"
if errorlevel 1 (
    echo      Trying alternative method...
    python -c "import PySide6, os; print(os.path.dirname(PySide6.__file__))" > temp_path.txt
    set /p PYSIDE_PATH=<temp_path.txt
    del temp_path.txt
    "!PYSIDE_PATH!\rcc.exe" "%QRC%" -o "%RCC_PY%"
    if errorlevel 1 (
        echo ERROR: Failed to compile Qt resources
        pause
        exit /b 1
    )
)
pyside6-rcc "%QRC%" -binary -o "%RCC_BIN%"
echo      Qt resources compiled successfully

echo.
echo [3/5] Building executable with PyInstaller...
echo      This may take a few minutes...
REM --workpath keeps PyInstaller's scratch files in build\intermediate\.
REM They include a TexturePig.exe that looks like the app but is NOT runnable:
REM it's the bare bootloader stub, with no _internal\ folder beside it. Only
REM dist\TexturePig\TexturePig.exe actually runs.
pyinstaller --clean -y --workpath build\intermediate packaging\TexturePig.spec
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
    "!ISCC!" packaging\installer.iss
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
echo    RUN THIS:      dist\TexturePig\TexturePig.exe
echo    Installer:     installer_output\TexturePigSetup-*.exe
echo.
echo    Note: build\intermediate\ holds PyInstaller scratch files, including
echo          a TexturePig.exe that will NOT run (no _internal\ beside it).
echo          Always launch the one in dist\TexturePig\.
echo.
echo ============================================

pause
