@echo off
setlocal
cd /d "%~dp0"

echo ================================================
echo Installing stronger local OCR tools
echo ================================================
echo.

where python >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_CMD=python"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON_CMD=py"
    ) else (
        echo Python was not found.
        pause
        exit /b 1
    )
)

echo Installing Python packages for EasyOCR...
%PYTHON_CMD% -m pip install --upgrade pip
%PYTHON_CMD% -m pip install easyocr opencv-python-headless numpy

echo.
echo Installing Tesseract OCR through winget if available...
where winget >nul 2>nul
if %errorlevel%==0 (
    winget install --id UB-Mannheim.TesseractOCR -e
) else (
    echo winget was not found. Skip Tesseract auto-install.
)

echo.
echo Done. Restart START.cmd.
pause
