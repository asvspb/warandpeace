

import sqlite3
import os
import sys

# Добавляем корневую директорию проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

DATABASE_NAME = os.path.join(os.path.dirname(__file__), '..', 'database', 'articles.db')
BACKUP_NAME = os.path.join(os.path.dirname(__file__), '..', 'database', 'articles.db.backup')

def migrate_database_to_v2():
    """
    Выполняет миграцию базы данных к новой схеме с отдельными таблицами 
    для статей и резюме.
    1. Переименовывает старую таблицу `articles` в `articles_old`.
    2. Создает новые таблицы `articles` и `summaries`.
    3. Копирует данные из `articles_old` в новые таблицы.
    4. Удаляет временную таблицу `articles_old`.
    """
    print("Начинаю миграцию базы данных...")

    if not os.path.exists(DATABASE_NAME):
        print("База данных не найдена. Новая будет создана при первом запуске.")
        # Импортируем и вызываем init_db, чтобы создать пустую БД правильной структуры
        from src.database import init_db
        init_db()
        print("Создана новая пустая база данных с правильной структурой.")
        return

    # Создаем резервную копию на всякий случай
    print(f"Создаю резервную копию: {BACKUP_NAME}")
    import shutil
    shutil.copy(DATABASE_NAME, BACKUP_NAME)

    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    try:
        # 1. Переименовываем старую таблицу
        print("Переименовываю старую таблицу `articles` в `articles_old`...")
        cursor.execute("ALTER TABLE articles RENAME TO articles_old")

        # 2. Создаем новые таблицы с помощью функции init_db из обновленного модуля
        print("Создаю новые таблицы `articles` и `summaries`...")
        from src.database import init_db
        # Вызываем init_db с текущим соединением, чтобы избежать блокировок
        init_db() # Это создаст таблицы articles, summaries, digests

        # 3. Копируем данные
        print("Копирую данные из старой таблицы в новые...")
        cursor.execute("SELECT id, url, title, summary, published_at FROM articles_old")
        old_articles = cursor.fetchall()

        for article in old_articles:
            old_id, url, title, summary, published_at = article
            
            # Вставляем в новую таблицу articles
            cursor.execute(
                "INSERT INTO articles (id, url, title, published_at) VALUES (?, ?, ?, ?)",
                (old_id, url, title, published_at)
            )
            new_article_id = old_id # ID сохраняется

            # Если было резюме, вставляем его в summaries
            if summary:
                cursor.execute(
                    "INSERT INTO summaries (article_id, summary_text) VALUES (?, ?)",
                    (new_article_id, summary)
                )
        
        # 4. Удаляем временную таблицу
        print("Удаляю временную таблицу `articles_old`...")
        cursor.execute("DROP TABLE articles_old")

        conn.commit()
        print("\nМиграция успешно завершена!")

    except sqlite3.OperationalError as e:
        if "no such table: articles" in str(e):
             print("Старая таблица `articles` не найдена. Возможно, миграция не требуется.")
             # Создаем таблицы, если их нет
             from src.database import init_db
             init_db()
        elif "table articles_old already exists" in str(e):
            print("Похоже, миграция уже была запущена, но не завершилась. Восстановите из бэкапа и попробуйте снова.")
        else:
            print(f"Произошла ошибка SQLite: {e}")
            conn.rollback()
    except Exception as e:
        print(f"Произошла непредвиденная ошибка: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database_to_v2()

