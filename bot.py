import logging
from decouple import config
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler
from telegram import Update
from datetime import datetime, timedelta
import openai
import psycopg2
import re

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных из .env файла
TELEGRAM_API_TOKEN = config('TELEGRAM_API_TOKEN')
openai.api_key = config('OPENAI_API_KEY')

DB_NAME = config('DB_NAME')
DB_USER = config('DB_USER')
DB_PASSWORD = config('DB_PASSWORD')
DB_HOST = config('DB_HOST')
DB_PORT = config('DB_PORT')

# Фиксированный идентификатор пользователя
FIXED_USER_ID = int(config('FIXED_USER_ID'))

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
    logger.info("Успешно подключились к базе данных PostgreSQL")
except Exception as e:
    logger.error(f"Ошибка подключения к базе данных: {e}")
    exit(1)

# Списки замьюченных и забаненных пользователей
muted_users = {}
banned_users = {}

def check_and_remove_ban():
    """Проверяет время и снимает бан с пользователей"""
    now = datetime.now()
    to_remove = [user for user, unban_time in banned_users.items() if now >= unban_time]

    # Удаление пользователей, чей бан истек
    for user in to_remove:
        del banned_users[user]

def delete_banned_user_message(update: Update, context: CallbackContext) -> bool:
    """Удаляет сообщения забаненных пользователей и возвращает True, если сообщение было удалено"""
    check_and_remove_ban()

    # Проверяем, есть ли сообщение в обновлении
    if update.message and update.message.from_user:
        if update.message.from_user.id in banned_users:
            try:
                context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
                logger.info(f"Сообщение от пользователя с ID {update.message.from_user.id} было удалено, так как он забанен.")
                return True
            except Exception as e:
                logger.error(f"Ошибка при удалении сообщения забаненного пользователя: {e}")
                return False
    return False

def delete_muted_user_message(update: Update, context: CallbackContext) -> bool:
    """Удаляет сообщения замьюченных пользователей и возвращает True, если сообщение было удалено"""
    check_and_remove_mute()

    # Проверяем, есть ли сообщение в обновлении
    if update.message and update.message.from_user:
        username = update.message.from_user.username

        if username in muted_users:
            # Если сообщение начинается с команды (слэш)
            if update.message.text.startswith("/"):
                try:
                    context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
                    logger.info(f"Сообщение команды от {username} было удалено, так как он замьючен.")
                    return True
                except Exception as e:
                    logger.error(f"Ошибка при удалении команды от {username}: {e}")
                    return False

            try:
                context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
                logger.info(f"Сообщение от {username} было удалено, так как он замьючен.")
                return True
            except Exception as e:
                logger.error(f"Ошибка при удалении сообщения от {username}: {e}")
                return False
    return False


def check_and_remove_mute():
    """Проверяет время и снимает мьют с пользователей"""
    now = datetime.now()
    to_remove = [user for user, unmute_time in muted_users.items() if now >= unmute_time]

    for user in to_remove:
        del muted_users[user]

def truncate_to_ten_words(text):
    """Ограничивает текст до 10 слов"""
    words = text.split()
    if len(words) > 20:
        return " ".join(words[:20]) + "..."
    return text

def extract_keywords_from_question(question):
    """Извлекает ключевые слова из вопроса пользователя."""
    clean_question = re.sub(r'[^\w\s]', '', question).lower()
    keywords = clean_question.split()
    return keywords

def search_messages_by_keywords(keywords, limit=50):
    """Поиск сообщений по ключевым словам в базе данных для FIXED_USER_ID, с ограничением на количество."""
    try:
        cur = conn.cursor()
        # Формируем SQL запрос для поиска сообщений с фильтрацией по user_id и ограничением по количеству (LIMIT)
        query = f"SELECT text FROM messages WHERE user_id = %s AND (" + " OR ".join([f"text ILIKE %s" for _ in keywords]) + f") LIMIT {limit}"
        cur.execute(query, [FIXED_USER_ID] + [f"%{keyword}%" for keyword in keywords])
        messages = [row[0] for row in cur.fetchall()]
        cur.close()

        # Логируем найденные сообщения
        logger.info(f"Найденные сообщения для FIXED_USER_ID: {messages}")

        return messages
    except Exception as e:
        logger.error(f"Ошибка при поиске сообщений в базе данных: {e}")
        return []

def generate_answer_by_topic(user_question, related_messages):
    """Генерация ответа на основе сообщений, содержащих ключевые слова из вопроса."""
    truncated_messages = " ".join(related_messages)

    # Логируем найденные сообщения
    logger.info(f"Найденные сообщения для генерации ответа: {truncated_messages}")

    prompt = f"На основе приведенных ниже сообщений пользователя, сформулируй связное мнение от его имени. \n\nСообщения пользователя:\n{truncated_messages}\n\nВопрос пользователя: {user_question}\nОтвет:"

    try:
        # Логируем отправляемый запрос
        logger.info(f"Запрос в OpenAI: {prompt}")

        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",  # Используйте выбранную модель
            messages=[
                {"role": "system", "content": "Ты помощник, который отвечает от имени пользователя на основании его сообщений."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=250,  # Оставляем достаточно токенов для ответа
            n=1,
            stop=None,
            temperature=0.7,
        )
        answer = response['choices'][0]['message']['content'].strip()

        # Ограничиваем текст до 10 слов
        short_answer = truncate_to_ten_words(answer)

        # Логируем полученный ответ от OpenAI
        logger.info(f"Ответ OpenAI: {short_answer}")

        return short_answer  # Возвращаем ограниченный ответ
    except Exception as e:
        logger.error(f"Ошибка при запросе к OpenAI API: {e}")
        return ""

def should_respond_to_message(update: Update, context: CallbackContext) -> bool:
    """Проверяет, нужно ли отвечать на сообщение (если упомянули бота или это ответ на его сообщение)."""
    message = update.message

    # Проверяем, упомянули ли бота
    if message.entities:
        for entity in message.entities:
            mention = message.text[entity.offset:entity.offset + entity.length].lower()
            if entity.type == 'mention' and mention == f"@{context.bot.username.lower()}":
                return True

    # Проверяем, является ли сообщение ответом на сообщение бота
    if message.reply_to_message and message.reply_to_message.from_user.id == context.bot.id:
        return True

    return False

def handle_message(update: Update, context: CallbackContext):
    """Обработка входящих сообщений и удаление их, если пользователь замьючен."""

    # Проверяем, если сообщение существует
    if not update.message:
        logger.error("Сообщение не найдено в обновлении.")
        return

    user_id = update.message.from_user.id
    username = update.message.from_user.username

    logger.info(f"Получено сообщение от пользователя {username} (ID: {user_id}): {update.message.text}")

    # Удаляем сообщения от замьюченных пользователей
    if user_id in muted_users:
        logger.info(f"Пользователь {username} (ID: {user_id}) замьючен. Удаление сообщения.")
        try:
            context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
            logger.info(f"Сообщение от замьюченного пользователя {username} (ID: {user_id}) было удалено.")
            return
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения от замьюченного пользователя {username} (ID: {user_id}): {e}")
            return
    else:
        logger.info(f"Пользователь {username} (ID: {user_id}) не замьючен.")

    # Проверяем, если сообщение от забаненного пользователя
    message_deleted = delete_banned_user_message(update, context)

    # Если сообщение не было удалено как забаненное, проверяем дальнейшую обработку
    if not message_deleted and should_respond_to_message(update, context):
        user_question = update.message.text.strip()

        # Извлекаем ключевые слова из вопроса
        keywords = extract_keywords_from_question(user_question)

        if keywords:
            # Логируем ключевые слова, по которым будем искать сообщения
            logger.info(f"Начинаем поиск сообщений по ключевым словам: {keywords}")

            related_messages = search_messages_by_keywords(keywords)

            if related_messages:
                # Генерируем ответ с помощью OpenAI
                answer = generate_answer_by_topic(user_question, related_messages)
                if answer:
                    logger.info(f"Ответ: {answer}")
                    update.message.reply_text(answer)
            else:
                logger.info("Сообщений по ключевым словам не найдено.")
        else:
            logger.info("Ключевые слова не были извлечены.")

def mute_user(update: Update, context: CallbackContext):
    """Command to mute a user"""
    try:
        user_id = update.message.from_user.id

        # Check if the user is authorized
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"User {user_id} attempted to use /mute command but is not authorized.")
            update.message.reply_text("You are not authorized to use this command.")
            return

        if not context.args or len(context.args) < 1:
            update.message.reply_text("Usage: /mute minutes\nYou need to reply to the user's message.")
            return

        mute_duration = int(context.args[0])

        # Check if the command is a reply to a message
        if not update.message.reply_to_message:
            update.message.reply_text("The /mute command must be used in reply to the user's message.")
            return

        # Get the target user ID
        target_user_id = update.message.reply_to_message.from_user.id

        # Determine when to unmute
        unmute_time = datetime.now() + timedelta(minutes=mute_duration)
        muted_users[target_user_id] = unmute_time

        update.message.reply_text(f"User has been muted for {mute_duration} minutes.")
    except Exception as e:
        logger.error(f"Error in mute_user: {e}")
        update.message.reply_text("An error occurred while executing the command.")

def ban_user(update: Update, context: CallbackContext):
    """Команда для бана пользователя"""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /ban, но не имеет прав.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        # Проверяем, является ли команда ответом на сообщение
        if not update.message.reply_to_message:
            update.message.reply_text("Команда /ban должна быть ответом на сообщение пользователя.")
            return

        # Получаем user_id пользователя, которого банят
        target_user_id = update.message.reply_to_message.from_user.id

        # Определяем, когда снять бан (через 10 минут)
        ban_end_time = datetime.now() + timedelta(minutes=10)
        banned_users[target_user_id] = ban_end_time

        update.message.reply_text(f"Пользователь с ID {target_user_id} забанен на 10 минут.")
    except Exception as e:
        logger.error(f"Ошибка в ban_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def unban_user(update: Update, context: CallbackContext):
    """Unbans a user by removing them from banned_users and muted_users."""
    try:
        user_id = update.message.from_user.id

        # Check if the user is authorized
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"User {user_id} attempted to use /unban command but is not authorized.")
            update.message.reply_text("You are not authorized to use this command.")
            return

        # Check if the command is a reply to a message
        if not update.message.reply_to_message:
            update.message.reply_text("The /unban command must be used in reply to the user's message.")
            return

        # Get the target user ID
        target_user_id = update.message.reply_to_message.from_user.id

        # Remove the user from muted_users and banned_users
        muted_users.pop(target_user_id, None)
        banned_users.pop(target_user_id, None)

        update.message.reply_text(f"User has been unbanned/unmuted.")
    except Exception as e:
        logger.error(f"Error in unban_user: {e}")
        update.message.reply_text("An error occurred while executing the command.")

def main():
    updater = Updater(token=TELEGRAM_API_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Обработчик команд
    dispatcher.add_handler(CommandHandler('mute', mute_user))
    dispatcher.add_handler(CommandHandler('ban', ban_user))
    dispatcher.add_handler(CommandHandler('unban', unban_user))

    # Обработчик текстовых сообщений
    dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_message))

    # Запуск бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
