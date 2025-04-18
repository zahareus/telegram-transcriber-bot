import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Завантажуємо змінні середовища з файлу .env
load_dotenv()

# Налаштування логування для відстеження подій та помилок
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Отримуємо токени та ID з середовища
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")

if not TELEGRAM_BOT_TOKEN:
    logger.error("Не знайдено TELEGRAM_BOT_TOKEN! Перевірте файл .env або змінні середовища.")
    exit()
if not ADMIN_USER_ID:
    logger.warning("Не знайдено ADMIN_USER_ID! Функції адміністратора не працюватимуть.")
    # Можна продовжити роботу, але краще задати ID адміністратора
else:
    try:
        ADMIN_USER_ID = int(ADMIN_USER_ID) # Перетворюємо ID адміністратора в число
    except ValueError:
        logger.error("ADMIN_USER_ID має бути числом! Перевірте файл .env.")
        exit()

# Функція-обробник для команди /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє команду /start."""
    user = update.effective_user
    logger.info(f"Користувач {user.id} ({user.username}) запустив бота.")

    await update.message.reply_html(
        rf"Привіт, {user.mention_html()}! Я бот для транскрибування аудіо. "
        "Зараз я повідомлю адміністратора про ваш запит на доступ."
        # На наступному кроці ми додамо сюди логіку перевірки та сповіщення адміністратора
    )
    # Тут буде логіка сповіщення адміністратора (наступний крок)

def main() -> None:
    """Запускає бота."""
    # Створюємо об'єкт Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Реєструємо обробник команди /start
    application.add_handler(CommandHandler("start", start))

    # Запускаємо бота в режимі опитування (polling)
    logger.info("Запуск бота...")
    application.run_polling()

if __name__ == '__main__':
    main()
