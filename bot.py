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

AUTHORIZED_USERS = [530674302, 6122780749, 147218177, 336914967]

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

# Список замьюченных пользователей
muted_users = {}


def search_messages_by_keywords(keywords, limit=1000):
    """Поиск сообщений в базе данных, содержащих одно из ключевых слов и отправленных фиксированным пользователем."""
    try:
        with conn.cursor() as cur:
            # Формируем условие для поиска по нескольким ключевым словам
            search_conditions = " OR ".join([f"text ILIKE %s" for _ in keywords])
            query = f"""
                SELECT text
                FROM messages
                WHERE ({search_conditions}) AND user_id = %s
                ORDER BY date ASC
                LIMIT %s
            """
            search_patterns = [f"%{keyword}%" for keyword in keywords]
            logger.info(f"Поиск сообщений с ключевыми словами: {keywords}")  # Логирование ключевых слов поиска
            cur.execute(query, (*search_patterns, FIXED_USER_ID, limit))
            messages = cur.fetchall()

            # Логируем все найденные сообщения
            if messages:
                logger.info(f"Найденные сообщения по ключевым словам '{keywords}': {messages}")
            else:
                logger.info(f"Сообщения по ключевым словам '{keywords}' не найдены.")

            return [msg[0] for msg in messages if msg[0]]
    except Exception as e:
        logger.error(f"Ошибка при поиске сообщений по ключевым словам: {e}")
        return []

def extract_keywords_from_question(question):
    """Извлекает ключевые слова из вопроса"""
    # Убираем стоп-слова и лишние символы
    stop_words = {"что", "как", "про", "думаешь", "о", "и", "в", "на", "по", "ты", "это"}
    words = re.findall(r'\b\w+\b', question.lower())
    keywords = [word for word in words if word not in stop_words]

    # Возвращаем список ключевых слов
    return keywords if keywords else question.split()

def check_and_remove_mute():
    """Проверяет время и снимает мьют с пользователей"""
    now = datetime.now()
    to_remove = [user for user, unmute_time in muted_users.items() if now >= unmute_time]

    for user in to_remove:
        del muted_users[user]

def delete_muted_user_message(update: Update, context: CallbackContext) -> bool:
    """Удаляет сообщения замьюченных пользователей и возвращает True, если сообщение было удалено"""
    check_and_remove_mute()

    username = update.message.from_user.username

    if username in muted_users:
        try:
            context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
            logger.info(f"Сообщение от {username} было удалено, так как он замьючен.")
            return True
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения от {username}: {e}")
            return False
    return False

def should_respond_to_message(update: Update, context: CallbackContext) -> bool:
    """Проверяет, нужно ли отвечать на сообщение"""
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

def extract_topic_from_question(question):
    """Использует OpenAI для анализа вопроса и извлечения основной темы с помощью чат-модели"""
    prompt = f"Определи ключевую тему вопроса: '{question}' и верни только ключевую тему одним словом."

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ты помощник, который извлекает ключевую тему вопроса."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=5,
            n=1,
            stop=None,
            temperature=0.5
        )
        topic = response['choices'][0]['message']['content'].strip()
        logger.info(f"Извлеченная тема: {topic}")  # Логирование ключевой темы
        return topic
    except Exception as e:
        logger.error(f"Ошибка при анализе темы вопроса с помощью OpenAI: {e}")
        return None

def search_messages_by_topic(topic, limit=50):
    """Поиск сообщений в базе данных, содержащих ключевые слова из вопроса и отправленных фиксированным пользователем."""
    try:
        with conn.cursor() as cur:
            query = """
                SELECT text
                FROM messages
                WHERE text ILIKE %s AND user_id = %s
                ORDER BY date ASC
                LIMIT %s
            """
            search_pattern = f"%{topic}%"
            logger.info(f"Поиск сообщений с темой: {topic}")  # Логирование ключевого слова поиска
            cur.execute(query, (search_pattern, FIXED_USER_ID, limit))
            messages = cur.fetchall()
            return [msg[0] for msg in messages if msg[0]]
    except Exception as e:
        logger.error(f"Ошибка при поиске сообщений по теме: {e}")
        return []

def truncate_messages(messages, max_chars=500):
    """Усечение сообщений до максимального количества символов"""
    combined_messages = " ".join(messages)
    if len(combined_messages) > max_chars:
        return combined_messages[:max_chars] + "..."
    return combined_messages

def generate_answer_by_topic(user_question, related_messages, max_chars=500):
    """Генерация ответа на основе сообщений, содержащих ключевые слова из вопроса."""
    truncated_messages = truncate_messages(related_messages, max_chars)

    prompt = f"На основе приведенных ниже сообщений пользователя, сформулируй связное мнение от его имени. \n\nСообщения пользователя:\n{truncated_messages}\n\nВопрос пользователя: {user_question}\nОтвет:"

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ты помощник, который отвечает от имени пользователя на основании его сообщений."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=100,  # Уменьшаем длину ответа
            n=1,
            stop=None,
            temperature=0.7,
        )
        answer = response['choices'][0]['message']['content'].strip()
        return answer
    except Exception as e:
        logger.error(f"Ошибка при запросе к OpenAI API: {e}")
        return ""

def handle_message(update: Update, context: CallbackContext):
    """Обработка текстовых сообщений"""
    message_deleted = delete_muted_user_message(update, context)

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
            # Если нет сообщений или ответа, бот просто не отвечает

def mute_user(update: Update, context: CallbackContext):
    """Команда для мьюта пользователя"""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /mute, но не имеет прав.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        if not context.args or len(context.args) < 2:
            update.message.reply_text("Использование: /mute username minutes")
            return

        username = context.args[0].lstrip('@')
        mute_duration = int(context.args[1])

        # Определяем, когда снять мьют
        unmute_time = datetime.now() + timedelta(minutes=mute_duration)
        muted_users[username] = unmute_time

        update.message.reply_text(f"Пользователь {username} замьючен на {mute_duration} минут.")
    except Exception as e:
        logger.error(f"Ошибка в mute_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def main():
    updater = Updater(token=TELEGRAM_API_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Обработчик команд
    dispatcher.add_handler(CommandHandler('mute', mute_user))

    # Обработчик текстовых сообщений
    dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_message))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
