import logging
from decouple import config
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler
from telegram import Update
from datetime import datetime, timedelta
import openai
import psycopg2
import re

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load variables from .env file
TELEGRAM_API_TOKEN = config('TELEGRAM_API_TOKEN')
openai.api_key = config('OPENAI_API_KEY')

DB_NAME = config('DB_NAME')
DB_USER = config('DB_USER')
DB_PASSWORD = config('DB_PASSWORD')
DB_HOST = config('DB_HOST')
DB_PORT = config('DB_PORT')

# Fixed user ID
FIXED_USER_ID = int(config('FIXED_USER_ID'))

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
    logger.info("Successfully connected to PostgreSQL database")
except Exception as e:
    logger.error(f"Database connection error: {e}")
    exit(1)

# Lists of muted and banned users
muted_users = {}
banned_users = {}

def check_and_remove_ban():
    """Checks the time and unbans users if the ban duration has expired"""
    now = datetime.now()
    to_remove = [user for user, unban_time in banned_users.items() if now >= unban_time]

    for user in to_remove:
        del banned_users[user]
        logger.info(f"Ban for user ID {user} has expired and was removed.")

def check_and_remove_mute():
    """Checks the time and unmutes users if the mute duration has expired"""
    now = datetime.now()
    to_remove = [user_id for user_id, unmute_time in muted_users.items() if now >= unmute_time]

    for user_id in to_remove:
        del muted_users[user_id]
        logger.info(f"Mute for user ID {user_id} has expired and was removed.")

def delete_banned_user_message(update: Update, context: CallbackContext) -> bool:
    """Deletes messages from banned users and returns True if the message was deleted"""
    check_and_remove_ban()

    if update.message and update.message.from_user:
        if update.message.from_user.id in banned_users:
            try:
                context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
                logger.info(f"Message from user ID {update.message.from_user.id} was deleted because they are banned.")
                return True
            except Exception as e:
                logger.error(f"Error deleting message from banned user: {e}")
                return False
    return False

def extract_keywords_from_question(question):
    """Extracts keywords from the user's question."""
    clean_question = re.sub(r'[^\w\s]', '', question).lower()
    keywords = clean_question.split()
    return keywords

def search_messages_by_keywords(keywords, limit=50):
    """Searches for messages containing keywords in the database for FIXED_USER_ID, with a limit on the number."""
    try:
        cur = conn.cursor()
        query = f"SELECT text FROM messages WHERE user_id = %s AND (" + " OR ".join([f"text ILIKE %s" for _ in keywords]) + f") LIMIT {limit}"
        cur.execute(query, [FIXED_USER_ID] + [f"%{keyword}%" for keyword in keywords])
        messages = [row[0] for row in cur.fetchall()]
        cur.close()

        logger.info(f"Found messages for FIXED_USER_ID: {messages}")

        return messages
    except Exception as e:
        logger.error(f"Error searching messages in the database: {e}")
        return []

def generate_answer_by_topic(user_question, related_messages):
    """Generates an answer based on messages containing keywords from the question."""
    truncated_messages = " ".join(related_messages)

    logger.info(f"Found messages for answer generation: {truncated_messages}")

    prompt = f"Based on the user's messages below, formulate a coherent opinion on their behalf.\n\nUser messages:\n{truncated_messages}\n\nUser question: {user_question}\nAnswer:"

    try:
        logger.info(f"OpenAI prompt: {prompt}")

        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",  # Use the selected model
            messages=[
                {"role": "system", "content": "You are an assistant who answers on behalf of the user based on their messages."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=250,
            n=1,
            stop=None,
            temperature=0.7,
        )
        answer = response['choices'][0]['message']['content'].strip()

        # Truncate the text to 20 words
        words = answer.split()
        if len(words) > 20:
            short_answer = " ".join(words[:20]) + "..."
        else:
            short_answer = answer

        logger.info(f"OpenAI answer: {short_answer}")

        return short_answer
    except Exception as e:
        logger.error(f"Error querying OpenAI API: {e}")
        return ""

def should_respond_to_message(update: Update, context: CallbackContext) -> bool:
    """Checks if the bot should respond to the message (if the bot was mentioned or it's a reply to its message)."""
    message = update.message

    if message.entities:
        for entity in message.entities:
            mention = message.text[entity.offset:entity.offset + entity.length].lower()
            if entity.type == 'mention' and mention == f"@{context.bot.username.lower()}":
                return True

    if message.reply_to_message and message.reply_to_message.from_user.id == context.bot.id:
        return True

    return False

def handle_message(update: Update, context: CallbackContext):
    """Handles incoming messages and deletes them if the user is muted."""
    if not update.message:
        logger.error("Message not found in update.")
        return

    user_id = update.message.from_user.id
    username = update.message.from_user.username

    logger.info(f"Received message from user {username} (ID: {user_id}): {update.message.text}")

    # Check and remove expired mutes
    check_and_remove_mute()

    # Delete messages from muted users
    if user_id in muted_users:
        logger.info(f"User {username} (ID: {user_id}) is muted. Deleting message.")
        try:
            context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
            logger.info(f"Message from muted user {username} (ID: {user_id}) was deleted.")
            return
        except Exception as e:
            logger.error(f"Error deleting message from muted user {username} (ID: {user_id}): {e}")
            return
    else:
        logger.info(f"User {username} (ID: {user_id}) is not muted.")

    # Delete messages from banned users
    message_deleted = delete_banned_user_message(update, context)

    # Continue processing if the message was not deleted
    if not message_deleted and should_respond_to_message(update, context):
        user_question = update.message.text.strip()

        # Extract keywords from the question
        keywords = extract_keywords_from_question(user_question)

        if keywords:
            logger.info(f"Starting search for messages with keywords: {keywords}")

            related_messages = search_messages_by_keywords(keywords)

            if related_messages:
                # Generate an answer using OpenAI
                answer = generate_answer_by_topic(user_question, related_messages)
                if answer:
                    logger.info(f"Answer: {answer}")
                    update.message.reply_text(answer)
            else:
                logger.info("No messages found for the given keywords.")
        else:
            logger.info("No keywords extracted.")

def handle_edited_message(update: Update, context: CallbackContext):
    """Handles edited messages and deletes them if the user is muted."""
    if not update.edited_message:
        logger.error("Edited message not found in update.")
        return

    user_id = update.edited_message.from_user.id
    username = update.edited_message.from_user.username

    logger.info(f"User {username} (ID: {user_id}) edited a message: {update.edited_message.text}")

    # Check and remove expired mutes
    check_and_remove_mute()

    # Delete edited messages from muted users
    if user_id in muted_users:
        logger.info(f"User {username} (ID: {user_id}) is muted. Deleting edited message.")
        try:
            context.bot.delete_message(chat_id=update.edited_message.chat_id, message_id=update.edited_message.message_id)
            logger.info(f"Edited message from muted user {username} (ID: {user_id}) was deleted.")
            return
        except Exception as e:
            logger.error(f"Error deleting edited message from muted user {username} (ID: {user_id}): {e}")
            return
    else:
        logger.info(f"User {username} (ID: {user_id}) is not muted.")

def mute_user(update: Update, context: CallbackContext):
    """Command to mute a user (used as a reply to the user's message)"""
    try:
        user_id = update.message.from_user.id

        # Check if the user is authorized
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"User {user_id} attempted to use /mute command but is not authorized.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        if not context.args or len(context.args) < 1:
            update.message.reply_text("Использование: /mute минуты\nНеобходимо ответить на сообщение пользователя.")
            return

        mute_duration = int(context.args[0])

        # Check if the command is a reply to a message
        if not update.message.reply_to_message:
            update.message.reply_text("Команда /mute должна быть ответом на сообщение пользователя.")
            return

        # Get the target user ID
        target_user = update.message.reply_to_message.from_user
        target_user_id = target_user.id
        target_username = target_user.username or target_user.first_name

        # Determine when to unmute
        unmute_time = datetime.now() + timedelta(minutes=mute_duration)
        muted_users[target_user_id] = unmute_time

        update.message.reply_text(f"Пользователь @{target_username} замьючен на {mute_duration} минут.")
    except Exception as e:
        logger.error(f"Ошибка в mute_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def ban_user(update: Update, context: CallbackContext):
    """Command to ban a user (used as a reply to the user's message)"""
    try:
        user_id = update.message.from_user.id

        # Check if the user is authorized
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"User {user_id} attempted to use /ban command but is not authorized.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        # Check if the command is a reply to a message
        if not update.message.reply_to_message:
            update.message.reply_text("Команда /ban должна быть ответом на сообщение пользователя.")
            return

        # Get the target user ID
        target_user_id = update.message.reply_to_message.from_user.id

        # Determine when to unban (after 10 minutes)
        ban_end_time = datetime.now() + timedelta(minutes=10)
        banned_users[target_user_id] = ban_end_time

        update.message.reply_text(f"Пользователь забанен на 10 минут.")
    except Exception as e:
        logger.error(f"Ошибка в ban_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def unban_user(update: Update, context: CallbackContext):
    """Command to unban/unmute a user (used as a reply to the user's message)"""
    try:
        user_id = update.message.from_user.id

        # Check if the user is authorized
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"User {user_id} attempted to use /unban command but is not authorized.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        # Check if the command is a reply to a message
        if not update.message.reply_to_message:
            update.message.reply_text("Команда /unban должна быть ответом на сообщение пользователя.")
            return

        # Get the target user ID
        target_user = update.message.reply_to_message.from_user
        target_user_id = target_user.id
        target_username = target_user.username or target_user.first_name

        # Remove the user from muted_users and banned_users
        was_muted = muted_users.pop(target_user_id, None) is not None
        was_banned = banned_users.pop(target_user_id, None) is not None

        if was_muted or was_banned:
            update.message.reply_text(f"Пользователь @{target_username} был разблокирован.")
        else:
            update.message.reply_text(f"Пользователь @{target_username} не был замьючен или забанен.")
    except Exception as e:
        logger.error(f"Ошибка в unban_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def main():
    updater = Updater(token=TELEGRAM_API_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Command Handlers
    dispatcher.add_handler(CommandHandler('mute', mute_user))
    dispatcher.add_handler(CommandHandler('ban', ban_user))
    dispatcher.add_handler(CommandHandler('unban', unban_user))

    # Message Handlers
    dispatcher.add_handler(MessageHandler(Filters.all, handle_message))
    dispatcher.add_handler(MessageHandler(Filters.update.edited_message, handle_edited_message))

    # Start the bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
