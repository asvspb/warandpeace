import sqlite3
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATABASE_NAME = "database/articles.db"
BACKUP_NAME = "database/articles.db.backup"

def migrate_db():
    """
    Выполняет миграцию старой схемы БД (articles + summaries) к новой (articles со статусом).
    1. Переименовывает старую таблицу articles в old_articles.
    2. Создает новую таблицу articles с правильной структурой.
    3. Копирует данные из old_articles, обогащая их данными из summaries.
    4. Удаляет временные таблицы.
    """
    logger.info("Начинаю миграцию базы данных...")
    
    # Создаем бэкап на всякий случай
    try:
        with open(DATABASE_NAME, 'rb') as src, open(BACKUP_NAME, 'wb') as dst:
            dst.write(src.read())
        logger.info(f"Резервная копия базы данных создана: {BACKUP_NAME}")
    except FileNotFoundError:
        logger.warning("Исходная база данных не найдена. Пропускаю создание резервной копии.")
        # Если базы нет, миграция не нужна, но init_db() должен быть вызван
        return

    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    try:
        # --- Шаг 1: Проверить, нужна ли миграция ---
        cursor.execute("PRAGMA table_info(articles)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'status' in columns:
            logger.info("Миграция не требуется. Поле 'status' уже существует в таблице articles.")
            return

        # --- Шаг 2: Переименовать старую таблицу articles ---
        logger.info("Переименовываю 'articles' в 'old_articles'...")
        cursor.execute("ALTER TABLE articles RENAME TO old_articles")

        # --- Шаг 3: Создать новую таблицу articles ---
        logger.info("Создаю новую таблицу 'articles' со статусной моделью...")
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

        # --- Шаг 4: Перенести данные, обогащая их из summaries ---
        logger.info("Переношу данные из 'old_articles' и 'summaries' в новую таблицу...")
        
        # Сначала получаем все резюме в словарь для быстрого доступа
        summaries = {}
        try:
            cursor.execute("SELECT article_id, summary_text FROM summaries")
            for row in cursor.fetchall():
                summaries[row[0]] = row[1]
            logger.info(f"Найдено {len(summaries)} резюме в старой таблице.")
        except sqlite3.OperationalError:
            logger.warning("Таблица 'summaries' не найдена. Миграция будет выполнена без резюме.")

        # Переносим статьи, определяя статус
        cursor.execute("SELECT id, url, title, published_at FROM old_articles")
        articles_to_migrate = cursor.fetchall()
        
        migrated_count = 0
        for article in articles_to_migrate:
            article_id, url, title, published_at = article
            summary = summaries.get(article_id)
            
            # Статус: если есть резюме, то 'posted', иначе 'new' (предполагаем, что раз есть резюме, то запощено)
            status = 'posted' if summary else 'new'
            
            cursor.execute("""
                INSERT INTO articles (id, url, title, published_at, summary_text, status) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, (article_id, url, title, published_at, summary, status))
            migrated_count += 1

        logger.info(f"Успешно перенесено {migrated_count} статей.")

        # --- Шаг 5: Удалить старые таблицы ---
        logger.info("Удаляю временные таблицы 'old_articles' и 'summaries'...")
        cursor.execute("DROP TABLE old_articles")
        try:
            cursor.execute("DROP TABLE summaries")
        except sqlite3.OperationalError:
            pass # Таблицы могло и не быть

        # --- Шаг 6: Создать индексы ---
        logger.info("Создаю индексы для новой таблицы...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_status ON articles (status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles (published_at)")

        conn.commit()
        logger.info("Миграция базы данных успешно завершена!")

    except sqlite3.Error as e:
        logger.error(f"Произошла ошибка во время миграции: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_db()
