@echo off
chcp 65001 >nul
setlocal EnableExtensions

title AI Video Text Translator - Start

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo.
echo ==========================================
echo   AI Video Text Translator - START
echo ==========================================
echo.

if not exist "backend\venv\Scripts\activate.bat" (
    echo [ERROR] Chua setup backend virtual environment.
    echo Hay chay setup.bat truoc.
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo [ERROR] Chua setup frontend dependencies.
    echo Hay chay setup.bat truoc.
    pause
    exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Khong tim thay ffmpeg trong PATH.
    echo Hay cai FFmpeg va mo lai terminal. Xem HUONG_DAN_SETUP.txt.
    pause
    exit /b 1
)

where ffprobe >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Khong tim thay ffprobe trong PATH.
    echo Hay cai FFmpeg day du va mo lai terminal. Xem HUONG_DAN_SETUP.txt.
    pause
    exit /b 1
)

echo [1/2] Dang mo backend API tai http://127.0.0.1:8000 ...
start "AI VTT Backend" cmd /k "cd /d ""%ROOT%backend"" && call ""venv\Scripts\activate.bat"" && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

timeout /t 3 >nul

echo [2/2] Dang mo frontend UI tai http://127.0.0.1:5173 ...
start "AI VTT Frontend" cmd /k "cd /d ""%ROOT%frontend"" && npm run dev -- --host 127.0.0.1 --port 5173"

timeout /t 2 >nul
start "" "http://127.0.0.1:5173/"

echo.
echo ==========================================
echo   TOOL DANG CHAY
echo ==========================================
echo Backend:  http://127.0.0.1:8000
echo Frontend: http://127.0.0.1:5173
echo.
echo Luu y: backend se tu clear uploads/temp runtime khi khoi dong.
echo Muon tat tool thi dong 2 cua so Backend va Frontend vua mo.
echo.
pause
