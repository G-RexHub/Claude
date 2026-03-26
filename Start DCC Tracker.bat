@echo off
title DCC ADT Tracker
color 0A

echo ================================================
echo   DCC Anomaly Detection Threshold Tracker
echo ================================================
echo.

:: ── Check Python is installed ──────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo  ERROR: Python is not installed.
    echo.
    echo  Please install Python from:
    echo    https://www.python.org/downloads/
    echo.
    echo  Make sure to tick "Add Python to PATH" during install,
    echo  then double-click this file again.
    echo.
    pause
    exit /b 1
)

:: ── Install / update required packages ────────────
echo  Checking required packages...
pip install flask click -q --disable-pip-version-check
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  ERROR: Could not install required packages.
    echo  Check your internet connection and try again.
    echo.
    pause
    exit /b 1
)

:: ── Create data folder if it doesn't exist ────────
if not exist "data" mkdir data

:: ── Start the app ──────────────────────────────────
echo.
echo  Starting DCC ADT Tracker...
echo.

:: Start Python app in background
start /b python app.py > app.log 2>&1

:: Wait for Flask to start up
echo  Opening browser in 3 seconds...
timeout /t 3 /nobreak >nul

:: Open browser
start "" http://localhost:5000

echo.
echo ================================================
echo   App is running at http://localhost:5000
echo.
echo   Leave this window open while using the app.
echo   To STOP the app, close this window.
echo ================================================
echo.

:: Keep window open — closing it kills the app
:wait
timeout /t 5 /nobreak >nul
:: Check the app is still up
curl -s -o nul -w "%%{http_code}" http://localhost:5000 2>nul | find "200" >nul
if %errorlevel% neq 0 (
    color 0E
    echo  App stopped unexpectedly. Check app.log for details.
    pause
    exit /b 1
)
goto wait
