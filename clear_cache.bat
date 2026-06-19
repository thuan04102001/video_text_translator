@echo off
chcp 65001 >nul
setlocal EnableExtensions

title AI Video Text Translator - Clear Cache

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo.
echo ==========================================
echo   AI Video Text Translator - CLEAR CACHE
echo ==========================================
echo.

if exist "backend\venv\Scripts\python.exe" (
    echo [1/3] Dang don pip cache...
    "backend\venv\Scripts\python.exe" -m pip cache purge
) else (
    echo [SKIP] Khong tim thay backend\venv, bo qua pip cache.
)

echo.
where npm >nul 2>nul
if errorlevel 1 (
    echo [SKIP] Khong tim thay npm, bo qua npm cache.
) else (
    echo [2/3] Dang don npm cache...
    call npm cache clean --force
)

echo.
echo [3/3] Don cache hoan tat.
echo.
echo Luu y:
echo - File nay chi don cache cai dat package.
echo - Khong xoa backend\venv, frontend\node_modules, template, output hay source code.
echo - Lan setup sau co the tai package lau hon mot chut vi cache da duoc don.
echo.
pause
