import logging
import re
from decouple import config
import psycopg2
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler
from telegram import Update
import openai
import string
import random
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# Загрузка переменных из .env файла
openai.api_key = config('OPENAI_API_KEY')
TELEGRAM_API_TOKEN = config('TELEGRAM_API_TOKEN')

DB_NAME = config('DB_NAME')
DB_USER = config('DB_USER')
DB_PASSWORD = config('DB_PASSWORD')
DB_HOST = config('DB_HOST')
DB_PORT = config('DB_PORT')

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

def introduce_typos(text):
    """Функция для добавления случайных ошибок в текст."""
    words = text.split()

    for i, word in enumerate(words):
        if word == "и" and random.random() < 0.3:
            continue
        if random.random() < 0.2:
            if 'с' in word:
                words[i] = word.replace('с', 'з')
            if 'в' in word:
                words[i] = word.replace('в', 'ф')

    return ' '.join(words)

def randomize_case(text):
    """Случайным образом меняет регистр первой буквы в предложении."""
    if random.random() < 0.5:
        return text[0].lower() + text[1:]
    return text

def should_respond_to_message(update: Update, context: CallbackContext) -> bool:
    """Проверяет, нужно ли отвечать на сообщение (если упомянули бота или это ответ на его сообщение)."""
    message = update.message
    bot_username = context.bot.username.lower()
    logger.info(f"Имя бота: {bot_username}")

    # 1. Проверяем, если бот упомянут в сообщении
    if message.entities:
        for entity in message.entities:
            mention = message.text[entity.offset:entity.offset + entity.length].lower()
            logger.info(f"Упоминание в сообщении: {mention}")
            if entity.type == 'mention' and mention == f"@{bot_username}":
                logger.info(f"Бот был упомянут: {mention}")
                return True

    # 2. Проверяем, если это ответ на сообщение бота
    if message.reply_to_message and message.reply_to_message.from_user.id == context.bot.id:
        logger.info("Сообщение является ответом на сообщение бота.")
        return True

    logger.info("Бот не был упомянут, и это не ответ на его сообщение.")
    return False

def extract_keywords(question):
    """Извлекает ключевые слова из вопроса для поиска."""
    keywords = question.split()
    if keywords:
        last_word = keywords[-1]
        last_word = last_word.rstrip(string.punctuation)
        return last_word
    return question

def clean_question(question):
    """Удаляет упоминания и специальные символы из вопроса."""
    question = re.sub(r'@\w+', '', question)
    question = question.strip()
    return question

def search_messages_by_topic(topic, limit=10):
    """Поиск сообщений в базе данных, содержащих ключевые слова из вопроса."""
    try:
        with conn.cursor() as cur:
            query = """
                SELECT text
                FROM messages
                WHERE text ILIKE %s
                ORDER BY date ASC
                LIMIT %s
            """
            search_pattern = f"%{topic}%"
            cur.execute(query, (search_pattern, limit))
            messages = cur.fetchall()
            return [msg[0] for msg in messages if msg[0]]
    except Exception as e:
        logger.error(f"Ошибка при поиске сообщений по теме: {e}")
        return []

def truncate_messages(messages, max_chars=1000):
    """Усечение сообщений до максимального количества символов"""
    combined_messages = " ".join(messages)
    if len(combined_messages) > max_chars:
        return combined_messages[:max_chars] + "..."
    return combined_messages

def truncate_to_max_chars(text, max_chars=200):
    """Ограничивает длину текста до определенного количества символов"""
    if len(text) > max_chars:
        return text[:max_chars] + "..."
    return text

def get_average_message_length(user_id):
    """Извлекает среднюю длину сообщений пользователя из базы данных."""
    try:
        with conn.cursor() as cur:
            query = """
                SELECT AVG(CHAR_LENGTH(text))
                FROM messages
                WHERE user_id = %s
            """
            cur.execute(query, (user_id,))
            avg_length = cur.fetchone()[0]
            return avg_length if avg_length else 100  # Возвращаем 100 по умолчанию
    except Exception as e:
        logger.error(f"Ошибка при извлечении средней длины сообщений: {e}")
        return 100  # Значение по умолчанию

def generate_answer_by_topic(user_question, related_messages, user_id, max_chars=1000):
    """Генерация ответа на основе сообщений, содержащих ключевые слова из вопроса."""
    truncated_messages = truncate_messages(related_messages, max_chars)

    # Получаем среднюю длину сообщений пользователя
    avg_message_length = get_average_message_length(user_id)

    prompt = "На основе приведенных ниже сообщений пользователя, сформулируйте связное мнение от его имени, сохраняя стиль, пунктуацию и грамматику сообщений, а также добавьте случайные ошибки для имитации человеческого текста.\n\n"
    prompt += "Сообщения пользователя:\n"
    prompt += "\n".join(truncated_messages)
    prompt += f"\n\nВопрос пользователя: {user_question}\nОтвет от имени автора, с сохранением его стиля и ошибок:"

    try:
        logger.info(f"Запрос к OpenAI API: {prompt}")
        response = openai.ChatCompletion.create(
            model='gpt-4o-mini',
            messages=[
                {"role": "system", "content": "Вы помощник, который формирует связное мнение на основе сообщений пользователя, сохраняя его стиль, пунктуацию и грамматику. Добавляйте случайные ошибки, чтобы текст выглядел естественным."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=int(avg_message_length // 2),  # Ограничиваем длину на основе средней длины сообщений
            n=1,
            stop=None,
            temperature=0.7,
        )
        answer = response['choices'][0]['message']['content'].strip()

        answer = randomize_case(answer)
        answer = introduce_typos(answer)

        logger.info(f"Ответ от OpenAI API: {answer}")
        return answer
    except Exception as e:
        logger.error(f"Ошибка при запросе к OpenAI API: {e}")
        return "Извините, произошла ошибка при генерации ответа."

def handle_message(update: Update, context: CallbackContext):
    try:
        if not should_respond_to_message(update, context):
            logger.info("Сообщение не требует ответа.")
            return

        # Логируем, что бот решил ответить на сообщение
        logger.info("Бот готовит ответ на сообщение.")

        user_question = update.message.text.strip()
        clean_topic = clean_question(user_question)

        extracted_keyword = extract_keywords(clean_topic)

        related_messages = search_messages_by_topic(extracted_keyword)

        if not related_messages:
            logger.info(f"Сообщения, связанные с темой '{extracted_keyword}', не найдены.")
            update.message.reply_text("Не удалось найти сообщения, связанные с вашим вопросом.")
            return

        user_id = update.message.from_user.id
        answer = generate_answer_by_topic(user_question, related_messages, user_id)

        # Ограничение длины ответа
        answer = truncate_to_max_chars(answer, max_chars=200)

        # Логируем сгенерированный ответ
        logger.info(f"Ответ на сообщение: {answer}")

        update.message.reply_text(answer)

    except Exception as e:
        logger.error(f"Ошибка в handle_message: {e}")
        update.message.reply_text("Извините, произошла ошибка при обработке вашего сообщения.")

def log_all_messages(update: Update, context: CallbackContext):
    """Логирование всех сообщений."""
    user = update.message.from_user
    message_text = update.message.text if update.message.text else "Не текстовое сообщение"

    # Логирование информации о пользователе и тексте сообщения
    logger.info(f"Получено сообщение от {user.username} ({user.id}): {message_text}")

    # Если это не текстовое сообщение, можем дополнительно логировать тип контента
    if update.message.sticker:
        logger.info(f"Стикер: {update.message.sticker.emoji}")
    elif update.message.photo:
        logger.info(f"Фото от пользователя {user.username}")
    elif update.message.video:
        logger.info(f"Видео от пользователя {user.username}")
    elif update.message.document:
        logger.info(f"Документ от пользователя {user.username}")
    elif update.message.voice:
        logger.info(f"Голосовое сообщение от пользователя {user.username}")
    elif update.message.location:
        logger.info(f"Локация от пользователя {user.username}")

def check_and_remove_mute():
    """Проверяет время и снимает мьют с пользователей"""
    now = datetime.now()
    to_remove = [user for user, unmute_time in muted_users.items() if now >= unmute_time]

    for user in to_remove:
        del muted_users[user]

def delete_muted_user_message(update: Update, context: CallbackContext):
    """Удаляет сообщения замьюченных пользователей"""
    check_and_remove_mute()

    if update.message.from_user.username in muted_users:
        # Удаляем сообщение
        try:
            context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
            logger.info(f"Сообщение от {update.message.from_user.username} было удалено, так как он замьючен.")
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")

def mute_user(update: Update, context: CallbackContext):
    """Команда для мьюта пользователя"""
    try:
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

def error_handler(update: object, context: CallbackContext):
    """Логирует все исключения, которые возникают во время обработки сообщений."""
    logger.error(msg="Исключение при обработке обновления:", exc_info=context.error)

def main():
    updater = Updater(token=TELEGRAM_API_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # 1. Обработчик команд
    dispatcher.add_handler(CommandHandler('mute', mute_user))

    # 2. Обработчик для удаления сообщений замьюченных пользователей
    dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), delete_muted_user_message))

    # 3. Обработчик сообщений, на которые нужно отвечать
    dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_message))

    # 4. Обработчик для логирования всех сообщений (в конце)
    dispatcher.add_handler(MessageHandler(Filters.all, log_all_messages))

    # 5. Обработчик ошибок
    dispatcher.add_error_handler(error_handler)

    # Запуск бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
