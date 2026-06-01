@echo off
setlocal

echo This script installs Tesseract OCR with winget.
echo If Windows asks for confirmation, accept it.
echo.

where winget >nul 2>nul
if errorlevel 1 (
    echo winget was not found. Install Tesseract manually from UB Mannheim build.
    pause
    exit /b 1
)

winget install --id UB-Mannheim.TesseractOCR -e

echo.
echo After installation, restart START.cmd.
pause
