# Обновляем информацию о пользователе в таблице known_users
try:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO known_users (user_id, username, last_seen) VALUES (%s, %s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, last_seen = EXCLUDED.last_seen",
        (user_id, username, datetime.now())
    )
    cur.close()
except Exception as e:
    logger.error(f"Ошибка при обновлении known_users: {e}")
