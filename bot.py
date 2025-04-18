import logging
import os
import json
import tempfile
import openai
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
from flask import Flask
from threading import Thread

# --- Веб-сервер Flask ---
flask_app = Flask(__name__)
@flask_app.route('/')
def health_check(): return "Telegram bot is running", 200
def run_flask():
    port = int(os.environ.get('PORT', 10000))
    flask_app.run(host='0.0.0.0', port=port)
    logger.info("Flask server stopped.")

# --- Логіка Telegram Бота ---
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Завантаження конфігурації ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_BOT_TOKEN: logger.error("Не знайдено TELEGRAM_BOT_TOKEN!"); exit()
if not OPENAI_API_KEY: logger.warning("Не знайдено OPENAI_API_KEY! Транскрипція не працюватиме.")
if not ADMIN_USER_ID: logger.error("Не знайдено ADMIN_USER_ID!"); exit()
try:
    ADMIN_USER_ID = int(ADMIN_USER_ID)
except ValueError:
    logger.error("ADMIN_USER_ID має бути числом!"); exit()

# --- Ініціалізація клієнта OpenAI ---
try:
    openai.api_key = OPENAI_API_KEY
    logger.info("Клієнт OpenAI успішно ініціалізовано.")
except Exception as e:
    logger.error(f"Помилка ініціалізації OpenAI: {e}")
    # exit()

# --- Керування користувачами ---
user_status = {}
# TODO: Завантажувати/зберігати цей словник у файл

def get_admin_keyboard(user_id_to_manage: int) -> InlineKeyboardMarkup:
    keyboard = [[
        InlineKeyboardButton("✅ Схвалити", callback_data=f"approve_{user_id_to_manage}"),
        InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_{user_id_to_manage}"),
    ]]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user; user_id = user.id
    username = user.username or "N/A"; first_name = user.first_name or ""; last_name = user.last_name or ""; full_name = f"{first_name} {last_name}".strip()
    logger.info(f"Користувач {user_id} ({username}, {full_name}) запустив /start.")
    status = user_status.get(user_id)

    if status == "approved": await update.message.reply_text("Ви вже маєте доступ. Надсилайте голосове повідомлення або аудіофайл (mp3, mp4, ogg).")
    elif status == "rejected": await update.message.reply_text("На жаль, ваш запит на доступ було відхилено.")
    elif status == "pending": await update.message.reply_text("Ваш запит на доступ вже надіслано адміністратору. Будь ласка, зачекайте.")
    else:
        logger.info(f"Новий користувач {user_id}. Надсилаємо запит адміністратору {ADMIN_USER_ID}.")
        user_status[user_id] = "pending"
        await update.message.reply_html(rf"Привіт, {user.mention_html()}! Ваш запит на доступ до бота надіслано адміністратору...")
        try:
            admin_message = (f"🔔 Новий запит на доступ!\n\nІм'я: {full_name}\nUsername: @{username}\nUser ID: `{user_id}`\n\nНадати доступ?")
            keyboard = get_admin_keyboard(user_id)
            await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_message, reply_markup=keyboard, parse_mode='Markdown')
            logger.info(f"Повідомлення адміністратору про {user_id} надіслано.")
        except Exception as e:
            logger.error(f"Не вдалося надіслати повідомлення адміністратору ({ADMIN_USER_ID}): {e}")
            await update.message.reply_text("Виникла помилка при надсиланні запиту адміністратору.")
            if user_id in user_status: del user_status[user_id]

async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; await query.answer(); admin_user = query.from_user
    if admin_user.id != ADMIN_USER_ID: return
    action, user_id_str = query.data.split('_', 1)
    try: user_id_to_manage = int(user_id_str)
    except ValueError: logger.error(f"Неправильний user_id: {query.data}"); return
    original_message = query.message.text; user_info_msg = ""

    if action == "approve":
        logger.info(f"Адміністратор {admin_user.id} схвалив {user_id_to_manage}.")
        user_status[user_id_to_manage] = "approved"; await query.edit_message_text(text=f"{original_message}\n\n✅ Доступ надано `{user_id_to_manage}`.", parse_mode='Markdown')
        user_info_msg = "🎉 Ваш запит на доступ схвалено! Надсилайте аудіо."
    elif action == "reject":
        logger.info(f"Адміністратор {admin_user.id} відхилив {user_id_to_manage}.")
        user_status[user_id_to_manage] = "rejected"; await query.edit_message_text(text=f"{original_message}\n\n❌ Доступ відхилено `{user_id_to_manage}`.", parse_mode='Markdown')
        user_info_msg = "😔 На жаль, ваш запит на доступ відхилено."
    if user_info_msg:
        try: await context.bot.send_message(chat_id=user_id_to_manage, text=user_info_msg)
        except Exception as e: logger.error(f"Не вдалося надіслати повідомлення {user_id_to_manage} ({action}): {e}")

# --- Обробка аудіо ---
MAX_FILE_SIZE_MB = 25
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user; user_id = user.id
    if user_status.get(user_id) != "approved":
        logger.warning(f"Спроба доступу неавторизованим користувачем {user_id}.")
        await update.message.reply_text("У вас немає доступу для використання цієї функції.")
        return

    file_id = None; file_size = None; file_unique_id = None; message = update.message
    if message.voice: file_id, file_size, file_unique_id = message.voice.file_id, message.voice.file_size, message.voice.file_unique_id; logger.info(f"Voice from {user_id} (id: {file_id}, size: {file_size})")
    elif message.audio: file_id, file_size, file_unique_id = message.audio.file_id, message.audio.file_size, message.audio.file_unique_id; logger.info(f"Audio from {user_id} (id: {file_id}, size: {file_size}, name: {message.audio.file_name})")
    elif message.document and message.document.mime_type in ('audio/mpeg', 'audio/ogg', 'video/mp4', 'audio/mp4', 'audio/x-m4a'): # Додано m4a, audio/mp4
        file_id, file_size, file_unique_id = message.document.file_id, message.document.file_size, message.document.file_unique_id; logger.info(f"Document ({message.document.mime_type}) from {user_id} (id: {file_id}, size: {file_size}, name: {message.document.file_name})")

    if not file_id: return
    if file_size and file_size > MAX_FILE_SIZE_BYTES:
        logger.warning(f"File too large from {user_id}: {file_size}")
        await message.reply_text(f"❌ Файл занадто великий ({file_size / 1024 / 1024:.1f} MB). Макс: {MAX_FILE_SIZE_MB} MB.")
        return

    processing_msg = await message.reply_text("⏳ Отримав, починаю розшифровку...")
    try: file_data = await context.bot.get_file(file_id)
    except Exception as e: logger.error(f"Failed to get file info {file_id} from {user_id}: {e}"); await processing_msg.edit_text("❌ Не вдалося завантажити файл."); return

    file_extension = ".tmp" # Default extension
    try:
        if message.voice: file_extension = ".oga"
        elif message.audio and message.audio.file_name: file_extension = os.path.splitext(message.audio.file_name)[1]
        elif message.document and message.document.file_name: file_extension = os.path.splitext(message.document.file_name)[1]
        if not file_extension or len(file_extension) > 5: # Basic sanity check for extension
             file_extension = ".audio" # Fallback if no/weird extension
    except Exception as e:
        logger.warning(f"Could not determine file extension: {e}")
        file_extension = ".audio"

    with tempfile.NamedTemporaryFile(suffix=file_extension, delete=True) as temp_file:
        try:
            await file_data.download_to_drive(temp_file.name)
            logger.info(f"File {file_unique_id} from {user_id} downloaded to {temp_file.name}")
        except Exception as e:
            logger.error(f"Error downloading file {file_unique_id} to {temp_file.name}: {e}")
            await processing_msg.edit_text("❌ Помилка під час завантаження файлу.")
            return

        try:
            logger.info(f"Sending file {temp_file.name} to OpenAI Whisper API (language: uk)...")
            with open(temp_file.name, "rb") as audio_file_handle:
                transcription_response = openai.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file_handle,
                    language="uk" # <--- ОСЬ ТУТ ВКАЗУЄМО УКРАЇНСЬКУ МОВУ
                )
            transcript_text = transcription_response.text
            logger.info(f"Transcription received for {file_unique_id} from {user_id}.")

            if transcript_text:
                max_length = 4000
                full_response_prefix = "Розшифровка:\n" # Додаємо префікс
                await message.reply_text(full_response_prefix + transcript_text[:max_length-len(full_response_prefix)]) # Відправляємо першу частину з префіксом
                # Якщо текст довший, відправляємо решту без префікса
                for i in range(max_length-len(full_response_prefix), len(transcript_text), max_length):
                     chunk = transcript_text[i:i+max_length]
                     if chunk: # Перевірка, що частина не порожня
                         await message.reply_text(chunk)
                await processing_msg.delete()
            else:
                logger.warning(f"Empty transcription for {file_unique_id} from {user_id}.")
                await processing_msg.edit_text("ℹ️ Не вдалося розпізнати текст в аудіо.")

        except openai.APIError as e:
            logger.error(f"OpenAI API error for {file_unique_id}: {e}")
            error_message = f"❌ Помилка OpenAI API: {e.body.get('message', 'Невідома помилка') if e.body else 'Невідома помилка'}"
            await processing_msg.edit_text(error_message)
        except Exception as e:
            logger.exception(f"General error during transcription of {file_unique_id}") # Використовуємо exception для повного стеку
            await processing_msg.edit_text("❌ Сталася неочікувана помилка під час обробки.")

# --- Головна функція ---
def main() -> None:
    logger.info("Starting main function...")
    # load_user_data()
    logger.info("Starting Flask server..."); flask_thread = Thread(target=run_flask); flask_thread.daemon = True; flask_thread.start(); logger.info("Flask thread started.")
    logger.info("Setting up Telegram bot application...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_admin_callback, pattern='^(approve|reject)_'))
    # Додано більше MIME-типів у фільтр
    audio_handlers = MessageHandler(
        filters.VOICE | filters.AUDIO | filters.Document.FileExtension("mp3") | filters.Document.FileExtension("ogg") | filters.Document.FileExtension("mp4") | filters.Document.FileExtension("m4a") | filters.Document.MimeType("audio/ogg") | filters.Document.MimeType("audio/mp4"),
        handle_audio
    )
    application.add_handler(audio_handlers)

    logger.info("Starting Telegram bot polling...")
    application.run_polling()
    # save_user_data()
    logger.info("Telegram bot polling stopped.")

if __name__ == '__main__':
    main()
