@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================
echo Установка и настройка окружения для Telegram-бота
echo ==============================================

:: Проверка наличия системного лаунчера py (помогает обойти заглушки Microsoft Store)
py --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=py"
) else (
    set "PYTHON_CMD=python"
)

echo [1/3] Проверка виртуального окружения (venv)...
if not exist "venv" (
    echo Виртуальное окружение не найдено. Создаем...
    %PYTHON_CMD% -m venv venv
    if errorlevel 1 (
        echo Ошибка при создании виртуального окружения. Убедитесь, что Python установлен.
        pause
        exit /b 1
    )
) else (
    echo Виртуальное окружение уже существует.
)

echo [2/3] Обновление менеджера пакетов pip...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip

echo [3/3] Установка зависимостей из requirements.txt...
if exist "requirements.txt" (
    pip install -r requirements.txt
) else (
    echo Файл requirements.txt не найден!
    pause
    exit /b 1
)

echo.
echo ==============================================
echo Настройка завершена успешно!
echo Теперь вы можете запустить бота двойным кликом по start.bat
echo ==============================================
pause
