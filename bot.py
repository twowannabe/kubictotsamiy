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
    conn.autocommit = True  # Включаем автокоммит для упрощения транзакций
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
    to_remove = [user_id for user_id, unban_time in banned_users.items() if now >= unban_time]

    for user_id in to_remove:
        del banned_users[user_id]
        logger.info(f"Бан пользователя с ID {user_id} истек и был снят.")

def check_and_remove_mute():
    """Проверяет время и снимает мьют с пользователей"""
    now = datetime.now()
    to_remove = [user_id for user_id, unmute_time in muted_users.items() if now >= unmute_time]

    for user_id in to_remove:
        del muted_users[user_id]
        logger.info(f"Мьют пользователя с ID {user_id} истек и был снят.")

def delete_banned_user_message(update: Update, context: CallbackContext) -> bool:
    """Удаляет сообщения забаненных пользователей и возвращает True, если сообщение было удалено"""
    check_and_remove_ban()

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

def extract_keywords_from_question(question):
    """Извлекает ключевые слова из вопроса пользователя."""
    clean_question = re.sub(r'[^\w\s]', '', question).lower()
    keywords = clean_question.split()
    return keywords

def search_messages_by_keywords(keywords, limit=50):
    """Поиск сообщений по ключевым словам в базе данных для FIXED_USER_ID, с ограничением на количество."""
    try:
        cur = conn.cursor()
        query = f"SELECT text FROM messages WHERE user_id = %s AND (" + " OR ".join([f"text ILIKE %s" for _ in keywords]) + f") LIMIT {limit}"
        cur.execute(query, [FIXED_USER_ID] + [f"%{keyword}%" for keyword in keywords])
        messages = [row[0] for row in cur.fetchall()]
        cur.close()

        logger.info(f"Найденные сообщения для FIXED_USER_ID: {messages}")

        return messages
    except Exception as e:
        logger.error(f"Ошибка при поиске сообщений в базе данных: {e}")
        return []

def generate_answer_by_topic(user_question, related_messages):
    """Генерация ответа на основе сообщений, содержащих ключевые слова из вопроса."""
    truncated_messages = " ".join(related_messages)

    logger.info(f"Найденные сообщения для генерации ответа: {truncated_messages}")

    prompt = f"На основе приведенных ниже сообщений пользователя, сформулируй связное мнение от его имени.\n\nСообщения пользователя:\n{truncated_messages}\n\nВопрос пользователя: {user_question}\nОтвет:"

    try:
        logger.info(f"Запрос в OpenAI: {prompt}")

        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",  # Используйте выбранную модель
            messages=[
                {"role": "system", "content": "Ты помощник, который отвечает от имени пользователя на основании его сообщений."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=250,
            n=1,
            stop=None,
            temperature=0.7,
        )
        answer = response['choices'][0]['message']['content'].strip()

        # Ограничиваем текст до 20 слов
        words = answer.split()
        if len(words) > 20:
            short_answer = " ".join(words[:20]) + "..."
        else:
            short_answer = answer

        logger.info(f"Ответ OpenAI: {short_answer}")

        return short_answer
    except Exception as e:
        logger.error(f"Ошибка при запросе к OpenAI API: {e}")
        return ""

def should_respond_to_message(update: Update, context: CallbackContext) -> bool:
    """Проверяет, нужно ли отвечать на сообщение (если упомянули бота или это ответ на его сообщение)."""
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
    """Обработка входящих сообщений и удаление их, если пользователь замьючен или забанен."""
    if not update.message:
        logger.error("Сообщение не найдено в обновлении.")
        return

    user_id = update.message.from_user.id
    username = update.message.from_user.username
    chat_id = update.message.chat_id
    message_id = update.message.message_id
    message_text = update.message.text

    logger.info(f"Получено сообщение от пользователя {username} (ID: {user_id}): {message_text}")

    # Проверяем и снимаем истекшие мьюты и баны
    check_and_remove_mute()
    check_and_remove_ban()

    # Удаляем сообщения от замьюченных или забаненных пользователей
    if user_id in muted_users or user_id in banned_users:
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

    # Продолжайте обработку других сообщений, если необходимо
    # Например, отвечать на сообщения, если бот упомянут
    if should_respond_to_message(update, context):
        user_question = message_text.strip()

        # Извлекаем ключевые слова из вопроса
        keywords = extract_keywords_from_question(user_question)

        if keywords:
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

def handle_edited_message(update: Update, context: CallbackContext):
    """Обработка отредактированных сообщений и удаление их, если пользователь замьючен или забанен."""
    if not update.edited_message:
        logger.error("Отредактированное сообщение не найдено в обновлении.")
        return

    user_id = update.edited_message.from_user.id
    username = update.edited_message.from_user.username
    chat_id = update.edited_message.chat_id
    message_id = update.edited_message.message_id
    message_text = update.edited_message.text

    logger.info(f"Пользователь {username} (ID: {user_id}) отредактировал сообщение: {message_text}")

    # Проверяем и снимаем истекшие мьюты и баны
    check_and_remove_mute()
    check_and_remove_ban()

    # Удаляем отредактированные сообщения от замьюченных или забаненных пользователей
    if user_id in muted_users or user_id in banned_users:
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
    """Команда для мьюта пользователя (используется как ответ на сообщение пользователя)"""
    try:
        user_id = update.message.from_user.id

        # Проверяем, находится ли пользователь в списке авторизованных
        if user_id not in AUTHORIZED_USERS:
            logger.info(f"Пользователь {user_id} попытался использовать команду /mute, но не имеет прав.")
            update.message.reply_text("У вас нет прав на использование этой команды.")
            return

        if not context.args or len(context.args) < 1:
            update.message.reply_text("Использование: /mute минуты\nНеобходимо ответить на сообщение пользователя.")
            return

        mute_duration = int(context.args[0])

        # Проверяем, является ли команда ответом на сообщение
        if not update.message.reply_to_message:
            update.message.reply_text("Команда /mute должна быть ответом на сообщение пользователя.")
            return

        # Получаем информацию о пользователе, которого нужно замьютить
        target_user = update.message.reply_to_message.from_user
        target_user_id = target_user.id
        target_username = target_user.username or target_user.first_name

        # Определяем, когда снять мьют
        unmute_time = datetime.now() + timedelta(minutes=mute_duration)
        muted_users[target_user_id] = unmute_time

        update.message.reply_text(f"Пользователь @{target_username} замьючен на {mute_duration} минут.")
    except Exception as e:
        logger.error(f"Ошибка в mute_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def ban_user(update: Update, context: CallbackContext):
    """Команда для бана пользователя и удаления всех его сообщений"""
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

        # Получаем информацию о пользователе, которого банят
        target_user = update.message.reply_to_message.from_user
        target_user_id = target_user.id
        target_username = target_user.username or target_user.first_name
        chat_id = update.message.chat_id

        # Определяем, когда снять бан (например, через 10 минут)
        ban_end_time = datetime.now() + timedelta(minutes=10)
        banned_users[target_user_id] = ban_end_time

        # Удаляем все сообщения пользователя из базы данных и чата
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT message_id FROM banned_messages WHERE chat_id = %s AND user_id = %s",
                (chat_id, target_user_id)
            )
            messages = cur.fetchall()
            for (msg_id,) in messages:
                try:
                    context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                    logger.info(f"Удалено сообщение с ID {msg_id} от пользователя {target_username} (ID: {target_user_id}).")
                except Exception as e:
                    logger.error(f"Ошибка при удалении сообщения с ID {msg_id}: {e}")
            # Удаляем записи из базы данных
            cur.execute(
                "DELETE FROM banned_messages WHERE chat_id = %s AND user_id = %s",
                (chat_id, target_user_id)
            )
            cur.close()
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщений из базы данных: {e}")

        update.message.reply_text(f"Пользователь @{target_username} забанен на 10 минут, и все его сообщения были удалены.")
    except Exception as e:
        logger.error(f"Ошибка в ban_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def unban_user(update: Update, context: CallbackContext):
    """Команда для разблокировки пользователя по username"""
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

        username = context.args[0].lstrip('@')
        chat_id = update.message.chat_id

        # Получаем user_id по username с помощью get_chat_member
        try:
            member = context.bot.get_chat_member(chat_id=chat_id, user_id=username)
            target_user_id = member.user.id
        except Exception as e:
            logger.error(f"Ошибка при получении информации о пользователе @{username}: {e}")
            update.message.reply_text(f"Не удалось найти пользователя @{username} в этом чате.")
            return

        # Удаляем пользователя из списков muted_users и banned_users
        был_замьючен = muted_users.pop(target_user_id, None) is not None
        был_забанен = banned_users.pop(target_user_id, None) is not None

        if был_замьючен or был_забанен:
            update.message.reply_text(f"Пользователь @{username} был разблокирован.")
        else:
            update.message.reply_text(f"Пользователь @{username} не был замьючен или забанен.")
    except Exception as e:
        logger.error(f"Ошибка в unban_user: {e}")
        update.message.reply_text("Произошла ошибка при выполнении команды.")

def main():
    updater = Updater(token=TELEGRAM_API_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Обработчики команд
    dispatcher.add_handler(CommandHandler('mute', mute_user))
    dispatcher.add_handler(CommandHandler('ban', ban_user))
    dispatcher.add_handler(CommandHandler('unban', unban_user))

    # Обработчики сообщений
    dispatcher.add_handler(MessageHandler(Filters.all, handle_message))
    dispatcher.add_handler(MessageHandler(Filters.update.edited_message, handle_edited_message))

    # Запуск бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
