import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta

# Добавляем корневой каталог проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import add_article, is_article_posted, init_db
from src.parser import fetch_articles_in_date_range

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

async def main():
    """
    Основная функция для сбора статей за последние 24 часа и добавления их в БД.
    """
    init_db()
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1)

    logger.info(f"Запускаю сбор статей с {start_date.strftime('%Y-%m-%d %H:%M')} по {end_date.strftime('%Y-%m-%d %H:%M')}")

    # Используем существующую функцию для сбора статей из архива
    articles = await asyncio.to_thread(fetch_articles_in_date_range, start_date, end_date)

    if not articles:
        logger.info("Новых статей за указанный период не найдено.")
        return

    logger.info(f"Найдено {len(articles)} статей. Добавляю в базу данных...")

    added_count = 0
    for article in reversed(articles): # Начинаем с самых старых
        if not is_article_posted(article["link"]):
            add_article(article["link"], article["title"], article["published_at"])
            logger.info(f"Добавлена статья: '{article['title']}'")
            added_count += 1
        else:
            logger.info(f"Статья '{article['title']}' уже существует в базе. Пропускаем.")

    logger.info(f"Добавлено {added_count} новых статей в базу данных.")

if __name__ == "__main__":
    asyncio.run(main())
