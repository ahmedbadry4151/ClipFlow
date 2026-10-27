@echo off
title ClipFlow
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found in your PATH.
    echo Please install Python 3.11+ and ensure "Add Python to PATH" is checked.
    pause
    exit /b 1
)

:: First-time setup: install requirements if not already done
if not exist ".installed" (
    echo ===================================================
    echo   First-time setup: Installing required packages...
    echo ===================================================
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to install dependencies. Please check your internet connection.
        pause
        exit /b 1
    )
    echo Installed on %date% at %time% > .installed
    echo.
    echo [INFO] Dependencies installed successfully!
    echo.
)

echo Starting ClipFlow and opening web browser...
python -m app serve --open
if errorlevel 1 pause
