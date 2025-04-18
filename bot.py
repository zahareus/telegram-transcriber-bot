import logging
import os
import json
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
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

if not TELEGRAM_BOT_TOKEN: logger.error("Не знайдено TELEGRAM_BOT_TOKEN!"); exit()
if not OPENAI_API_KEY: logger.warning("Не знайдено OPENAI_API_KEY! Транскрипція не працюватиме.")
if not ADMIN_USER_ID: logger.error("Не знайдено ADMIN_USER_ID!"); exit()
try:
    ADMIN_USER_ID = int(ADMIN_USER_ID)
except ValueError:
    logger.error("ADMIN_USER_ID має бути числом!"); exit()

# --- Керування користувачами ---
user_status = {} # user_id: status ("approved", "pending", "rejected")
# TODO: Завантажувати/зберігати цей словник у файл

def get_admin_keyboard(user_id_to_manage: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("✅ Схвалити", callback_data=f"approve_{user_id_to_manage}"),
            InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_{user_id_to_manage}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    username = user.username or "N/A"
    first_name = user.first_name or ""
    last_name = user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()

    logger.info(f"Користувач {user_id} ({username}, {full_name}) запустив /start.")

    status = user_status.get(user_id)

    if status == "approved":
        logger.info(f"Користувач {user_id} вже схвалений.")
        await update.message.reply_text("Ви вже маєте доступ. Можете надсилати аудіо для транскрипції.")
    elif status == "rejected":
        logger.info(f"Користувач {user_id} раніше був відхилений.")
        await update.message.reply_text("На жаль, ваш запит на доступ було відхилено.")
    elif status == "pending":
        logger.info(f"Користувач {user_id} вже очікує на схвалення.")
        await update.message.reply_text("Ваш запит на доступ вже надіслано адміністратору. Будь ласка, зачекайте.")
    else:
        logger.info(f"Новий користувач {user_id}. Надсилаємо запит адміністратору {ADMIN_USER_ID}.")
        user_status[user_id] = "pending"

        await update.message.reply_html(
            rf"Привіт, {user.mention_html()}! Ваш запит на доступ до бота надіслано адміністратору. "
            "Ви отримаєте сповіщення, як тільки його розглянуть."
        )

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
                parse_mode='Markdown'
            )
            logger.info(f"Повідомлення адміністратору про {user_id} надіслано.")
        except Exception as e:
            logger.error(f"Не вдалося надіслати повідомлення адміністратору ({ADMIN_USER_ID}): {e}")
            await update.message.reply_text("Виникла помилка при надсиланні запиту адміністратору. Спробуйте пізніше.")
            # Перевірка чи існує ключ перед видаленням
            if user_id in user_status:
                 del user_status[user_id]


async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    admin_user = query.from_user
    if admin_user.id != ADMIN_USER_ID:
        logger.warning(f"Спроба використання адмін-кнопки користувачем {admin_user.id}!")
        # Не редагуємо повідомлення, якщо це не адмін, щоб не викликати помилку
        return

    action, user_id_str = query.data.split('_', 1)
    try:
        user_id_to_manage = int(user_id_str)
    except ValueError:
        logger.error(f"Неправильний user_id у callback_data: {query.data}")
        await query.edit_message_text(text="Помилка: Некоректні дані.")
        return

    original_message = query.message.text

    if action == "approve":
        logger.info(f"Адміністратор {admin_user.id} схвалив користувача {user_id_to_manage}.")
        user_status[user_id_to_manage] = "approved"
        await query.edit_message_text(
            text=f"{original_message}\n\n✅ Доступ надано користувачу `{user_id_to_manage}`.",
            parse_mode='Markdown'
        ) # <--- ВИПРАВЛЕНО: Додано закриваючу дужку )
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
        await query.edit_message_text(
            text=f"{original_message}\n\n❌ Доступ відхилено для користувача `{user_id_to_manage}`.",
            parse_mode='Markdown'
        ) # <--- ВИПРАВЛЕНО: Додано закриваючу дужку )
        try:
            await context.bot.send_message(
                chat_id=user_id_to_manage,
                text="😔 На жаль, ваш запит на доступ до бота було відхилено."
            )
        except Exception as e:
            logger.error(f"Не вдалося надіслати повідомлення відхиленому користувачу {user_id_to_manage}: {e}")

    else:
        logger.warning(f"Невідома дія в callback_data: {query.data}")
        await query.edit_message_text(text="Помилка: Невідома дія.")


def main() -> None:
    logger.info("Starting main function...")

    # load_user_data() # Додамо пізніше

    logger.info("Starting Flask server in a separate thread...")
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("Flask thread started.")

    logger.info("Setting up Telegram bot application...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_admin_callback, pattern='^(approve|reject)_'))

    # Додамо обробники аудіо тут...

    logger.info("Starting Telegram bot polling...")
    application.run_polling()

    # save_user_data() # Додамо пізніше
    logger.info("Telegram bot polling stopped.")


if __name__ == '__main__':
    main()
