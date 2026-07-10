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
from dotenv import load_dotenv
import yt_dlp
from yt_dlp.utils import match_filter_func

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Setup logging
logging.basicConfig(level=logging.INFO)

# Initialize dispatcher
dp = Dispatcher()

def format_duration(seconds: int) -> str:
    """Formats duration in seconds to MM:SS or HH:MM:SS."""
    if not seconds:
        return "Unknown"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def search_youtube(query: str):
    """Searches YouTube and returns a list of top 5 videos."""
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'match_filter': match_filter_func('!is_live')
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch5:{query}", download=False)
            results = []
            for entry in info.get('entries', []):
                # Ensure we have a valid ID and title
                if entry.get('id') and entry.get('title'):
                    results.append({
                        'title': entry.get('title'),
                        'id': entry.get('id'),
                        'duration': entry.get('duration')
                    })
            return results
    except Exception as e:
        logging.error(f"Search error: {e}")
        return []

def create_progress_bar(percent: float, length: int = 10) -> str:
    """Creates a visual progress bar like [████░░░░░░]"""
    filled_length = int(length * percent // 100)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"[{bar}] {percent:.1f}%"

def parse_time(time_str: str) -> float:
    """Parses time string (e.g., '1:30', '10:00:00', '45') to seconds."""
    parts = list(map(float, time_str.split(':')))
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]

def download_audio(file_id: str, query: str, start_time: float = None, end_time: float = None, progress_hook=None):
    """
    Downloads audio using yt_dlp and returns the filepath and title.
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

    if progress_hook:
        ydl_opts['progress_hooks'] = [progress_hook]

    if start_time is not None and end_time is not None:
        ydl_opts['external_downloader'] = 'ffmpeg'
        ydl_opts['external_downloader_args'] = {
            'ffmpeg_i': ['-ss', str(start_time), '-to', str(end_time)]
        }

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

            return f"{file_id}.mp3", info.get('title', 'Unknown Title')
    except Exception as e:
        logging.error(f"Error downloading {query}: {e}")
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

    last_update_time = [time.time()]

    def progress_hook(d):
        if d['status'] == 'downloading':
            try:
                # _percent_str can contain ANSI escape codes, so we strip them
                percent_str = re.sub(r'\x1b\[[0-9;]*m', '', d.get('_percent_str', '0.0%'))
                percent_str = percent_str.replace('%', '').strip()
                percent = float(percent_str)

                # Throttle updates to max 1 per 2 seconds to avoid Telegram rate limits
                current_time = time.time()
                if current_time - last_update_time[0] > 2.0:
                    last_update_time[0] = current_time
                    bar = create_progress_bar(percent)
                    # Use run_coroutine_threadsafe since this hook is called from the executor thread
                    asyncio.run_coroutine_threadsafe(
                        msg.edit_text(f"Скачивание: {bar}\nПожалуйста, подождите..."),
                        loop
                    )
            except Exception as e:
                pass # Ignore parsing errors for progress to not interrupt download

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
        logging.error(f"Handler error: {e}")
        await msg.edit_text("Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже.")
    finally:
        # Guarantee removal of all files related to this file_id (e.g. .mp3, .webm, .part)
        for f in glob.glob(f"{file_id}.*"):
            for attempt in range(3):
                try:
                    os.remove(f)
                    break # successfully removed
                except OSError as e:
                    if attempt < 2:
                        await asyncio.sleep(1) # wait for process to release file lock
                    else:
                        logging.error(f"Failed to remove file {f} after 3 attempts: {e}")

@dp.message(F.text)
async def handle_text(message: types.Message):
    text = message.text.strip()

    # Try to extract time range like "10:00-15:30" or "01:00:00-01:05:00" from the end of the string
    time_range_match = re.search(r'\s+([\d:]+)-([\d:]+)$', text)

    start_time = None
    end_time = None
    query = text

    if time_range_match:
        try:
            start_time = parse_time(time_range_match.group(1))
            end_time = parse_time(time_range_match.group(2))
            # Remove the time range part from the query
            query = text[:time_range_match.start()].strip()
        except ValueError:
            pass # fallback to full download if time parsing fails

    query_lower = query.lower()
    is_url = query_lower.startswith('http://') or query_lower.startswith('https://')

    if is_url:
        # Direct URL download
        await process_download(message, query, start_time, end_time)
    else:
        # Text search
        msg = await message.answer("Ищу треки, пожалуйста, подождите...")
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, search_youtube, query)

        if not results:
            await msg.edit_text("Ничего не найдено по вашему запросу. Попробуйте по-другому.")
            return

        buttons = []
        for res in results:
            title = res['title']
            # Limit title length to prevent Telegram API errors
            if len(title) > 40:
                title = title[:37] + "..."
            duration = format_duration(res['duration'])
            btn_text = f"🎵 {title} ({duration})"
            # Use the explicit id from yt-dlp to avoid string splitting bugs
            # Limit id to 20 chars to safely fit within Telegram's 64 byte limit
            video_id = str(res['id'])[:20]
            st_str = str(start_time) if start_time is not None else ""
            et_str = str(end_time) if end_time is not None else ""
            cb_data = f"dl|{video_id}|{st_str}|{et_str}"
            buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await msg.edit_text("Выберите трек из списка ниже:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith('dl|'))
async def handle_download_callback(callback: types.CallbackQuery):
    parts = callback.data.split('|')
    video_id = parts[1]

    start_time = None
    end_time = None

    if len(parts) >= 4:
        if parts[2]:
            start_time = float(parts[2])
        if parts[3]:
            end_time = float(parts[3])

    url = f"https://www.youtube.com/watch?v={video_id}"

    # Acknowledge the callback
    await callback.answer()

    # Update the original message to show progress and remove the keyboard
    await callback.message.edit_text(f"Вы выбрали трек. Начинаю загрузку...", reply_markup=None)

    # Start the download process
    await process_download(callback.message, url, start_time, end_time, is_callback=True)

async def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN is not set in .env file.")
        return

    bot = Bot(token=BOT_TOKEN)
    logging.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
