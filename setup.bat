@echo off
chcp 65001 >nul
setlocal EnableExtensions

title AI Video Text Translator - Setup

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo.
echo ==========================================
echo   AI Video Text Translator - SETUP
echo ==========================================
echo.

if not exist "backend" (
    echo [ERROR] Khong tim thay folder backend.
    pause
    exit /b 1
)

if not exist "frontend" (
    echo [ERROR] Khong tim thay folder frontend.
    pause
    exit /b 1
)

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Chua cai Python hoac Python chua co trong PATH.
        echo Xem file HUONG_DAN_SETUP.txt de cai moi truong.
        pause
        exit /b 1
    )
    set "PYTHON_CMD=python"
)

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Chua cai NodeJS/npm hoac npm chua co trong PATH.
    echo Xem file HUONG_DAN_SETUP.txt de cai moi truong.
    pause
    exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Khong tim thay ffmpeg trong PATH.
    echo Render video/audio/frame template can ffmpeg.
    echo Xem file HUONG_DAN_SETUP.txt de cai FFmpeg.
    pause
    exit /b 1
)

where ffprobe >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Khong tim thay ffprobe trong PATH.
    echo Render frame/audio can ffprobe de doc thoi luong video/audio.
    echo Xem file HUONG_DAN_SETUP.txt de cai FFmpeg day du.
    pause
    exit /b 1
)

echo [1/5] Tao/cap nhat Python virtual environment...
if not exist "backend\venv" (
    call %PYTHON_CMD% -m venv "backend\venv"
    if errorlevel 1 (
        echo [ERROR] Khong tao duoc backend\venv.
        pause
        exit /b 1
    )
)

call "backend\venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Khong activate duoc backend\venv.
    pause
    exit /b 1
)

echo.
echo [2/5] Cai backend dependencies...
python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [ERROR] Loi update pip/setuptools/wheel.
    pause
    exit /b 1
)

pip install -r "backend\requirements.txt"
if errorlevel 1 (
    echo [ERROR] Loi cai backend requirements.
    pause
    exit /b 1
)

echo.
echo [3/5] Cai Playwright Chromium cho Video Crawler...
python -m playwright install chromium
if errorlevel 1 (
    echo [WARN] Playwright Chromium cai chua thanh cong.
    echo Neu Video Crawler loi browser, hay chay lai setup.bat hoac xem HUONG_DAN_SETUP.txt.
)

echo.
echo [4/5] Cai frontend dependencies...
cd /d "%ROOT%frontend"
call npm install
if errorlevel 1 (
    echo [ERROR] Loi npm install.
    pause
    exit /b 1
)

cd /d "%ROOT%"

echo.
echo [5/5] Tao thu muc runtime can thiet...
if not exist "backend\uploads" mkdir "backend\uploads"
if not exist "backend\outputs" mkdir "backend\outputs"
if not exist "backend\temp" mkdir "backend\temp"
if not exist "backend\logs" mkdir "backend\logs"
if not exist "backend\models" mkdir "backend\models"
if not exist "backend\frame_templates" mkdir "backend\frame_templates"
if not exist "temp" mkdir "temp"
if not exist "outputs" mkdir "outputs"

echo.
echo ==========================================
echo   SETUP HOAN TAT
echo ==========================================
echo.
echo De chay tool: mo start.bat
echo UI: http://127.0.0.1:5173
echo API: http://127.0.0.1:8000
echo.
pause
