@echo off
REM Texture Pig - Windows build script.
REM Compiles Qt resources, builds the app (onedir), and packages an installer.
REM
REM Layout:  src\texture_pig\   sources
REM          packaging\         build inputs (spec, installer script, launcher)
REM          out\               everything this script produces
REM
REM Everything lands in out\:
REM     out\TexturePig\TexturePig.exe   <- the app (run this)
REM     out\TexturePigSetup-*.exe       <- the installer
REM PyInstaller's scratch files go to %TEMP%, deliberately not into the project.

setlocal enabledelayedexpansion

echo ============================================
echo    Texture Pig - Windows Build Script
echo ============================================
echo.

REM Run from the repo root (this script's directory)
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Prefer the project's virtualenv if there is one, so the build doesn't
REM silently pick up a different interpreter that happens to be on PATH.
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    set "RCC=.venv\Scripts\pyside6-rcc.exe"
    set "VENV_NOTE= (using .venv)"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python not found in PATH and no .venv\ in the project.
        echo Create one with:  python -m venv .venv ^&^& .venv\Scripts\pip install -e ".[dev]"
        pause
        exit /b 1
    )
    set "PY=python"
    set "RCC=pyside6-rcc"
    set "VENV_NOTE="
)

set "QRC=src\texture_pig\ui\resources.qrc"
set "RCC_PY=src\texture_pig\ui\icons_rc.py"
set "RCC_BIN=src\texture_pig\ui\resources.rcc"
set "WORK_DIR=%TEMP%\texturepig-build"

echo [1/5] Checking dependencies!VENV_NOTE!...
"!PY!" -c "import PySide6, numpy, cv2, PIL" >nul 2>&1
if errorlevel 1 (
    echo      Missing dependencies. Installing from requirements.txt...
    "!PY!" -m pip install -r requirements.txt
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
REM pyside6-rcc ships in the same Scripts\ dir as the interpreter; if it isn't
REM there, fall back to rcc.exe inside the installed PySide6 package.
if not exist "!RCC!" where "!RCC!" >nul 2>&1 || (
    for /f "usebackq delims=" %%P in (`"!PY!" -c "import PySide6,os;print(os.path.join(os.path.dirname(PySide6.__file__),'rcc.exe'))"`) do set "RCC=%%P"
)
"!RCC!" "%QRC%" -o "%RCC_PY%"
if errorlevel 1 (
    echo ERROR: Failed to compile Qt resources ^(tried: !RCC!^)
    pause
    exit /b 1
)
"!RCC!" "%QRC%" -binary -o "%RCC_BIN%"
if errorlevel 1 (
    echo ERROR: Failed to compile binary Qt resources
    pause
    exit /b 1
)
echo      Qt resources compiled successfully

echo.
echo [3/5] Building executable with PyInstaller...
echo      This may take a few minutes...
REM --distpath : finished app -> out\TexturePig\
REM --workpath : scratch -> %TEMP%. Those scratch files include a TexturePig.exe
REM              that looks like the app but cannot run (bare bootloader stub
REM              with no _internal\ beside it). Keeping it out of the project
REM              means there is only ever one TexturePig.exe here.
"!PY!" -m PyInstaller --clean -y --distpath out --workpath "%WORK_DIR%" packaging\TexturePig.spec
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
    echo      Install it from https://jrsoftware.org/isinfo.php
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
echo    Build Output
echo ============================================
echo.
echo    RUN THIS:   out\TexturePig\TexturePig.exe
echo    Installer:  out\TexturePigSetup-*.exe
echo.
echo    (scratch files: %WORK_DIR% - outside the project)
echo.
echo ============================================

pause
