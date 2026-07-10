import asyncio
import glob
import logging
import os
import re
import time
import uuid
import subprocess
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters.command import Command
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.session.aiohttp import AiohttpSession
from dotenv import load_dotenv
import yt_dlp
from yt_dlp.utils import match_filter_func

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

def format_duration(seconds: int) -> str:
    """Форматирует длительность в строку формата ММ:СС или ЧЧ:ММ:СС, устойчива к float."""
    if not seconds:
        return "Неизвестно"

    seconds = int(round(float(seconds)))

    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def search_music(query: str):
    """Ищет треки на нескольких платформах с использованием прокси."""
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'proxy': PROXY_URL,
    }
    results = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_yt = ydl.extract_info(f"ytsearch3:{query}", download=False)
            for entry in info_yt.get('entries', []):
                if entry.get('url') or entry.get('id'):
                    url = entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
                    results.append({
                        'title': f"[YT] {entry.get('title')}",
                        'url': url,
                        'duration': entry.get('duration')
                    })

            try:
                info_sc = ydl.extract_info(f"scsearch2:{query}", download=False)
                for entry in info_sc.get('entries', []):
                    if entry.get('url'):
                        results.append({
                            'title': f"[SC] {entry.get('title')}",
                            'url': entry.get('url'),
                            'duration': entry.get('duration')
                        })
            except Exception:
                pass

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
    """Скачивает аудиопоток в максимальном качестве с использованием файла куков cookies.txt."""

    if "youtube.com/watch" in query:
        video_id_match = re.search(r'(v=[^&]+)', query)
        if video_id_match:
            query = f"https://www.youtube.com/watch?{video_id_match.group(1)}"

    full_audio_mp3 = f"{file_id}_full.mp3"
    final_cut_mp3 = f"{file_id}.mp3"

    ydl_opts = {
        'format': 'bestaudio/best',
        'extract_flat': False,
        'outtmpl': f'{file_id}_full.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch1',
        'match_filter': match_filter_func('!is_live'),
        'proxy': PROXY_URL,
    }

    # Если текстовый файл с куками лежит в папке бота — цепляем его
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = "cookies.txt"
        logging.info("Используем текстовый файл cookies.txt для авторизации YouTube.")

    if progress_hook:
        ydl_opts['progress_hooks'] = [progress_hook]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            query_lower = query.lower()
            if not query_lower.startswith('http://') and not query_lower.startswith('https://'):
                search_query = f"ytsearch1:{query}"
            else:
                search_query = query

            info = ydl.extract_info(search_query, download=True)
            if 'entries' in info:
                info = info['entries'][0]

            # Локальная быстрая обрезка файла силами ffmpeg ПОСЛЕ загрузки
            if start_time is not None and end_time is not None:
                logging.info(f"Локальная обрезка ffmpeg: c {start_time} до {end_time}")

                cmd = [
                    'ffmpeg', '-y',
                    '-ss', str(start_time),
                    '-to', str(end_time),
                    '-i', full_audio_mp3,
                    '-acodec', 'copy',
                    final_cut_mp3
                ]

                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                if os.path.exists(full_audio_mp3):
                    os.remove(full_audio_mp3)

                return final_cut_mp3, info.get('title', 'Неизвестный трек')

            if os.path.exists(full_audio_mp3):
                os.rename(full_audio_mp3, final_cut_mp3)

            return final_cut_mp3, info.get('title', 'Неизвестный трек')

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
    msg = await message.answer("Ищу и скачиваю музыку, please wait...")

    loop = asyncio.get_running_loop()
    file_id = str(uuid.uuid4())
    last_update_time = [time.time()]

    def progress_hook(d):
        if d['status'] == 'downloading':
            try:
                percent_str = re.sub(r'\x1b\[[0-9;]*m', '', d.get('_percent_str', '0.0%'))
                percent_str = percent_str.replace('%', '').strip()
                percent = float(percent_str)

                current_time = time.time()
                if current_time - last_update_time[0] > 2.0:
                    last_update_time[0] = current_time
                    bar = create_progress_bar(percent)
                    asyncio.run_coroutine_threadsafe(
                        msg.edit_text(f"Скачивание: {bar}\nПожалуйста, подождите..."),
                        loop
                    )
            except Exception:
                pass

    try:
        filepath, title = await loop.run_in_executor(None, download_audio, file_id, query, start_time, end_time, progress_hook)

        if filepath and os.path.exists(filepath):
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            if file_size_mb > 50:
                await msg.edit_text("Извините, аудио слишком длинное. Лимит Telegram — 50 МБ (около 35 минут).")
            else:
                await msg.delete()
                await message.bot.send_chat_action(chat_id=message.chat.id, action="upload_document")
                audio = FSInputFile(filepath)
                await message.bot.send_audio(chat_id=message.chat.id, audio=audio, caption=title)
        else:
            await msg.edit_text("Не удалось найти или скачать музыку. Попробуйте изменить запрос.")

    except Exception as e:
        logging.error(f"Ошибка в обработчике скачивания: {e}")
        await msg.edit_text("Произошла непредвиденная ошибка.")
    finally:
        for f in glob.glob(f"{file_id}*"):
            for attempt in range(3):
                try:
                    os.remove(f)
                    break
                except OSError:
                    if attempt < 2:
                        await asyncio.sleep(1)

@dp.message(F.text)
async def handle_text(message: types.Message):
    text = message.text.strip()

    query_lower = text.lower()
    is_url = query_lower.startswith('http://') or query_lower.startswith('https://')

    if is_url:
        time_range_match = re.search(r'\s+([\d:]+)-([\d:]+)$', text)
        start_time = None
        end_time = None
        query = text

        if time_range_match:
            try:
                start_time = parse_time(time_range_match.group(1))
                end_time = parse_time(time_range_match.group(2))
                query = text[:time_range_match.start()].strip()
            except ValueError:
                pass

        await process_download(message, query, start_time, end_time)
    else:
        time_range_match = re.search(r'\s+([\d:]+)-([\d:]+)$', text)
        start_time = None
        end_time = None
        query = text

        if time_range_match:
            try:
                start_time = parse_time(time_range_match.group(1))
                end_time = parse_time(time_range_match.group(2))
                query = text[:time_range_match.start()].strip()
            except ValueError:
                pass

        msg = await message.answer("Ищу треки, please wait...")
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, search_music, query)

        if not results:
            await msg.edit_text("Ничего не найдено по вашему запросу.")
            return

        buttons = []
        for res in results:
            title = res['title']
            if len(title) > 40:
                title = title[:37] + "..."
            duration = format_duration(res['duration'])
            btn_text = f"🎵 {title} ({duration})"

            short_id = str(uuid.uuid4())[:8]
            SEARCH_CACHE[short_id] = res['url']

            st_str = str(start_time) if start_time is not None else ""
            et_str = str(end_time) if end_time is not None else ""

            cb_data = f"dl|{short_id}|{st_str}|{et_str}"
            buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await msg.edit_text("Выберите трек из списка ниже:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith('dl|'))
async def handle_download_callback(callback: types.CallbackQuery):
    parts = callback.data.split('|')
    short_id = parts[1]

    url = SEARCH_CACHE.get(short_id)
    if not url:
        await callback.answer("Ошибка: ссылка устарела.", show_alert=True)
        return

    start_time = None
    end_time = None

    if len(parts) >= 4:
        if parts[2]:
            start_time = float(parts[2])
        if parts[3]:
            end_time = float(parts[3])

    await callback.answer()
    await callback.message.edit_text(f"Вы выбрали трек. Начинаю загрузку...", reply_markup=None)
    await process_download(callback.message, url, start_time, end_time, is_callback=True)

async def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN is not set in .env file.")
        return

    if PROXY_URL:
        logging.info(f"Инициализируем сессию через прокси из .env: {PROXY_URL}")
        try:
            from aiohttp_socks import ProxyConnector
            import aiohttp

            # В aiogram 3.x AiohttpSession не принимает connector в __init__.
            # Нам нужно создать свой класс сессии, переопределив create_session.
            class ProxyAiohttpSession(AiohttpSession):
                async def create_session(self) -> aiohttp.ClientSession:
                    if getattr(self, "_session", None) is None or self._session.closed:
                        connector = ProxyConnector.from_url(PROXY_URL)
                        self._session = aiohttp.ClientSession(connector=connector)
                    return self._session

            session = ProxyAiohttpSession()
            bot = Bot(token=BOT_TOKEN, session=session)
        except ImportError:
            logging.warning("aiohttp_socks не установлен, пробуем использовать стандартный AiohttpSession.")
            session = AiohttpSession(proxy=PROXY_URL)
            bot = Bot(token=BOT_TOKEN, session=session)
    else:
        logging.info("Запуск без прокси...")
        bot = Bot(token=BOT_TOKEN)

    logging.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
