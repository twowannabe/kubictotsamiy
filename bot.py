import logging
from decouple import config
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters, ApplicationHandlerStop
from telegram import Update
from datetime import datetime, timedelta
import psycopg2

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Set logging level to WARNING for specific libraries
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)

# Load environment variables
TELEGRAM_API_TOKEN = config('TELEGRAM_API_TOKEN')

DB_NAME = config('DB_NAME')
DB_USER = config('DB_USER')
DB_PASSWORD = config('DB_PASSWORD')
DB_HOST = config('DB_HOST')
DB_PORT = config('DB_PORT')

# List of authorized users
AUTHORIZED_USERS = [530674302, 6122780749, 147218177, 336914967, 130043299, 111733381, 459816251, 391425127]

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

# Dictionary to store muted users
muted_users = {}

# Create known_users table if it does not exist
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
    logger.info("Table known_users verified or created.")
except Exception as e:
    logger.error(f"Error creating known_users table: {e}")
    exit(1)

# Utility functions to manage mute and ban status
def check_and_remove_mute():
    now = datetime.now()
    to_remove = [user_id for user_id, unmute_time in muted_users.items() if now >= unmute_time]
    for user_id in to_remove:
        del muted_users[user_id]
        logger.info(f"Mute for user ID {user_id} expired and was removed.")

def check_and_remove_ban():
    try:
        now = datetime.now()
        cur = conn.cursor()
        cur.execute("DELETE FROM banned_users WHERE ban_end_time <= %s", (now,))
        cur.close()
    except Exception as e:
        logger.error(f"Error checking and removing bans: {e}")

def is_user_banned(user_id):
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
        logger.error(f"Error checking ban status for user: {e}")
        return False

# Handlers for various bot functions
async def handle_muted_banned_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message or update.edited_message
        if not message:
            return

        user_id = message.from_user.id
        username = (message.from_user.username or message.from_user.first_name).lower()
        chat_id = message.chat_id
        message_id = message.message_id

        # Check and remove expired mutes and bans
        check_and_remove_mute()
        check_and_remove_ban()

        # Check if user is muted or banned
        if user_id in muted_users or is_user_banned(user_id):
            status = "muted" if user_id in muted_users else "banned"
            logger.info(f"User {username} (ID: {user_id}) is {status}. Deleting message.")
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                logger.info(f"Message from {status} user {username} (ID: {user_id}) was deleted.")
                raise ApplicationHandlerStop()
            except Exception as e:
                logger.error(f"Error deleting message from {status} user {username} (ID: {user_id}): {e}")
        else:
            logger.debug(f"User {username} (ID: {user_id}) is not muted or banned.")
    except Exception as e:
        logger.error(f"Error in handle_muted_banned_users: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        logger.error("Message not found in update.")
        return

    user_id = update.message.from_user.id
    username = (update.message.from_user.username or update.message.from_user.first_name).lower()
    chat_id = update.message.chat_id
    message_id = update.message.message_id

    logger.info(f"Received message from {username} (ID: {user_id})")

    # Update user information in the known_users table
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO known_users (user_id, username, last_seen) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, last_seen = EXCLUDED.last_seen",
            (user_id, username, datetime.now())
        )
        cur.close()
    except Exception as e:
        logger.error(f"Error updating known_users: {e}")

    # Save message information in the database
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO banned_messages (chat_id, user_id, username, message_id) VALUES (%s, %s, %s, %s)",
            (chat_id, user_id, username, message_id)
        )
        cur.close()
    except Exception as e:
        logger.error(f"Error saving message to database: {e}")

# Command Handlers
# These handlers allow users to mute, unmute, ban, unban, and manage other users in the chat

# Main function to run the bot
def main():
    application = Application.builder().token(TELEGRAM_API_TOKEN).build()

    # Set logging level for httpx to WARNING
    logging.getLogger('httpx').setLevel(logging.WARNING)

    # Handlers
    application.add_handler(MessageHandler(filters.ALL, handle_muted_banned_users), group=0)
    application.add_handler(CommandHandler('mute', mute_user), group=1)
    application.add_handler(CommandHandler('unmute', unmute_user), group=1)
    application.add_handler(CommandHandler('ban', ban_user), group=1)
    application.add_handler(CommandHandler('unban', unban_user), group=1)
    application.add_handler(CommandHandler('wipe', wipe_messages), group=1)
    application.add_handler(CommandHandler('help', help_command), group=1)
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message), group=2)
    application.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, handle_edited_message), group=2)

    # Start the bot
    logger.info("Bot is running.")
    application.run_polling()

if __name__ == '__main__':
    main()
