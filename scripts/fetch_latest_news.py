import sys
import os
from datetime import datetime
import time
import logging

# Добавляем корневую директорию проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.parser import get_article_text, get_articles_from_page
from src.database import init_db, add_article, is_article_posted

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fetch_and_add_latest_news():
    """
    Получает последние новости с главной страницы и добавляет их в базу данных.
    """
    logger.info("Начинаю сбор последних новостей с главной страницы...")
    init_db()

    articles_on_main_page = get_articles_from_page(1) # Получаем только первую страницу

    if not articles_on_main_page:
        logger.warning("Не найдено статей на главной странице или произошла ошибка при загрузке.")
        return

    processed_count = 0
    for article in articles_on_main_page:
        url = article['link']
        title = article['title']
        published_at = article['published_at']

        if is_article_posted(url):
            logger.info(f"Статья уже в базе: {title} ({published_at})")
            continue

        logger.info(f"Обрабатываю новую статью: {title} ({published_at})")
        full_text = get_article_text(url)
        if not full_text:
            logger.warning(f"Не удалось получить полный текст для статьи: {title}. Пропускаю.")
            continue

        # Суммаризация отключена, как и в backfill.py
        summary = None 

        add_article(url, title, summary, published_at_iso=published_at)
        processed_count += 1
        logger.info(f"Добавлена статья: {title} ({published_at}) (без суммаризации)")
        time.sleep(0.1) # Небольшая задержка, чтобы не нагружать сервер

    logger.info(f"\nСбор последних новостей завершен. Всего добавлено {processed_count} новых статей.")

if __name__ == "__main__":
    fetch_and_add_latest_news()
