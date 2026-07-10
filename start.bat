@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================
echo Запуск Telegram-бота
echo ==============================================

:: Проверка наличия виртуального окружения
if not exist "venv\Scripts\activate.bat" (
    echo [КРИТИЧЕСКАЯ ОШИБКА] Окружение не настроено!
    echo Пожалуйста, сначала запустите файл setup.bat
    pause
    exit /b 1
)

:: Проверка конфигурационного файла
if not exist ".env" (
    echo [ВНИМАНИЕ] Файл .env не найден!
    echo Если бот не запустится, скопируйте .env.example в .env и укажите свой BOT_TOKEN.
    echo.
)

:: Запуск бота через виртуальное окружение
echo Активация окружения и запуск main.py...
call venv\Scripts\activate.bat
python main.py

pause
