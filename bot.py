import logging
from decouple import config
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler
from telegram import Update
from datetime import datetime, timedelta
import psycopg2

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load variables from .env file
TELEGRAM_API_TOKEN = config('TELEGRAM_API_TOKEN')

DB_NAME = config('DB_NAME')
DB_USER = config('DB_USER')
DB_PASSWORD = config('DB_PASSWORD')
DB_HOST = config('DB_HOST')
DB_PORT = config('DB_PORT')

AUTHORIZED_USERS = [530674302, 6122780749, 147218177, 336914967, 130043299, 111733381]

# Connect to PostgreSQL database
try:
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )
    conn.autocommit = True
    logger.info("Successfully connected to PostgreSQL database")
except Exception as e:
    logger.error(f"Database connection error: {e}")
    exit(1)

# Dictionaries to store muted users
muted_users = {}  # {user_id: unmute_time}
# Banned users are stored in the database table 'banned_users'

def check_and_remove_mute():
    """Check and remove expired mutes."""
    now = datetime.now()
    to_remove = [user_id for user_id, unmute_time in muted_users.items() if now >= unmute_time]
    for user_id in to_remove:
        del muted_users[user_id]
        logger.info(f"User with ID {user_id} has been unmuted (mute expired).")

def check_and_remove_ban():
    """Check and remove expired bans from the database."""
    try:
        now = datetime.now()
        cur = conn.cursor()
        cur.execute("DELETE FROM banned_users WHERE ban_end_time <= %s", (now,))
        cur.close()
    except Exception as e:
        logger.error(f"Error checking and removing bans: {e}")

def is_user_banned(user_id):
    """Check if a user is banned."""
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
        logger.error(f"Error checking user ban status: {e}")
        return False

def handle_message(update: Update, context: CallbackContext):
    """Handle incoming messages and delete them if the user is muted or banned."""
    if not update.message:
        logger.error("No message found in update.")
        return

    user_id = update.message.from_user.id
    username = (update.message.from_user.username or update.message.from_user.first_name).lower()
    chat_id = update.message.chat_id
    message_id = update.message.message_id

    logger.info(f"Received message from {username} (ID: {user_id})")

    # Check and remove expired mutes and bans
    check_and_remove_mute()
    check_and_remove_ban()

    # Delete messages from muted or banned users
    if user_id in muted_users or is_user_banned(user_id):
        status = "muted" if user_id in muted_users else "banned"
        logger.info(f"User {username} (ID: {user_id}) is {status}. Deleting message.")
        try:
            context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(f"Deleted message from {status} user {username} (ID: {user_id}).")
            return
        except Exception as e:
            logger.error(f"Error deleting message from {status} user {username} (ID: {user_id}): {e}")
            return
    else:
        logger.info(f"User {username} (ID: {user_id}) is not muted or banned.")

    # Save message info to the database
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO banned_messages (chat_id, user_id, username, message_id) VALUES (%s, %s, %s, %s)",
            (chat_id, user_id, username, message_id)
        )
        cur.close()
    except Exception as e:
        logger.error(f"Error saving message to database: {e}")

def handle_edited_message(update: Update, context: CallbackContext):
    """Handle edited messages and delete them if the user is muted or banned."""
    if not update.edited_message:
        logger.error("No edited message found in update.")
        return

    user_id = update.edited_message.from_user.id
    username = (update.edited_message.from_user.username or update.edited_message.from_user.first_name).lower()
    chat_id = update.edited_message.chat_id
    message_id = update.edited_message.message_id

    logger.info(f"User {username} (ID: {user_id}) edited a message.")

    # Check and remove expired mutes and bans
    check_and_remove_mute()
    check_and_remove_ban()

    # Delete edited messages from muted or banned users
    if user_id in muted_users or is_user_banned(user_id):
        status = "muted" if user_id in muted_users else "banned"
        logger.info(f"User {username} (ID: {user_id}) is {status}. Deleting edited message.")
        try:
            context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(f"Deleted edited message from {status} user {username} (ID: {user_id}).")
            return
        except Exception as e:
            logger.error(f"Error deleting edited message from {status} user {username} (ID: {user_id}): {e}")
            return
    else:
        logger.info(f"User {username} (ID: {user_id}) is not muted or banned.")

    # Save edited message info to the database
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO banned_messages (chat_id, user_id, username, message_id) VALUES (%s, %s, %s, %s)",
            (chat_id, user_id, username, message_id)
        )
        cur.close()
    except Exception as e:
        logger.error(f"Error saving edited message to database: {e}")

def mute_user(update: Update, context: CallbackContext):
    """Mute a user by @username, in reply to a message, or for a specified number of minutes."""
    try:
        user_id = update.message.from_user.id

        # Check if user is authorized
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"User {user_id} tried to use /mute but is not authorized.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        args = context.args
        target_user_id = None
        target_username = None
        mute_duration = 10  # Default mute duration in minutes

        # If command is used in reply to a message
        if update.message.reply_to_message:
            target_user = update.message.reply_to_message.from_user
            target_user_id = target_user.id
            target_username = (target_user.username or target_user.first_name).lower()
            if args and args[0].isdigit():
                mute_duration = int(args[0])
        elif args:
            if args[0].startswith('@'):
                # Mute by @username
                username = args[0].lstrip('@').lower()
                chat_id = update.message.chat_id
                try:
                    member = context.bot.get_chat_member(chat_id=chat_id, user_id=username)
                    target_user_id = member.user.id
                    target_username = (member.user.username or member.user.first_name).lower()
                except Exception as e:
                    logger.error(f"Error getting user info for @{username}: {e}")
                    update.message.reply_text(f"Не удалось найти пользователя @{username} в этом чате.")
                    return
                if len(args) > 1 and args[1].isdigit():
                    mute_duration = int(args[1])
            elif args[0].isdigit():
                # Mute the command issuer for specified minutes (not typical)
                mute_duration = int(args[0])
                target_user_id = user_id
                target_username = (update.message.from_user.username or update.message.from_user.first_name).lower()
            else:
                update.message.reply_text("Использование: /mute @username [минуты] или ответьте на сообщение пользователя командой /mute [минуты].")
                return
        else:
            update.message.reply_text("Использование: /mute @username [минуты] или ответьте на сообщение пользователя командой /mute [минуты].")
            return

        # Set unmute time
        unmute_time = datetime.now() + timedelta(minutes=mute_duration)
        muted_users[target_user_id] = unmute_time

        update.message.reply_text(f"Пользователь @{target_username} замьючен на {mute_duration} минут.")
    except Exception as e:
        logger.error(f"Error in mute_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def unmute_user(update: Update, context: CallbackContext):
    """Unmute a user by @username or in reply to a message."""
    try:
        user_id = update.message.from_user.id

        # Check if user is authorized
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"User {user_id} tried to use /unmute but is not authorized.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        target_user_id = None
        target_username = None

        # If command is used in reply to a message
        if update.message.reply_to_message:
            target_user = update.message.reply_to_message.from_user
            target_user_id = target_user.id
            target_username = (target_user.username or target_user.first_name).lower()
        elif context.args and len(context.args) >= 1:
            # Unmute by @username
            username = context.args[0].lstrip('@').lower()
            chat_id = update.message.chat_id
            try:
                member = context.bot.get_chat_member(chat_id=chat_id, user_id=username)
                target_user_id = member.user.id
                target_username = (member.user.username or member.user.first_name).lower()
            except Exception as e:
                logger.error(f"Error getting user info for @{username}: {e}")
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
        logger.error(f"Error in unmute_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def ban_user(update: Update, context: CallbackContext):
    """Ban a user by @username, in reply to a message, or for a specified number of minutes."""
    try:
        user_id = update.message.from_user.id

        # Check if user is authorized
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"User {user_id} tried to use /ban but is not authorized.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        args = context.args
        target_user_id = None
        target_username = None
        ban_duration = 10  # Default ban duration in minutes

        # If command is used in reply to a message
        if update.message.reply_to_message:
            target_user = update.message.reply_to_message.from_user
            target_user_id = target_user.id
            target_username = (target_user.username or target_user.first_name).lower()
            if args and args[0].isdigit():
                ban_duration = int(args[0])
        elif args:
            if args[0].startswith('@'):
                # Ban by @username
                username = args[0].lstrip('@').lower()
                chat_id = update.message.chat_id
                try:
                    member = context.bot.get_chat_member(chat_id=chat_id, user_id=username)
                    target_user_id = member.user.id
                    target_username = (member.user.username or member.user.first_name).lower()
                except Exception as e:
                    logger.error(f"Error getting user info for @{username}: {e}")
                    update.message.reply_text(f"Не удалось найти пользователя @{username} в этом чате.")
                    return
                if len(args) > 1 and args[1].isdigit():
                    ban_duration = int(args[1])
            elif args[0].isdigit():
                # Ban the command issuer for specified minutes (unlikely scenario)
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
            update.message.reply_text(f"Не удалось получить user_id пользователя @{target_username}.")
            return

        # Set ban end time
        ban_end_time = datetime.now() + timedelta(minutes=ban_duration)

        # Insert banned user into banned_users table
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO banned_users (user_id, username, ban_end_time) VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET ban_end_time = EXCLUDED.ban_end_time, username = EXCLUDED.username",
                (target_user_id, target_username, ban_end_time)
            )
            cur.close()
        except Exception as e:
            logger.error(f"Error adding banned user to database: {e}")

        # Delete all messages from the user
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
                    logger.info(f"Deleted message ID {msg_id} from user {target_username} (ID: {target_user_id}).")
                except Exception as e:
                    logger.error(f"Error deleting message ID {msg_id}: {e}")
            # Delete records from the database
            cur.execute(
                "DELETE FROM banned_messages WHERE user_id = %s",
                (target_user_id,)
            )
            cur.close()
        except Exception as e:
            logger.error(f"Error deleting messages from database: {e}")

        update.message.reply_text(f"Пользователь @{target_username} забанен на {ban_duration} минут, и все его сообщения были удалены.")
    except Exception as e:
        logger.error(f"Error in ban_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def unban_user(update: Update, context: CallbackContext):
    """Unban a user by @username."""
    try:
        user_id = update.message.from_user.id

        # Check if user is authorized
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"User {user_id} tried to use /unban but is not authorized.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        if not context.args or len(context.args) < 1:
            update.message.reply_text("Использование: /unban @username")
            return

        username = context.args[0].lstrip('@').lower()

        # Find user_id in banned_users table
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
            logger.error(f"Error searching for user in database: {e}")
            update.message.reply_text("Произошла ошибка при поиске пользователя в базе данных.")
            return

        # Remove user from banned_users table
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM banned_users WHERE user_id = %s",
                (target_user_id,)
            )
            cur.close()
            update.message.reply_text(f"Пользователь @{username} был разблокирован.")
        except Exception as e:
            logger.error(f"Error deleting user from banned_users: {e}")
            update.message.reply_text("Произошла ошибка при разблокировке пользователя.")
    except Exception as e:
        logger.error(f"Error in unban_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def main():
    updater = Updater(token=TELEGRAM_API_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Command handlers
    dispatcher.add_handler(CommandHandler('mute', mute_user))
    dispatcher.add_handler(CommandHandler('unmute', unmute_user))
    dispatcher.add_handler(CommandHandler('ban', ban_user))
    dispatcher.add_handler(CommandHandler('unban', unban_user))

    # Message handlers
    dispatcher.add_handler(MessageHandler(Filters.all, handle_message))
    dispatcher.add_handler(MessageHandler(Filters.update.edited_message, handle_edited_message))

    # Start the bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
