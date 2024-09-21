import logging
from decouple import config
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler
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
AUTHORIZED_USERS = [530674302, 6122780749, 147218177, 336914967, 130043299, 111733381]

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

def handle_message(update: Update, context: CallbackContext):
    """Обрабатывает входящие сообщения и удаляет их, если пользователь замьючен или забанен."""
    if not update.message:
        logger.error("Сообщение не найдено в обновлении.")
        return

    user_id = update.message.from_user.id
    username = (update.message.from_user.username or update.message.from_user.first_name).lower()
    chat_id = update.message.chat_id
    message_id = update.message.message_id

    logger.info(f"Получено сообщение от {username} (ID: {user_id})")

    # Проверяем и снимаем истекшие мьюты и баны
    check_and_remove_mute()
    check_and_remove_ban()

    # Удаляем сообщения от замьюченных или забаненных пользователей
    if user_id in muted_users or is_user_banned(user_id):
        status = "замьючен" if user_id in muted_users else "забанен"
        logger.info(f"Пользователь {username} (ID: {user_id}) {status}. Удаление сообщения.")
        try:
            context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(f"Сообщение от {status} пользователя {username} (ID: {user_id}) было удалено.")
            return
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения от {status} пользователя {username} (ID: {user_id}): {e}")
            return
    else:
        logger.info(f"Пользователь {username} (ID: {user_id}) не замьючен и не забанен.")

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

def handle_edited_message(update: Update, context: CallbackContext):
    """Обрабатывает отредактированные сообщения и удаляет их, если пользователь замьючен или забанен."""
    if not update.edited_message:
        logger.error("Отредактированное сообщение не найдено в обновлении.")
        return

    user_id = update.edited_message.from_user.id
    username = (update.edited_message.from_user.username or update.edited_message.from_user.first_name).lower()
    chat_id = update.edited_message.chat_id
    message_id = update.edited_message.message_id

    logger.info(f"Пользователь {username} (ID: {user_id}) отредактировал сообщение.")

    # Проверяем и снимаем истекшие мьюты и баны
    check_and_remove_mute()
    check_and_remove_ban()

    # Удаляем отредактированные сообщения от замьюченных или забаненных пользователей
    if user_id in muted_users or is_user_banned(user_id):
        status = "замьючен" if user_id in muted_users else "забанен"
        logger.info(f"Пользователь {username} (ID: {user_id}) {status}. Удаление отредактированного сообщения.")
        try:
            context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(f"Отредактированное сообщение от {status} пользователя {username} (ID: {user_id}) было удалено.")
            return
        except Exception as e:
            logger.error(f"Ошибка при удалении отредактированного сообщения от {status} пользователя {username} (ID: {user_id}): {e}")
            return
    else:
        logger.info(f"Пользователь {username} (ID: {user_id}) не замьючен и не забанен.")

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

def mute_user(update: Update, context: CallbackContext):
    """Мьютит пользователя по @username, в ответе на сообщение или на заданное количество минут."""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /mute, но не имеет прав.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
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
                chat_id = update.message.chat_id
                try:
                    member = context.bot.get_chat_member(chat_id=chat_id, user_id=username)
                    target_user_id = member.user.id
                    target_username = (member.user.username or member.user.first_name).lower()
                except Exception as e:
                    logger.error(f"Ошибка при получении информации о пользователе @{username}: {e}")
                    update.message.reply_text(f"Не удалось найти пользователя @{username} в этом чате.")
                    return
                if len(args) > 1 and args[1].isdigit():
                    mute_duration = int(args[1])
            elif args[0].isdigit():
                # Мьют самого себя на заданное количество минут (редкий случай)
                mute_duration = int(args[0])
                target_user_id = user_id
                target_username = (update.message.from_user.username or update.message.from_user.first_name).lower()
            else:
                update.message.reply_text("Использование: /mute @username [минуты] или ответьте на сообщение пользователя командой /mute [минуты].")
                return
        else:
            update.message.reply_text("Использование: /mute @username [минуты] или ответьте на сообщение пользователя командой /mute [минуты].")
            return

        if not target_user_id:
            update.message.reply_text("Не удалось определить пользователя для мьюта.")
            return

        # Устанавливаем время размьюта
        unmute_time = datetime.now() + timedelta(minutes=mute_duration)
        muted_users[target_user_id] = unmute_time

        update.message.reply_text(f"Пользователь @{target_username} замьючен на {mute_duration} минут.")
    except Exception as e:
        logger.error(f"Ошибка в mute_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def unmute_user(update: Update, context: CallbackContext):
    """Размьютит пользователя по @username или в ответе на сообщение."""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /unmute, но не имеет прав.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
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
            chat_id = update.message.chat_id
            try:
                member = context.bot.get_chat_member(chat_id=chat_id, user_id=username)
                target_user_id = member.user.id
                target_username = (member.user.username or member.user.first_name).lower()
            except Exception as e:
                logger.error(f"Ошибка при получении информации о пользователе @{username}: {e}")
                update.message.reply_text(f"Не удалось найти пользователя @{username} в этом чате.")
                return
        else:
            update.message.reply_text("Использование: /unmute @username или ответьте на сообщение пользователя командой /unmute.")
            return

        if target_user_id in muted_users:
            del muted_users[target_user_id]
            update.message.reply_text(f"Пользователь @{target_username} был размьючен.")
        else:
            update.message.reply_text(f"Пользователь @{target_username} не был замьючен.")
    except Exception as e:
        logger.error(f"Ошибка в unmute_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def ban_user(update: Update, context: CallbackContext):
    """Банит пользователя по @username, в ответе на сообщение или на заданное количество минут."""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /ban, но не имеет прав.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
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
                chat_id = update.message.chat_id
                try:
                    member = context.bot.get_chat_member(chat_id=chat_id, user_id=username)
                    target_user_id = member.user.id
                    target_username = (member.user.username or member.user.first_name).lower()
                except Exception as e:
                    logger.error(f"Ошибка при получении информации о пользователе @{username}: {e}")
                    update.message.reply_text(f"Не удалось найти пользователя @{username} в этом чате.")
                    return
                if len(args) > 1 and args[1].isdigit():
                    ban_duration = int(args[1])
            elif args[0].isdigit():
                # Бан самого себя на заданное количество минут (редкий случай)
                ban_duration = int(args[0])
                target_user_id = user_id
                target_username = (update.message.from_user.username or update.message.from_user.first_name).lower()
            else:
                update.message.reply_text("Использование: /ban @username [минуты] или ответьте на сообщение пользователя командой /ban [минуты].")
                return
        else:
            update.message.reply_text("Использование: /ban @username [минуты] или ответьте на сообщение пользователя командой /ban [минуты].")
            return

        if not target_user_id:
            update.message.reply_text("Не удалось определить пользователя для бана.")
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
                    context.bot.delete_message(chat_id=msg_chat_id, message_id=msg_id)
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

        update.message.reply_text(f"Пользователь @{target_username} забанен на {ban_duration} минут, и все его сообщения были удалены.")
    except Exception as e:
        logger.error(f"Ошибка в ban_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def unban_user(update: Update, context: CallbackContext):
    """Разбанивает пользователя по @username."""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /unban, но не имеет прав.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        if not context.args or len(context.args) < 1:
            update.message.reply_text("Использование: /unban @username")
            return

        username = context.args[0].lstrip('@').lower()

        # Ищем user_id в таблице banned_users
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT user_id FROM banned_users WHERE LOWER(username) = %s",
                (username,)
            )
            result = cur.fetchone()
            cur.close()

            if result:
                target_user_id = result[0]
            else:
                update.message.reply_text(f"Пользователь @{username} не найден в списке забаненных пользователей.")
                return
        except Exception as e:
            logger.error(f"Ошибка при поиске пользователя в базе данных: {e}")
            update.message.reply_text("Произошла ошибка при поиске пользователя в базе данных.")
            return

        # Удаляем пользователя из таблицы banned_users
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM banned_users WHERE user_id = %s",
                (target_user_id,)
            )
            cur.close()
            update.message.reply_text(f"Пользователь @{username} был разблокирован.")
        except Exception as e:
            logger.error(f"Ошибка при удалении пользователя из banned_users: {e}")
            update.message.reply_text("Произошла ошибка при разблокировке пользователя.")
    except Exception as e:
        logger.error(f"Ошибка в unban_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def unmute_user(update: Update, context: CallbackContext):
    """Размьютит пользователя по @username или в ответе на сообщение."""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /unmute, но не имеет прав.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
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
            chat_id = update.message.chat_id
            try:
                member = context.bot.get_chat_member(chat_id=chat_id, user_id=username)
                target_user_id = member.user.id
                target_username = (member.user.username or member.user.first_name).lower()
            except Exception as e:
                logger.error(f"Ошибка при получении информации о пользователе @{username}: {e}")
                update.message.reply_text(f"Не удалось найти пользователя @{username} в этом чате.")
                return
        else:
            update.message.reply_text("Использование: /unmute @username или ответьте на сообщение пользователя командой /unmute.")
            return

        if target_user_id in muted_users:
            del muted_users[target_user_id]
            update.message.reply_text(f"Пользователь @{target_username} был размьючен.")
        else:
            update.message.reply_text(f"Пользователь @{target_username} не был замьючен.")
    except Exception as e:
        logger.error(f"Ошибка в unmute_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def help_command(update: Update, context: CallbackContext):
    """Отправляет подробную информацию о доступных командах бота."""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /help, но не имеет прав.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
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
            "🔧 **Примеры:**\n"
            "   - `/ban @vladixoxo 30` — забанить пользователя @vladixoxo на 30 минут.\n"
            "   - Ответьте на сообщение пользователя и введите `/ban 15` — забанить этого пользователя на 15 минут.\n"
            "   - `/mute @user123` — замьютить пользователя @user123 на 10 минут.\n"
            "   - Ответьте на сообщение пользователя и введите `/unmute` — размьютить этого пользователя.\n\n"
            "⚠️ **Важно:** Все команды доступны только авторизованным пользователям."
        )

        update.message.reply_text(help_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка в help_command: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def main():
    """Основная функция запуска бота."""
    updater = Updater(token=TELEGRAM_API_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Обработчики команд
    dispatcher.add_handler(CommandHandler('mute', mute_user))
    dispatcher.add_handler(CommandHandler('unmute', unmute_user))
    dispatcher.add_handler(CommandHandler('ban', ban_user))
    dispatcher.add_handler(CommandHandler('unban', unban_user))
    dispatcher.add_handler(CommandHandler('help', help_command))  # Добавлена команда /help

    # Обработчики сообщений
    dispatcher.add_handler(MessageHandler(Filters.all & ~Filters.command, handle_message))
    dispatcher.add_handler(MessageHandler(Filters.update.edited_message, handle_edited_message))

    # Запуск бота
    updater.start_polling()
    logger.info("Бот запущен и работает.")
    updater.idle()

if __name__ == '__main__':
    main()
