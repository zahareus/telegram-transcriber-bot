import logging
import os
import json # Додано для майбутнього збереження/завантаження даних
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup # Додано кнопки
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler # Додано обробник кнопок
from flask import Flask
from threading import Thread

# --- Веб-сервер Flask ---
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return "Telegram bot is running", 200

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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Перевірки змінних (залишаємо як є)
if not TELEGRAM_BOT_TOKEN: logger.error("Не знайдено TELEGRAM_BOT_TOKEN!"); exit()
if not OPENAI_API_KEY: logger.warning("Не знайдено OPENAI_API_KEY! Транскрипція не працюватиме.") # Змінено на warning
if not ADMIN_USER_ID: logger.error("Не знайдено ADMIN_USER_ID!"); exit()
try:
    ADMIN_USER_ID = int(ADMIN_USER_ID)
except ValueError:
    logger.error("ADMIN_USER_ID має бути числом!"); exit()

# --- Керування користувачами ---
# Словник для зберігання статусів користувачів (user_id: status)
# status: "approved", "pending", "rejected"
# TODO: Завантажувати/зберігати цей словник у файл
user_status = {}

# Функція для побудови клавіатури адміністратора
def get_admin_keyboard(user_id_to_manage: int) -> InlineKeyboardMarkup:
    """Створює клавіатуру з кнопками Схвалити/Відхилити."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Схвалити", callback_data=f"approve_{user_id_to_manage}"),
            InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_{user_id_to_manage}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# Оновлена функція-обробник для команди /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє команду /start, перевіряє статус користувача та надсилає запит адміну."""
    user = update.effective_user
    user_id = user.id
    username = user.username or "N/A"
    first_name = user.first_name or ""
    last_name = user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()

    logger.info(f"Користувач {user_id} ({username}, {full_name}) запустив /start.")

    # Перевіряємо статус користувача
    status = user_status.get(user_id)

    if status == "approved":
        logger.info(f"Користувач {user_id} вже схвалений.")
        await update.message.reply_text("Ви вже маєте доступ. Можете надсилати аудіо для транскрипції.")
        # Тут можна додати інструкції, як надсилати аудіо
    elif status == "rejected":
        logger.info(f"Користувач {user_id} раніше був відхилений.")
        await update.message.reply_text("На жаль, ваш запит на доступ було відхилено.")
    elif status == "pending":
        logger.info(f"Користувач {user_id} вже очікує на схвалення.")
        await update.message.reply_text("Ваш запит на доступ вже надіслано адміністратору. Будь ласка, зачекайте.")
    else: # Новий користувач
        logger.info(f"Новий користувач {user_id}. Надсилаємо запит адміністратору {ADMIN_USER_ID}.")
        user_status[user_id] = "pending" # Позначаємо як очікуючого

        await update.message.reply_html(
            rf"Привіт, {user.mention_html()}! Ваш запит на доступ до бота надіслано адміністратору. "
            "Ви отримаєте сповіщення, як тільки його розглянуть."
        )

        # Надсилаємо повідомлення адміністратору
        try:
            admin_message = (
                f"🔔 Новий запит на доступ!\n\n"
                f"Ім'я: {full_name}\n"
                f"Username: @{username}\n"
                f"User ID: `{user_id}`\n\n"
                f"Надати доступ?"
            )
            keyboard = get_admin_keyboard(user_id)
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=admin_message,
                reply_markup=keyboard,
                parse_mode='Markdown' # Використовуємо Markdown для форматування ID
            )
            logger.info(f"Повідомлення адміністратору про {user_id} надіслано.")
        except Exception as e:
            logger.error(f"Не вдалося надіслати повідомлення адміністратору ({ADMIN_USER_ID}): {e}")
            # Можливо, варто повідомити користувача про проблему?
            await update.message.reply_text("Виникла помилка при надсиланні запиту адміністратору. Спробуйте пізніше.")
            del user_status[user_id] # Видаляємо статус, якщо не вдалося повідомити адміна

# Функція-обробник для натискання кнопок адміністратором
async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє натискання кнопок Схвалити/Відхилити."""
    query = update.callback_query
    await query.answer() # Важливо відповісти на запит, щоб кнопка перестала "крутитися"

    admin_user = query.from_user
    if admin_user.id != ADMIN_USER_ID:
        logger.warning(f"Спроба використання адмін-кнопки користувачем {admin_user.id}!")
        await query.edit_message_text(text="Помилка: Ви не адміністратор.")
        return

    # Розбираємо дані з кнопки (наприклад, "approve_123456789")
    action, user_id_str = query.data.split('_', 1)
    try:
        user_id_to_manage = int(user_id_str)
    except ValueError:
        logger.error(f"Неправильний user_id у callback_data: {query.data}")
        await query.edit_message_text(text="Помилка: Некоректні дані.")
        return

    original_message = query.message.text # Зберігаємо оригінальний текст повідомлення

    if action == "approve":
        logger.info(f"Адміністратор {admin_user.id} схвалив користувача {user_id_to_manage}.")
        user_status[user_id_to_manage] = "approved"
        await query.edit_message_text(text=f"{original_message}\n\n✅ Доступ надано користувачу `{user_id_to_manage}`.", parse_mode='Markdown')
        # Повідомляємо користувача
        try:
            await context.bot.send_message(
                chat_id=user_id_to_manage,
                text="🎉 Ваш запит на доступ схвалено! Тепер ви можете надсилати аудіофайли або голосові повідомлення для транскрипції."
            )
        except Exception as e:
            logger.error(f"Не вдалося надіслати повідомлення схваленому користувачу {user_id_to_manage}: {e}")

    elif action == "reject":
        logger.info(f"Адміністратор {admin_user.id} відхилив користувача {user_id_to_manage}.")
        user_status[user_id_to_manage] = "rejected"
        await query.edit_message_text(text=
