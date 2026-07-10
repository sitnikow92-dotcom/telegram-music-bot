import asyncio
import glob
import logging
import os
import re
import time
import uuid
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters.command import Command
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.session.aiohttp import AiohttpSession
from dotenv import load_dotenv
import yt_dlp
from yt_dlp.utils import match_filter_func, download_range_func

# Загрузка переменных окружения из файла .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
PROXY_URL = os.getenv("PROXY_URL")

# Настройка логирования для отслеживания ошибок и статусов
logging.basicConfig(level=logging.INFO)

# Инициализация диспетчера для обработки входящих сообщений
dp = Dispatcher()

# Глобальный словарь для кэширования длинных URL (обход лимита 64 байта в callback_data)
SEARCH_CACHE = {}

def format_duration(seconds) -> str:
    """Форматирует длительность в секундах в строку формата ММ:СС или ЧЧ:ММ:СС."""
    if not seconds:
        return "Неизвестно"
    # Приводим к int, так как SoundCloud может возвращать float, а :02d требует целых чисел.
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def search_music(query: str):
    """Ищет треки на нескольких платформах (YT + SoundCloud) и объединяет результаты."""
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
    }
    if PROXY_URL:
        ydl_opts['proxy'] = PROXY_URL
    results = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 1. Ищем 3 трека на YouTube
            info_yt = ydl.extract_info(f"ytsearch3:{query}", download=False)
            for entry in info_yt.get('entries', []):
                if entry.get('url') or entry.get('id'):
                    url = entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
                    results.append({
                        'title': f"[YT] {entry.get('title')}",
                        'url': url,
                        'duration': entry.get('duration')
                    })

            # 2. Ищем 2 трека в SoundCloud
            info_sc = ydl.extract_info(f"scsearch2:{query}", download=False)
            for entry in info_sc.get('entries', []):
                if entry.get('url'):
                    results.append({
                        'title': f"[SC] {entry.get('title')}",
                        'url': entry.get('url'),
                        'duration': entry.get('duration')
                    })
            return results
    except Exception as e:
        logging.error(f"Ошибка мульти-поиска: {e}")
        return []

def create_progress_bar(percent: float, length: int = 10) -> str:
    """Создает визуальный прогресс-бар в виде [████░░░░░░]"""
    filled_length = int(length * percent // 100)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"[{bar}] {percent:.1f}%"

def parse_time(time_str: str) -> float:
    """Парсит строку времени (например, '1:30', '10:00:00', '45') и переводит в секунды."""
    parts = list(map(float, time_str.split(':')))
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]

def download_audio(file_id: str, query: str, start_time: float = None, end_time: float = None, progress_hook=None):
    """
    Скачивает аудио с помощью yt_dlp и возвращает путь к сохраненному файлу и название.
    """
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': f'{file_id}.%(ext)s',
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch1',
        'match_filter': match_filter_func('!is_live')
    }
    if PROXY_URL:
        ydl_opts['proxy'] = PROXY_URL

    if progress_hook:
        ydl_opts['progress_hooks'] = [progress_hook] # Добавляем функцию для перехвата прогресса загрузки

    if start_time is not None and end_time is not None:
        # Используем download_range_func для скачивания только нужного фрагмента,
        # что экономит трафик и место, избегая скачивания всего видео целиком.
        ydl_opts['download_ranges'] = download_range_func(None, [(start_time, end_time)])

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            query_lower = query.lower()
            # Если запрос не является прямой ссылкой, формируем запрос для поиска на YouTube (ytsearch1)
            if not query_lower.startswith('http://') and not query_lower.startswith('https://'):
                search_query = f"ytsearch1:{query}"
            else:
                search_query = query

            info = ydl.extract_info(search_query, download=True)

            # Если вернулся список (плейлист или результаты поиска), берем первый элемент
            if 'entries' in info:
                info = info['entries'][0]

            return f"{file_id}.mp3", info.get('title', 'Неизвестный трек')
    except Exception as e:
        logging.error(f"Ошибка при скачивании {query}: {e}")
        return None, None

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот для поиска и скачивания музыки.\n"
        "Отправь мне название песни или ссылку на YouTube, и я пришлю тебе аудио."
    )

async def process_download(message: types.Message, query: str, start_time: float = None, end_time: float = None, is_callback: bool = False):
    msg = await message.answer("Ищу и скачиваю музыку, пожалуйста, подождите...")

    loop = asyncio.get_running_loop()
    file_id = str(uuid.uuid4())

    # Храним время последнего обновления в списке (чтобы изменять его внутри вложенной функции)
    last_update_time = [time.time()]

    def progress_hook(d):
        """Хук, который вызывается во время скачивания для обновления прогресс-бара."""
        if d['status'] == 'downloading':
            try:
                # В _percent_str могут быть ANSI escape-коды для цвета, очищаем их регуляркой
                percent_str = re.sub(r'\x1b\[[0-9;]*m', '', d.get('_percent_str', '0.0%'))
                percent_str = percent_str.replace('%', '').strip()
                percent = float(percent_str)

                # Троттлинг (ограничение частоты): обновляем сообщение не чаще 1 раза в 2 секунды,
                # чтобы Telegram API не заблокировал бота за флуд.
                current_time = time.time()
                if current_time - last_update_time[0] > 2.0:
                    last_update_time[0] = current_time
                    bar = create_progress_bar(percent)
                    # Используем run_coroutine_threadsafe, так как этот хук вызывается из синхронного потока (executor thread),
                    # а редактирование сообщения должно произойти в главном асинхронном цикле.
                    asyncio.run_coroutine_threadsafe(
                        msg.edit_text(f"Скачивание: {bar}\nПожалуйста, подождите..."),
                        loop
                    )
            except Exception as e:
                pass # Игнорируем ошибки парсинга прогресса, чтобы не прерывать само скачивание

    try:
        # Запускаем синхронную функцию скачивания в отдельном потоке (executor),
        # чтобы бот не "зависал" для других пользователей на время загрузки.
        filepath, title = await loop.run_in_executor(None, download_audio, file_id, query, start_time, end_time, progress_hook)

        if filepath and os.path.exists(filepath):
            # Проверяем размер файла (в мегабайтах) перед отправкой
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            if file_size_mb > 50:
                await msg.edit_text("Извините, аудио слишком длинное. Лимит Telegram — 50 МБ (около 35 минут).")
            else:
                await msg.delete()
                # Отправляем действие "Отправка аудио" (показывается в статусе набора текста)
                await message.bot.send_chat_action(chat_id=message.chat.id, action="upload_document")
                audio = FSInputFile(filepath)
                await message.bot.send_audio(chat_id=message.chat.id, audio=audio, caption=title)
        else:
            await msg.edit_text("Не удалось найти или скачать музыку. Попробуйте изменить запрос.")

    except Exception as e:
        logging.error(f"Ошибка в обработчике скачивания: {e}")
        await msg.edit_text("Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже.")
    finally:
        # Гарантированное удаление всех временных файлов, связанных с этим file_id (например, .mp3, .webm, .part)
        for f in glob.glob(f"{file_id}.*"):
            for attempt in range(3):
                try:
                    os.remove(f)
                    break # Файл успешно удален
                except OSError as e:
                    if attempt < 2:
                        # Если файл заблокирован (например, Windows PermissionError из-за yt-dlp),
                        # ждем секунду и пробуем снова.
                        await asyncio.sleep(1)
                    else:
                        logging.error(f"Не удалось удалить файл {f} после 3 попыток: {e}")

@dp.message(F.text)
async def handle_text(message: types.Message):
    text = message.text.strip()

    # Пытаемся извлечь временной интервал, например "10:00-15:30" или "01:00:00-01:05:00" в конце строки
    time_range_match = re.search(r'\s+([\d:]+)-([\d:]+)$', text)

    start_time = None
    end_time = None
    query = text

    if time_range_match:
        try:
            start_time = parse_time(time_range_match.group(1))
            end_time = parse_time(time_range_match.group(2))
            # Удаляем часть с таймкодом из поискового запроса
            query = text[:time_range_match.start()].strip()
        except ValueError:
            pass # Если не удалось распарсить время, просто скачиваем видео целиком

    query_lower = query.lower()
    is_url = query_lower.startswith('http://') or query_lower.startswith('https://')

    if is_url:
        # Скачиваем напрямую, если отправлена прямая ссылка
        await process_download(message, query, start_time, end_time)
    else:
        # Если это текст — ищем треки на мульти-платформах
        msg = await message.answer("Ищу треки, пожалуйста, подождите...")
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, search_music, query)

        if not results:
            await msg.edit_text("Ничего не найдено по вашему запросу. Попробуйте по-другому.")
            return

        buttons = []
        for res in results:
            title = res['title']
            # Обрезаем название, чтобы избежать ошибок Telegram API из-за слишком длинных кнопок
            if len(title) > 40:
                title = title[:37] + "..."
            duration = format_duration(res['duration'])
            btn_text = f"🎵 {title} ({duration})"

            # Генерируем короткий ID для кэша (8 символов)
            short_id = str(uuid.uuid4())[:8]
            # Сохраняем реальную ссылку (любой платформы) в память бота
            SEARCH_CACHE[short_id] = res['url']

            st_str = str(start_time) if start_time is not None else ""
            et_str = str(end_time) if end_time is not None else ""

            # В callback передаем только short_id. Теперь мы на 100% вписываемся в лимиты!
            cb_data = f"dl|{short_id}|{st_str}|{et_str}"
            buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await msg.edit_text("Выберите трек из списка ниже:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith('dl|'))
async def handle_download_callback(callback: types.CallbackQuery):
    # Разбираем данные, пришедшие с нажатой кнопки
    parts = callback.data.split('|')
    short_id = parts[1]

    # Достаем ссылку любой платформы из памяти
    url = SEARCH_CACHE.get(short_id)
    if not url:
        await callback.answer("Ошибка: ссылка устарела или бот был перезагружен.", show_alert=True)
        return

    start_time = None
    end_time = None

    # Пытаемся восстановить таймкоды, если они были сохранены в кнопке
    if len(parts) >= 4:
        if parts[2]:
            start_time = float(parts[2])
        if parts[3]:
            end_time = float(parts[3])

    # Подтверждаем получение callback_query, чтобы у пользователя пропали "часики" на кнопке
    await callback.answer()

    # Обновляем оригинальное сообщение, убираем клавиатуру и показываем текст загрузки
    await callback.message.edit_text(f"Вы выбрали трек. Начинаю загрузку...", reply_markup=None)

    # Запускаем основной процесс скачивания
    await process_download(callback.message, url, start_time, end_time, is_callback=True)

async def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN is not set in .env file.")
        return

    # Если в .env прописан прокси, используем его, иначе запускаем напрямую
    # Если в .env прописан прокси, инициализируем сессию aiogram
    if PROXY_URL:
        logging.info(f"Инициализируем сессию через прокси из .env: {PROXY_URL}")
        # aiogram версии 3.x нативно поддерживает aiohttp_socks, достаточно просто передать proxy=
        session = AiohttpSession(proxy=PROXY_URL)
        bot = Bot(token=BOT_TOKEN, session=session)
    else:
        logging.info("Запуск без прокси...")
        bot = Bot(token=BOT_TOKEN)

    logging.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
