@echo off
cd /d "%~dp0"

echo ==============================================
echo Telegram Bot Setup
echo ==============================================

:: Check for py launcher (bypasses Windows Store python stubs)
py --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=py"
) else (
    set "PYTHON_CMD=python"
)

echo [1/3] Checking virtual environment (venv)...
if not exist "venv" (
    echo Virtual environment not found. Creating...
    %PYTHON_CMD% -m venv venv
    if errorlevel 1 (
        echo Failed to create virtual environment. Please ensure Python is installed.
        pause
        exit /b 1
    )
) else (
    echo Virtual environment already exists.
)

echo [2/3] Upgrading pip...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip

echo [3/3] Installing dependencies from requirements.txt...
if exist "requirements.txt" (
    pip install -r requirements.txt
) else (
    echo requirements.txt not found!
    pause
    exit /b 1
)

echo.
echo Setting up .env file...
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo .env file successfully created from template.
    ) else (
        echo WARNING: .env.example not found. You need to create .env manually.
    )
) else (
    echo .env file already exists.
)

echo.
echo ==============================================
echo Setup completed successfully!
echo You can now run the bot by double-clicking start.bat
echo ==============================================
pause
