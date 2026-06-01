@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

echo ================================================
echo AI text recognition local site
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
        echo Install Python 3.10+ and enable Add Python to PATH.
        pause
        exit /b 1
    )
)

echo Using Python:
%PYTHON_CMD% --version

echo.
echo Installing required packages if needed...
%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Package installation failed.
    pause
    exit /b 1
)

echo.
echo Starting local site...
echo Close this terminal to stop the site.
echo.
%PYTHON_CMD% main.py
pause
