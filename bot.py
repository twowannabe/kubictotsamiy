from telegram.ext import MessageHandler, Filters, CallbackContext
from telegram import Update

def handle_message(update: Update, context: CallbackContext):
    try:
        # Логируем информацию о сообщении
        logger.info(f"handle_message вызван для пользователя {update.effective_user.id} в чате {update.effective_chat.id}")
        logger.info(f"Текст сообщения: {update.message.text}")

        # Получаем ID пользователя, который отправил сообщение
        user_id = update.effective_user.id
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

def main():
    updater = Updater(token=TELEGRAM_API_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Изменяем фильтр, чтобы он ловил любые текстовые сообщения
    dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_message))

    # Логирование всех обновлений
    dispatcher.add_handler(MessageHandler(Filters.all, log_update))

    dispatcher.add_error_handler(error_handler)

    updater.start_polling()
    logger.info("Бот запущен. Нажмите Ctrl+C для остановки.")
    updater.idle()
