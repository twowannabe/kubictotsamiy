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

# Устанавливаем уровень логирования для httpx на WARNING
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)

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
    try:
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
        else:
            logger.debug(f"Пользователь {username} (ID: {user_id}) не замьючен и не забанен.")
    except Exception as e:
        logger.error(f"Ошибка в handle_muted_banned_users: {e}")

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

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Мьютит пользователя по @username, в ответе на сообщение или на заданное количество минут."""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /mute, но не имеет прав.")
            await update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        args = context.args
        target_user_id = None
        target_username = None
        mute_duration = 10  # Стандартная длительность мьюта в минутах

        # Если команда используется в ответе на сообщение
        if update.message.reply_to_message:
            target_user = update.message.reply_to_message.from_user
            target_user_id = target_user.id
            target_username = (target_user.username or target_user.first_name).lower()
            if args and args[0].isdigit():
                mute_duration = int(args[0])
        elif args:
            if args[0].startswith('@'):
                # Мьют по @username
                username = args[0].lstrip('@').lower()
                try:
                    # Ищем пользователя в таблице known_users
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT user_id FROM known_users WHERE LOWER(username) = %s LIMIT 1",
                        (username,)
                    )
                    result = cur.fetchone()
                    cur.close()
                    if result:
                        target_user_id = result[0]
                        target_username = username
                    else:
                        await update.message.reply_text(f"Не удалось найти пользователя @{username} в базе данных.")
                        return
                    if len(args) > 1 and args[1].isdigit():
                        mute_duration = int(args[1])
                except Exception as e:
                    logger.error(f"Ошибка при получении информации о пользователе @{username}: {e}")
                    await update.message.reply_text("Произошла ошибка при поиске пользователя в базе данных.")
                    return
            elif args[0].isdigit():
                # Мьют самого себя на заданное количество минут (редкий случай)
                mute_duration = int(args[0])
                target_user_id = user_id
                target_username = (update.message.from_user.username or update.message.from_user.first_name).lower()
            else:
                await update.message.reply_text("Использование: /mute @username [минуты] или ответьте на сообщение пользователя командой /mute [минуты].")
                return
        else:
            await update.message.reply_text("Использование: /mute @username [минуты] или ответьте на сообщение пользователя командой /mute [минуты].")
            return

        if not target_user_id:
            await update.message.reply_text("Не удалось определить пользователя для мьюта.")
            return

        # Устанавливаем время размьюта
        unmute_time = datetime.now() + timedelta(minutes=mute_duration)
        muted_users[target_user_id] = unmute_time

        await update.message.reply_text(f"Пользователь @{target_username} замьючен на {mute_duration} минут.")
    except Exception as e:
        logger.error(f"Ошибка в mute_user: {e}")
        await update.message.reply_text("Произошла ошибка при выполнении команды.")

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Размьютит пользователя по @username или в ответе на сообщение."""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /unmute, но не имеет прав.")
            await update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        target_user_id = None
        target_username = None

        # Если команда используется в ответе на сообщение
        if update.message.reply_to_message:
            target_user = update.message.reply_to_message.from_user
            target_user_id = target_user.id
            target_username = (target_user.username or target_user.first_name).lower()
        elif context.args and len(context.args) >= 1:
            # Размьют по @username
            username = context.args[0].lstrip('@').lower()
            try:
                # Ищем пользователя в таблице known_users
                cur = conn.cursor()
                cur.execute(
                    "SELECT user_id FROM known_users WHERE LOWER(username) = %s LIMIT 1",
                    (username,)
                )
                result = cur.fetchone()
                cur.close()
                if result:
                    target_user_id = result[0]
                    target_username = username
                else:
                    await update.message.reply_text(f"Не удалось найти пользователя @{username} в базе данных.")
                    return
            except Exception as e:
                logger.error(f"Ошибка при получении информации о пользователе @{username}: {e}")
                await update.message.reply_text("Произошла ошибка при поиске пользователя в базе данных.")
                return
        else:
            await update.message.reply_text("Использование: /unmute @username или ответьте на сообщение пользователя командой /unmute.")
            return

        if target_user_id in muted_users:
            del muted_users[target_user_id]
            await update.message.reply_text(f"Пользователь @{target_username} был размьючен.")
        else:
            await update.message.reply_text(f"Пользователь @{target_username} не был замьючен.")
    except Exception as e:
        logger.error(f"Ошибка в unmute_user: {e}")
        await update.message.reply_text("Произошла ошибка при выполнении команды.")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Банит пользователя по @username, в ответе на сообщение или на заданное количество минут."""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /ban, но не имеет прав.")
            await update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        args = context.args
        target_user_id = None
        target_username = None
        ban_duration = 10  # Стандартная длительность бана в минутах

        # Если команда используется в ответе на сообщение
        if update.message.reply_to_message:
            target_user = update.message.reply_to_message.from_user
            target_user_id = target_user.id
            target_username = (target_user.username or target_user.first_name).lower()
            if args and args[0].isdigit():
                ban_duration = int(args[0])
        elif args:
            if args[0].startswith('@'):
                # Бан по @username
                username = args[0].lstrip('@').lower()
                try:
                    # Ищем пользователя в таблице known_users
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT user_id FROM known_users WHERE LOWER(username) = %s LIMIT 1",
                        (username,)
                    )
                    result = cur.fetchone()
                    cur.close()
                    if result:
                        target_user_id = result[0]
                        target_username = username
                    else:
                        await update.message.reply_text(f"Не удалось найти пользователя @{username} в базе данных.")
                        return
                    if len(args) > 1 and args[1].isdigit():
                        ban_duration = int(args[1])
                except Exception as e:
                    logger.error(f"Ошибка при получении информации о пользователе @{username}: {e}")
                    await update.message.reply_text("Произошла ошибка при поиске пользователя в базе данных.")
                    return
            elif args[0].isdigit():
                # Бан самого себя на заданное количество минут (редкий случай)
                ban_duration = int(args[0])
                target_user_id = user_id
                target_username = (update.message.from_user.username or update.message.from_user.first_name).lower()
            else:
                await update.message.reply_text("Использование: /ban @username [минуты] или ответьте на сообщение пользователя командой /ban [минуты].")
                return
        else:
            await update.message.reply_text("Использование: /ban @username [минуты] или ответьте на сообщение пользователя командой /ban [минуты].")
            return

        if not target_user_id:
            await update.message.reply_text("Не удалось определить пользователя для бана.")
            return

        # Устанавливаем время разбана
        ban_end_time = datetime.now() + timedelta(minutes=ban_duration)

        # Вставляем забаненного пользователя в таблицу banned_users
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO banned_users (user_id, username, ban_end_time) VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET ban_end_time = EXCLUDED.ban_end_time, username = EXCLUDED.username",
                (target_user_id, target_username, ban_end_time)
            )
            cur.close()
        except Exception as e:
            logger.error(f"Ошибка при добавлении забаненного пользователя в базу данных: {e}")

        # Удаляем все сообщения пользователя из базы данных и чата
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT message_id, chat_id FROM banned_messages WHERE user_id = %s",
                (target_user_id,)
            )
            messages = cur.fetchall()
            for msg_id, msg_chat_id in messages:
                try:
                    await context.bot.delete_message(chat_id=msg_chat_id, message_id=msg_id)
                    logger.info(f"Удалено сообщение с ID {msg_id} от пользователя {target_username} (ID: {target_user_id}).")
                except Exception as e:
                    logger.error(f"Ошибка при удалении сообщения с ID {msg_id}: {e}")
            # Удаляем записи из базы данных
            cur.execute(
                "DELETE FROM banned_messages WHERE user_id = %s",
                (target_user_id,)
            )
            cur.close()
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщений из базы данных: {e}")

        await update.message.reply_text(f"Пользователь @{target_username} забанен на {ban_duration} минут, и все его сообщения были удалены.")
    except Exception as e:
        logger.error(f"Ошибка в ban_user: {e}")
        await update.message.reply_text("Произошла ошибка при выполнении команды.")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Разбанивает пользователя по @username."""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /unban, но не имеет прав.")
            await update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        if not context.args or len(context.args) < 1:
            await update.message.reply_text("Использование: /unban @username")
            return

        username = context.args[0].lstrip('@').lower()

        # Ищем user_id в таблице known_users
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT user_id FROM known_users WHERE LOWER(username) = %s LIMIT 1",
                (username,)
            )
            result = cur.fetchone()
            cur.close()

            if result:
                target_user_id = result[0]
            else:
                await update.message.reply_text(f"Пользователь @{username} не найден в базе данных.")
                return
        except Exception as e:
            logger.error(f"Ошибка при поиске пользователя в базе данных: {e}")
            await update.message.reply_text("Произошла ошибка при поиске пользователя в базе данных.")
            return

        # Удаляем пользователя из таблицы banned_users
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM banned_users WHERE user_id = %s",
                (target_user_id,)
            )
            cur.close()
            await update.message.reply_text(f"Пользователь @{username} был разблокирован.")
        except Exception as e:
            logger.error(f"Ошибка при удалении пользователя из banned_users: {e}")
            await update.message.reply_text("Произошла ошибка при разблокировке пользователя.")
    except Exception as e:
        logger.error(f"Ошибка в unban_user: {e}")
        await update.message.reply_text("Произошла ошибка при выполнении команды.")

async def wipe_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет все сообщения пользователя, вызывающего команду, в текущем чате."""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /wipe, но не имеет прав.")
            await update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        chat_id = update.message.chat_id

        # Получаем все message_id пользователя из таблицы banned_messages для текущего чата
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT message_id FROM banned_messages WHERE user_id = %s AND chat_id = %s",
                (user_id, chat_id)
            )
            messages = cur.fetchall()
            cur.close()

            if not messages:
                await update.message.reply_text("У вас нет сохраненных сообщений для удаления.")
                return

            deleted_count = 0
            for (msg_id,) in messages:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                    deleted_count += 1
                    logger.info(f"Удалено сообщение ID {msg_id} пользователя ID {user_id}.")
                except Exception as e:
                    logger.error(f"Ошибка при удалении сообщения ID {msg_id}: {e}")

            # Удаляем записи о сообщениях из базы данных
            try:
                cur = conn.cursor()
                cur.execute(
                    "DELETE FROM banned_messages WHERE user_id = %s AND chat_id = %s",
                    (user_id, chat_id)
                )
                cur.close()
            except Exception as e:
                logger.error(f"Ошибка при удалении записей сообщений из базы данных: {e}")

            await update.message.reply_text(f"Удалено {deleted_count} ваших сообщений.")
        except Exception as e:
            logger.error(f"Ошибка при получении сообщений для удаления: {e}")
            await update.message.reply_text("Произошла ошибка при попытке удалить ваши сообщения.")
    except Exception as e:
        logger.error(f"Ошибка в wipe_messages: {e}")
        await update.message.reply_text("Произошла ошибка при выполнении команды.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет подробную информацию о доступных командах бота."""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /help, но не имеет прав.")
            await update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        help_text = (
            "📚 **Справка по командам бота** 📚\n\n"
            "**1. /ban**\n"
            "   - **Использование:**\n"
            "     - `/ban @username [минуты]` — забанить пользователя на указанное количество минут. Если время не указано, бан длится 10 минут по умолчанию.\n"
            "     - `/ban [минуты]` — забанить пользователя, на сообщение которого вы отвечаете, на указанное количество минут.\n"
            "   - **Описание:** Банит пользователя, удаляет все его сообщения (как старые, так и новые).\n\n"
            "**2. /mute**\n"
            "   - **Использование:**\n"
            "     - `/mute @username [минуты]` — замьютить пользователя на указанное количество минут. Если время не указано, мьют длится 10 минут по умолчанию.\n"
            "     - `/mute [минуты]` — замьютить пользователя, на сообщение которого вы отвечаете, на указанное количество минут.\n"
            "   - **Описание:** Мьютит пользователя, удаляет только новые сообщения пользователя, старые остаются.\n\n"
            "**3. /unmute**\n"
            "   - **Использование:**\n"
            "     - `/unmute @username` — размьютить пользователя.\n"
            "     - `/unmute` — размьютить пользователя, на сообщение которого вы отвечаете.\n"
            "   - **Описание:** Снимает мьют с пользователя, позволяя ему снова отправлять сообщения.\n\n"
            "**4. /unban**\n"
            "   - **Использование:**\n"
            "     - `/unban @username` — разбанить пользователя.\n"
            "   - **Описание:** Снимает бан с пользователя, позволяя ему снова отправлять сообщения.\n\n"
            "**5. /wipe**\n"
            "   - **Использование:**\n"
            "     - `/wipe` — удаляет все ваши сообщения в этом чате.\n"
            "   - **Описание:** Удаляет все ваши сообщения, которые бот сохранил в базе данных для этого чата.\n\n"
            "🔧 **Примеры:**\n"
            "   - `/ban @vladixoxo 30` — забанить пользователя @vladixoxo на 30 минут.\n"
            "   - Ответьте на сообщение пользователя и введите `/ban 15` — забанить этого пользователя на 15 минут.\n"
            "   - `/mute @user123` — замьютить пользователя @user123 на 10 минут.\n"
            "   - Ответьте на сообщение пользователя и введите `/unmute` — размьютить этого пользователя.\n"
            "   - `/wipe` — удалить все ваши сообщения в этом чате.\n\n"
            "⚠️ **Важно:** Все команды доступны только авторизованным пользователям.\n\n"
            "📌 **Примечание:** При использовании команд по @username убедитесь, что пользователь ранее отправлял сообщения в чатах, где присутствует бот, чтобы его информация была сохранена в базе данных."
        )

        await update.message.reply_text(help_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка в help_command: {e}")
        await update.message.reply_text("Произошла ошибка при выполнении команды.")

def main():
    """Основная функция запуска бота."""
    application = Application.builder().token(TELEGRAM_API_TOKEN).build()

    # Устанавливаем уровень логирования для httpx на WARNING
    logging.getLogger('httpx').setLevel(logging.WARNING)

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
