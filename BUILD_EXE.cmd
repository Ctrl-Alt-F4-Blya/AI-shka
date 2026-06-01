@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

where python >nul 2>nul
if %errorlevel%==0 (set "PYTHON_CMD=python") else (set "PYTHON_CMD=py")

%PYTHON_CMD% -m pip install -r requirements.txt pyinstaller
if errorlevel 1 pause & exit /b 1

%PYTHON_CMD% -m PyInstaller --noconfirm --clean --onefile --name AI_Text_Recognition_Local --add-data "static;static" --add-data "samples;samples" main.py
if errorlevel 1 pause & exit /b 1

echo.
echo EXE created: dist\AI_Text_Recognition_Local.exe
pause
