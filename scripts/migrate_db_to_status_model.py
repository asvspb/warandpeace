import sqlite3
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATABASE_NAME = "database/articles.db"

def add_column_if_not_exists(cursor, table_name, column_name, column_def):
    """Проверяет и добавляет колонку, если она не существует."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    if column_name not in columns:
        logger.info(f"Добавляю колонку '{column_name}' в таблицу '{table_name}'...")
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
    else:
        logger.info(f"Колонка '{column_name}' уже существует в таблице '{table_name}'.")

def migrate_db():
    """
    Выполняет идемпотентную миграцию базы данных к последней версии.
    Проверяет наличие таблиц и колонок перед их созданием или изменением.
    """
    logger.info("Запуск проверки и миграции базы данных...")
    
    try:
        with sqlite3.connect(DATABASE_NAME) as conn:
            cursor = conn.cursor()

            # Проверяем, существует ли таблица 'articles' вообще
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles'")
            if not cursor.fetchone():
                logger.info("Таблица 'articles' не найдена. Создаю ее с нуля.")
                cursor.execute("""
                    CREATE TABLE articles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        url TEXT NOT NULL UNIQUE,
                        title TEXT NOT NULL,
                        published_at TIMESTAMP NOT NULL,
                        summary_text TEXT,
                        status TEXT NOT NULL DEFAULT 'new',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                logger.info("Таблица 'articles' успешно создана.")

            # Добавляем недост��ющие колонки в таблицу 'articles'
            add_column_if_not_exists(cursor, 'articles', 'status', "TEXT NOT NULL DEFAULT 'new'")
            add_column_if_not_exists(cursor, 'articles', 'summary_text', 'TEXT')
            add_column_if_not_exists(cursor, 'articles', 'created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
            add_column_if_not_exists(cursor, 'articles', 'updated_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP')

            # Проверяем, существует ли старая таблица 'summaries'
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='summaries'")
            if cursor.fetchone():
                logger.info("Обнаружена старая таблица 'summaries'. Переношу данные...")
                # Получаем все резюме в словарь
                summaries = {row[0]: row[1] for row in cursor.execute("SELECT article_id, summary_text FROM summaries").fetchall()}
                
                # Обновляем 'articles', добавляя резюме и меняя статус
                for article_id, summary in summaries.items():
                    cursor.execute("UPDATE articles SET summary_text = ?, status = 'posted' WHERE id = ? AND summary_text IS NULL", (summary, article_id))
                
                logger.info("Удаляю старую таблицу 'summaries'...")
                cursor.execute("DROP TABLE summaries")
            
            # Создаем индексы, если их нет
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_status ON articles (status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles (published_at)")

            conn.commit()
            logger.info("Проверка и миграция базы данных успешно завершены.")

    except sqlite3.Error as e:
        logger.error(f"Произошла ошибка во время миграции: {e}", exc_info=True)

if __name__ == "__main__":
    migrate_db()
