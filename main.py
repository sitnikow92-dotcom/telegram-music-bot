import asyncio
import glob
import logging
import os
import re
import uuid
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters.command import Command
from aiogram.types import FSInputFile
from dotenv import load_dotenv
import yt_dlp

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Setup logging
logging.basicConfig(level=logging.INFO)

# Initialize dispatcher
dp = Dispatcher()

def parse_time(time_str: str) -> float:
    """Parses time string (e.g., '1:30', '10:00:00', '45') to seconds."""
    parts = list(map(float, time_str.split(':')))
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]

def download_audio(file_id: str, query: str, start_time: float = None, end_time: float = None):
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
        'default_search': 'ytsearch1'
    }

    if start_time is not None and end_time is not None:
        ydl_opts['external_downloader'] = 'ffmpeg'
        ydl_opts['external_downloader_args'] = {
            'ffmpeg_i': ['-ss', str(start_time), '-to', str(end_time)]
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if not query.startswith('http://') and not query.startswith('https://'):
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

    msg = await message.answer("Ищу и скачиваю музыку, пожалуйста, подождите...")

    loop = asyncio.get_running_loop()
    file_id = str(uuid.uuid4())

    try:
        filepath, title = await loop.run_in_executor(None, download_audio, file_id, query, start_time, end_time)

        if filepath and os.path.exists(filepath):
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            if file_size_mb > 50:
                await msg.edit_text("Извините, аудио слишком длинное. Лимит Telegram — 50 МБ (около 35 минут).")
            else:
                await msg.delete()
                audio = FSInputFile(filepath)
                await message.answer_audio(audio=audio, caption=title)
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

async def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN is not set in .env file.")
        return

    bot = Bot(token=BOT_TOKEN)
    logging.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
