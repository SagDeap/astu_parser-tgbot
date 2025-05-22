import sqlite3
import os
import logging
from typing import Optional


# Объективно тут БД не нужна, эт прост моя шиза, можно использовать и массивы (см bot.py) 
# Настройка логирования
logger = logging.getLogger(__name__)

# Путь к базе данных
DB_PATH = "users.db"

def init_db() -> None:
    
    conn = None
    try:
        # Создаем папку для БД, если ее нет
        db_dir = os.path.dirname(DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Создаем таблицу пользователей, если ее нет
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            group_name TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        conn.commit()
        logger.info("База данных инициализирована успешно.")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")
    finally:
        if conn:
            conn.close()

def save_user_group(user_id: int, group_name: str) -> bool:
   
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Проверяем, есть ли уже запись для этого пользователя
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        
        if result:
            # Обновляем существующую запись
            cursor.execute("""
            UPDATE users 
            SET group_name = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE user_id = ?
            """, (group_name, user_id))
        else:
            # Создаем новую запись
            cursor.execute("""
            INSERT INTO users (user_id, group_name) 
            VALUES (?, ?)
            """, (user_id, group_name))
        
        conn.commit()
        logger.info(f"Группа {group_name} сохранена для пользователя {user_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении группы пользователя: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_user_group(user_id: int) -> Optional[str]:
    
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT group_name FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        
        if result:
            logger.info(f"Получена группа для пользователя {user_id}: {result[0]}")
            return result[0]
        else:
            logger.info(f"Группа для пользователя {user_id} не найдена")
            return None
    except Exception as e:
        logger.error(f"Ошибка при получении группы пользователя: {e}")
        return None
    finally:
        if conn:
            conn.close()

def delete_user_data(user_id: int) -> bool:
    
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        
        conn.commit()
        logger.info(f"Данные пользователя {user_id} удалены")
        return True
    except Exception as e:
        logger.error(f"Ошибка при удалении данных пользователя: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_all_users() -> list:
    
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT user_id, group_name, updated_at FROM users")
        users = cursor.fetchall()
        
        logger.info(f"Получено {len(users)} пользователей из БД")
        return users
    except Exception as e:
        logger.error(f"Ошибка при получении списка пользователей: {e}")
        return []
    finally:
        if conn:
            conn.close() 
