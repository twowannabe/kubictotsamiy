import logging
import re
from decouple import config
import psycopg2
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext
from telegram import Update
import openai
import string
import random

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

    # 1. Проверяем, если бот упомянут в сообщении
    if message.entities:
        for entity in message.entities:
            if entity.type == 'mention' and message.text[entity.offset:entity.offset + entity.length].lower() == f"@{context.bot.username.lower()}":
                return True

    # 2. Проверяем, если это ответ на сообщение бота
    if message.reply_to_message and message.reply_to_message.from_user.id == context.bot.id:
        return True

    # Если ни одно условие не выполнено, бот не должен отвечать
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

        return answer
    except Exception as e:
        logger.error(f"Ошибка при запросе к OpenAI API: {e}")
        return "Извините, произошла ошибка при генерации ответа."

def handle_message(update: Update, context: CallbackContext):
    try:
        if not should_respond_to_message(update, context):
            return

        user_question = update.message.text.strip()
        clean_topic = clean_question(user_question)

        extracted_keyword = extract_keywords(clean_topic)

        related_messages = search_messages_by_topic(extracted_keyword)

        if not related_messages:
            update.message.reply_text("Не удалось найти сообщения, связанные с вашим вопросом.")
            return

        # Получаем user_id для анализа длины сообщений
        user_id = update.message.from_user.id

        # Генерируем ответ с учётом средней длины сообщений пользователя
        answer = generate_answer_by_topic(user_question, related_messages, user_id)

        update.message.reply_text(answer)

    except Exception as e:
        logger.error(f"Ошибка в handle_message: {e}")
        update.message.reply_text("Извините, произошла ошибка при обработке вашего сообщения.")

    except Exception as e:
        logger.error(f"Ошибка в handle_message: {e}")
        update.message.reply_text("Извините, произошла ошибка при обработке вашего сообщения.")

def log_update(update: Update, context: CallbackContext):
    logger.info(f"Получено обновление: {update}")

def error_handler(update: object, context: CallbackContext):
    logger.error(msg="Исключение при обработке обновления:", exc_info=context.error)

def main():
    updater = Updater(token=TELEGRAM_API_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Изменяем фильтр, чтобы он ловил любые текстовые сообщения, кроме команд
    dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_message))

    # Логирование всех обновлений
    dispatcher.add_handler(MessageHandler(Filters.all, log_update))

    dispatcher.add_error_handler(error_handler)

    updater.start_polling()
    logger.info("Бот запущен. Нажмите Ctrl+C для остановки.")
    updater.idle()

if __name__ == '__main__':
    main()
