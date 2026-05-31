@echo off
cd /d "%~dp0"
title Build - Apy Schedule

echo ==============================================
echo  Build Script for Apy Schedule
echo ==============================================
echo.

:: --- Step 1: Install PyInstaller if missing ---
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [Step 1] Installing PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] pip install pyinstaller failed.
        pause
        exit /b 1
    )
) else (
    echo [Step 1] PyInstaller OK
)

:: --- Step 2: Remove conflicting pathlib if present ---
python -m pip show pathlib >nul 2>&1
if not errorlevel 1 (
    echo [Step 2] Removing incompatible pathlib package...
    python -m pip uninstall pathlib -y
) else (
    echo [Step 2] pathlib conflict: none
)

:: --- Step 3: Read version from version.py ---
for /f "usebackq delims=" %%v in (`python -c "from version import APP_VERSION; print(APP_VERSION)"`) do set VERSION=%%v
for /f "usebackq delims=" %%d in (`python -c "from version import APP_DATE; print(APP_DATE)"`) do set VERDATE=%%d
for /f "usebackq delims=" %%s in (`python -c "from version import DB_SCHEMA_VERSION; print(DB_SCHEMA_VERSION)"`) do set SCHEMA_VER=%%s
echo [Step 3] Version: %VERSION%  Date: %VERDATE%  DB Schema: %SCHEMA_VER%

:: --- Step 4: Generate Windows version info file ---
echo [Step 4] Generating version info file...
python gen_version_info.py
if errorlevel 1 (
    echo [WARNING] version info generation failed, continuing without it
) else (
    echo [Step 4] version info file generated OK
)

:: --- Step 5: Run PyInstaller ---
echo.
echo [Step 5] Building EXE ... please wait (3-5 min)
echo.
python -m PyInstaller apy_schedule.spec --noconfirm
echo.

:: --- Step 6: Check base result ---
if not exist "dist\作業予定管理.exe" (
    echo ==============================================
    echo  BUILD FAILED
    echo  Check: build\apy_schedule\warn-apy_schedule.txt
    echo ==============================================
    echo.
    pause
    exit /b 1
)

:: --- Step 7: Copy with version number in filename ---
set VERSIONED=dist\作業予定管理_v%VERSION%.exe
copy /Y "dist\作業予定管理.exe" "%VERSIONED%" >nul
if errorlevel 1 (
    echo [WARNING] versioned copy failed
) else (
    echo [Step 7] Versioned copy: %VERSIONED%
)

echo ==============================================
echo  BUILD SUCCESS
echo  Base  : dist\作業予定管理.exe
echo  配布用 : %VERSIONED%
echo  Version: v%VERSION%  (%VERDATE%)
echo  DB Schema: v%SCHEMA_VER%
echo ==============================================
echo.
pause
