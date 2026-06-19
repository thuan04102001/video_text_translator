@echo off
title AI Video Translator - Regression Runner

cd /d "%~dp0"

echo ==========================================
echo AI VIDEO TRANSLATOR - REGRESSION RUNNER
echo ==========================================
echo.

REM =========================
REM CHECK VENV
REM =========================

if exist "venv\Scripts\activate.bat" (
    echo [OK] Found venv.
) else (
    echo [ERROR] venv not found:
    echo %cd%\venv
    pause
    exit /b 1
)

REM =========================
REM ACTIVATE VENV
REM =========================

call venv\Scripts\activate.bat

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to activate venv.
    pause
    exit /b 1
)

echo.
echo [OK] venv activated.
echo.

REM =========================
REM SHOW PYTHON
REM =========================

python --version

echo.
echo ==========================================
echo START REGRESSION
echo ==========================================
echo.

REM =========================
REM RUN REGRESSION
REM =========================

python tests\regression\regression_runner.py

echo.
echo ==========================================
echo REGRESSION FINISHED
echo ==========================================
echo.

REM =========================
REM AUTO OPEN FAIL SUMMARY
REM =========================

if exist "tests\regression\reports\fail_only_latest.json" (
    echo Opening fail_only_latest.json ...
    start "" "tests\regression\reports\fail_only_latest.json"
)

echo.
pause