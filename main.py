import asyncio
import logging
import os
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

# Initialize bot and dispatcher
if BOT_TOKEN:
    bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def download_audio(query: str):
    """
    Downloads audio using yt_dlp and returns the filepath and title.
    """
    file_id = str(uuid.uuid4())
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
    query = message.text
    msg = await message.answer("Ищу и скачиваю музыку, пожалуйста, подождите...")

    loop = asyncio.get_running_loop()
    try:
        filepath, title = await loop.run_in_executor(None, download_audio, query)

        if filepath and os.path.exists(filepath):
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            if file_size_mb > 50:
                await msg.edit_text("Извините, аудио слишком длинное. Лимит Telegram — 50 МБ (около 35 минут).")
            else:
                await msg.delete()
                audio = FSInputFile(filepath)
                await message.answer_audio(audio=audio, caption=title)

            try:
                os.remove(filepath)
            except OSError as e:
                logging.error(f"Error removing file {filepath}: {e}")
        else:
            await msg.edit_text("Не удалось найти или скачать музыку. Попробуйте изменить запрос.")

    except Exception as e:
        logging.error(f"Handler error: {e}")
        await msg.edit_text("Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже.")

async def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN is not set in .env file.")
        return

    logging.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
