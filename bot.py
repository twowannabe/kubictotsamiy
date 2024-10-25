import logging
from decouple import config
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters, ApplicationHandlerStop
from telegram import Update
from datetime import datetime, timedelta
import psycopg2

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных из .env файла
TELEGRAM_API_TOKEN = config('TELEGRAM_API_TOKEN')

DB_NAME = config('DB_NAME')
DB_USER = config('DB_USER')
DB_PASSWORD = config('DB_PASSWORD')
DB_HOST = config('DB_HOST')
DB_PORT = config('DB_PORT')

# Список авторизованных пользователей (добавьте сюда Telegram user_id тех, кто может управлять ботом)
AUTHORIZED_USERS = [530674302, 6122780749, 147218177, 336914967, 130043299, 111733381, 459816251, 391425127]

# Подключение к базе данных PostgreSQL
try:
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )
    conn.autocommit = True
    logger.info("Успешно подключились к базе данных PostgreSQL")
except Exception as e:
    logger.error(f"Ошибка подключения к базе данных: {e}")
    exit(1)

# Словарь для хранения замьюченных пользователей
muted_users = {}  # {user_id: unmute_time}
# Забаненные пользователи хранятся в таблице 'banned_users'

# Создание таблицы known_users, если она не существует
try:
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS known_users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            last_seen TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    logger.info("Таблица known_users проверена или создана.")
except Exception as e:
    logger.error(f"Ошибка при создании таблицы known_users: {e}")
    exit(1)

def check_and_remove_mute():
    """Проверяет и снимает мьют с пользователей, у которых время мьюта истекло."""
    now = datetime.now()
    to_remove = [user_id for user_id, unmute_time in muted_users.items() if now >= unmute_time]
    for user_id in to_remove:
        del muted_users[user_id]
        logger.info(f"Мьют пользователя с ID {user_id} истек и был снят.")

def check_and_remove_ban():
    """Проверяет и удаляет истекшие баны из таблицы banned_users."""
    try:
        now = datetime.now()
        cur = conn.cursor()
        cur.execute("DELETE FROM banned_users WHERE ban_end_time <= %s", (now,))
        cur.close()
    except Exception as e:
        logger.error(f"Ошибка при проверке и удалении банов: {e}")

def is_user_banned(user_id):
    """Проверяет, забанен ли пользователь."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT ban_end_time FROM banned_users WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        cur.close()
        if result:
            ban_end_time = result[0]
            if datetime.now() < ban_end_time:
                return True
        return False
    except Exception as e:
        logger.error(f"Ошибка при проверке статуса бана пользователя: {e}")
        return False

async def handle_muted_banned_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет сообщения от замьюченных или забаненных пользователей."""
    message = update.message or update.edited_message
    if not message:
        return

    user_id = message.from_user.id
    username = (message.from_user.username or message.from_user.first_name).lower()
    chat_id = message.chat_id
    message_id = message.message_id

    # Проверяем и снимаем истекшие мьюты и баны
    check_and_remove_mute()
    check_and_remove_ban()

    # Проверяем, замьючен или забанен ли пользователь
    if user_id in muted_users or is_user_banned(user_id):
        status = "замьючен" if user_id in muted_users else "забанен"
        logger.info(f"Пользователь {username} (ID: {user_id}) {status}. Удаление сообщения.")
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(f"Сообщение от {status} пользователя {username} (ID: {user_id}) было удалено.")
            # Останавливаем дальнейшую обработку обновления
            raise ApplicationHandlerStop()
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения от {status} пользователя {username} (ID: {user_id}): {e}")
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает входящие сообщения."""
    if not update.message:
        logger.error("Сообщение не найдено в обновлении.")
        return

    user_id = update.message.from_user.id
    username = (update.message.from_user.username or update.message.from_user.first_name).lower()
    chat_id = update.message.chat_id
    message_id = update.message.message_id

    logger.info(f"Получено сообщение от {username} (ID: {user_id})")

    # Обновляем информацию о пользователе в таблице known_users
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO known_users (user_id, username, last_seen) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, last_seen = EXCLUDED.last_seen",
            (user_id, username, datetime.now())
        )
        cur.close()
    except Exception as e:
        logger.error(f"Ошибка при обновлении known_users: {e}")

    # Сохраняем информацию о сообщении в базе данных
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO banned_messages (chat_id, user_id, username, message_id) VALUES (%s, %s, %s, %s)",
            (chat_id, user_id, username, message_id)
        )
        cur.close()
    except Exception as e:
        logger.error(f"Ошибка при сохранении сообщения в базе данных: {e}")

async def handle_edited_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает отредактированные сообщения."""
    if not update.edited_message:
        logger.error("Отредактированное сообщение не найдено в обновлении.")
        return

    user_id = update.edited_message.from_user.id
    username = (update.edited_message.from_user.username or update.edited_message.from_user.first_name).lower()
    chat_id = update.edited_message.chat_id
    message_id = update.edited_message.message_id

    logger.info(f"Пользователь {username} (ID: {user_id}) отредактировал сообщение.")

    # Обновляем информацию о пользователе в таблице known_users
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO known_users (user_id, username, last_seen) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, last_seen = EXCLUDED.last_seen",
            (user_id, username, datetime.now())
        )
        cur.close()
    except Exception as e:
        logger.error(f"Ошибка при обновлении known_users: {e}")

    # Сохраняем информацию об отредактированном сообщении в базе данных
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO banned_messages (chat_id, user_id, username, message_id) VALUES (%s, %s, %s, %s)",
            (chat_id, user_id, username, message_id)
        )
        cur.close()
    except Exception as e:
        logger.error(f"Ошибка при сохранении отредактированного сообщения в базе данных: {e}")

# Ваши функции команд остаются такими же

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (без изменений)
    pass  # Замените pass на ваш код

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (без изменений)
    pass  # Замените pass на ваш код

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (без изменений)
    pass  # Замените pass на ваш код

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (без изменений)
    pass  # Замените pass на ваш код

async def wipe_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (без изменений)
    pass  # Замените pass на ваш код

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (без изменений)
    pass  # Замените pass на ваш код

def main():
    """Основная функция запуска бота."""
    application = Application.builder().token(TELEGRAM_API_TOKEN).build()

    # Обработчик для удаления сообщений от замьюченных или забаненных пользователей
    application.add_handler(MessageHandler(filters.ALL, handle_muted_banned_users), group=0)

    # Обработчики команд
    application.add_handler(CommandHandler('mute', mute_user), group=1)
    application.add_handler(CommandHandler('unmute', unmute_user), group=1)
    application.add_handler(CommandHandler('ban', ban_user), group=1)
    application.add_handler(CommandHandler('unban', unban_user), group=1)
    application.add_handler(CommandHandler('wipe', wipe_messages), group=1)
    application.add_handler(CommandHandler('help', help_command), group=1)

    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message), group=2)
    application.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, handle_edited_message), group=2)

    # Запуск бота
    logger.info("Бот запущен и работает.")
    application.run_polling()

if __name__ == '__main__':
    main()
