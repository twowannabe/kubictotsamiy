import logging
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

FIXED_USER_ID = config('FIXED_USER_ID', cast=int)  # загружаем user_id из .env

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

def get_user_messages():
    try:
        with conn.cursor() as cur:
            query = "SELECT text FROM messages WHERE user_id = %s AND text IS NOT NULL ORDER BY date ASC"
            cur.execute(query, (FIXED_USER_ID,))
            messages = cur.fetchall()
            return [msg[0] for msg in messages if msg[0]]
    except Exception as e:
        logger.error(f"Ошибка при получении сообщений пользователя: {e}")
        return []

def generate_answer(user_messages, user_question):
    prompt = "Вы — помощник, который отвечает на вопросы пользователя, основываясь на его предыдущих сообщениях.\n\n"
    prompt += "Предыдущие сообщения пользователя:\n"
    prompt += "\n".join(user_messages)
    prompt += f"\n\nВопрос пользователя: {user_question}\nОтвет:"

    try:
        response = openai.Completion.create(
            engine='gpt-4',
            prompt=prompt,
            max_tokens=150,
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

        # Получаем ID пользователя, который отправил сообщение
        user_question = update.message.text.strip()

        # Логируем вопрос пользователя
        logger.info(f"Вопрос пользователя: {user_question}")

        # Получаем сообщения пользователя с фиксированным user_id из .env
        user_messages = get_user_messages()

        # Логируем полученные сообщения из базы данных
        logger.info(f"Сообщения пользователя: {user_messages}")

        if not user_messages:
            update.message.reply_text("Нет сохраненных сообщений для формирования ответа.")
            return

        # Генерируем ответ на основе сообщений пользователя
        answer = generate_answer(user_messages, user_question)

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
