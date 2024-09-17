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

def search_messages_by_topic(topic, limit=10):
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

def handle_message(update: Update, context: CallbackContext):
    """Обработка текстовых сообщений"""
    message_deleted = delete_muted_user_message(update, context)

    if not message_deleted and should_respond_to_message(update, context):
        user_question = update.message.text.strip()

        # Используем OpenAI для извлечения темы вопроса
        topic = extract_topic_from_question(user_question)

        if topic:
            related_messages = search_messages_by_topic(topic)

            if related_messages:
                # Генерируем ответ с помощью OpenAI
                answer = generate_answer_by_topic(user_question, related_messages)
                if answer:
                    logger.info(f"Ответ: {answer}")
                    update.message.reply_text(answer)
            # Если нет сообщений или ответа, бот просто не отвечает
