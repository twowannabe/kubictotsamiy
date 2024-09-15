import logging
import re
from decouple import config
import psycopg2
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext
from telegram import Update
import openai

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

# Функция для очистки вопроса
def clean_question(question):
    """Удаляет упоминания и специальные символы из вопроса."""
    # Удаление упоминаний бота (@username)
    question = re.sub(r'@\w+', '', question)
    # Удаление лишних пробелов
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
            search_pattern = f"%{topic}%"  # поиск фразы в любом месте сообщения
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

def generate_answer_by_topic(user_question, related_messages, max_chars=1000):
    """Генерация ответа на основе сообщений, содержащих ключевые слова из вопроса."""
    # Урезаем найденные сообщения, чтобы не превышать лимит символов
    truncated_messages = truncate_messages(related_messages, max_chars)

    prompt = "Вы — помощник, который отвечает на вопросы пользователя, основываясь на его предыдущих сообщениях.\n\n"
    prompt += "Сообщения, содержащие информацию по теме:\n"
    prompt += "\n".join(truncated_messages)
    prompt += f"\n\nВопрос пользователя: {user_question}\nОтвет:"

    try:
        response = openai.Completion.create(
            engine='gpt-4o-mini',  # Используем gpt-4o-mini
            prompt=prompt,
            max_tokens=150,  # Уменьшаем максимальное количество токенов для экономии
            n=1,
            stop=None,
            temperature=0.7,
        )
        answer = response.choices[0].text.strip()
        return answer
    except Exception as e:
        logger.error(f"Ошибка при запросе к OpenAI API: {e}")
        return "Извините, произошла ошибка при генерации ответа."

def handle_message(update: Update, context: CallbackContext):
    try:
        # Логируем информацию о сообщении
        logger.info(f"handle_message вызван для пользователя {update.effective_user.id} в чате {update.effective_chat.id}")
        logger.info(f"Текст сообщения: {update.message.text}")

        # Получаем вопрос пользователя и очищаем его от упоминаний бота
        user_question = update.message.text.strip()
        clean_topic = clean_question(user_question)

        # Логируем очищенный вопрос
        logger.info(f"Очищенный вопрос пользователя: {clean_topic}")

        # Поиск сообщений, связанных с темой вопроса
        related_messages = search_messages_by_topic(clean_topic)

        # Логируем найденные сообщения
        logger.info(f"Найденные сообщения по теме '{clean_topic}': {related_messages}")

        if not related_messages:
            update.message.reply_text("Не удалось найти сообщения, связанные с вашим вопросом.")
            return

        # Генерируем ответ на основе найденных сообщений
        answer = generate_answer_by_topic(user_question, related_messages)

        # Логируем сгенерированный ответ
        logger.info(f"Ответ: {answer}")

        # Отправляем ответ пользователю
        update.message.reply_text(answer)

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
