import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask # Додано Flask
from threading import Thread # Додано Thread для одночасного запуску

# --- Веб-сервер Flask ---
# Створюємо екземпляр Flask
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    """Простий маршрут, щоб Render бачив, що сервіс відповідає."""
    return "Telegram bot is running", 200

def run_flask():
    """Запускає Flask-сервер."""
    # Render надає порт через змінну середовища PORT
    # Використовуємо 10000 як стандартний, якщо змінна не встановлена
    port = int(os.environ.get('PORT', 10000))
    # host='0.0.0.0' робить сервер доступним ззовні контейнера Render
    flask_app.run(host='0.0.0.0', port=port)
    logger.info("Flask server stopped.") # Додано логування зупинки Flask

# --- Логіка Telegram Бота ---
# Завантажуємо змінні середовища з файлу .env (для локального запуску, якщо знадобиться)
load_dotenv()

# Налаштування логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Отримуємо токени та ID з середовища
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") # Також завантажимо ключ OpenAI

# Перевірки наявності змінних
if not TELEGRAM_BOT_TOKEN:
    logger.error("Не знайдено TELEGRAM_BOT_TOKEN!")
    exit()
if not OPENAI_API_KEY:
    logger.error("Не знайдено OPENAI_API_KEY!")
    # Можливо, поки що не виходити, якщо транскрипція ще не реалізована?
    # Але краще мати ключ одразу.
    # exit()
if not ADMIN_USER_ID:
    logger.warning("Не знайдено ADMIN_USER_ID! Функції адміністратора не працюватимуть.")
else:
    try:
        ADMIN_USER_ID = int(ADMIN_USER_ID)
    except ValueError:
        logger.error("ADMIN_USER_ID має бути числом!")
        exit()

# Функція-обробник для команди /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє команду /start."""
    user = update.effective_user
    logger.info(f"Користувач {user.id} ({user.username or 'N/A'}) запустив бота.") # Додав обробку відсутності username

    await update.message.reply_html(
        rf"Привіт, {user.mention_html()}! Я бот для транскрибування аудіо. "
        "Зараз я повідомлю адміністратора про ваш запит на доступ."
        # На наступному кроці ми додамо сюди логіку перевірки та сповіщення адміністратора
    )
    # Тут буде логіка сповіщення адміністратора (наступний крок)

def main() -> None:
    """Налаштовує та запускає Flask та Telegram бота."""
    logger.info("Starting main function...") # Додано логування старту main

    # --- Запуск Flask у окремому потоці ---
    # Створюємо потік для Flask
    logger.info("Starting Flask server in a separate thread...")
    flask_thread = Thread(target=run_flask)
    # daemon=True означає, що потік завершиться разом з основним процесом
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("Flask thread started.")

    # --- Налаштування та запуск Telegram бота ---
    logger.info("Setting up Telegram bot application...")
    # Створюємо об'єкт Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Реєструємо обробник команди /start
    application.add_handler(CommandHandler("start", start))

    # Додамо інші обробники тут на наступних кроках...

    # Запускаємо бота в режимі опитування (polling)
    logger.info("Starting Telegram bot polling...")
    application.run_polling()
    logger.info("Telegram bot polling stopped.") # Додано логування зупинки бота

if __name__ == '__main__':
    main()
