@echo off
cd /d "%~dp0"

echo ==============================================
echo Starting Telegram Bot
echo ==============================================

:: Check for virtual environment
if not exist "venv\Scripts\activate.bat" (
    echo [CRITICAL ERROR] Environment is not configured!
    echo Please run setup.bat first.
    pause
    exit /b 1
)

:: Check for configuration file
if not exist ".env" (
    echo [WARNING] .env file not found!
    echo If the bot fails to start, make sure to copy .env.example to .env and set your BOT_TOKEN.
    echo.
)

:: Run the bot via the virtual environment
echo Activating environment and running main.py...
call venv\Scripts\activate.bat
python main.py

pause
