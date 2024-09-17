import logging
from decouple import config
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CommandHandler
from telegram import Update
from datetime import datetime, timedelta  # Импорт для работы с временем

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных из .env файла
TELEGRAM_API_TOKEN = config('TELEGRAM_API_TOKEN')

# Список замьюченных пользователей
muted_users = {}

def check_and_remove_mute():
    """Проверяет время и снимает мьют с пользователей"""
    now = datetime.now()
    to_remove = [user for user, unmute_time in muted_users.items() if now >= unmute_time]

    # Удаление пользователей, чей мьют истек
    for user in to_remove:
        del muted_users[user]

def delete_muted_user_message(update: Update, context: CallbackContext):
    """Удаляет сообщения замьюченных пользователей"""
    check_and_remove_mute()  # Проверяем актуальность мьюта

    username = update.message.from_user.username

    if username in muted_users:
        # Удаляем сообщение замьюченного пользователя
        try:
            context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
            logger.info(f"Сообщение от {username} было удалено, так как он замьючен.")
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения от {username}: {e}")

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

def handle_message(update: Update, context: CallbackContext):
    """Простая обработка сообщений"""
    # Проверяем, не замьючен ли пользователь и удаляем его сообщение, если нужно
    delete_muted_user_message(update, context)

    # Если сообщение пользователя не было удалено, отправляем ответ
    if update.message and not update.message.deleted:  # Убедимся, что сообщение еще существует
        logger.info(f"Получено сообщение от {update.message.from_user.username}: {update.message.text}")
        update.message.reply_text("Я получил ваше сообщение!")

def main():
    updater = Updater(token=TELEGRAM_API_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Обработчик команд
    dispatcher.add_handler(CommandHandler('mute', mute_user))

    # Обработчик текстовых сообщений
    dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_message))

    # Запуск бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
