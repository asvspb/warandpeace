

import sys
import os
import time
import logging

# Добавляем корневую директорию проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.parser import get_article_text, get_articles_from_page
from src.database import init_db, add_article, add_summary, has_summary
from src.summarizer import summarize_text_local

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_summaries_for_main_page():
    """
    Получает новости с главной страницы, генерирует для них резюме 
    и сохраняет в отдельную таблицу `summaries`.
    """
    logger.info("Начинаю процесс создания резюме для новостей с главной страницы...")
    init_db() # Убедимся, что таблицы существуют

    articles_on_main_page = get_articles_from_page(1)

    if not articles_on_main_page:
        logger.warning("Не найдено статей на главной странице или произошла ошибка.")
        return

    summaries_added_count = 0
    for article_data in reversed(articles_on_main_page):
        url = article_data['link']
        title = article_data['title']
        published_at = article_data['published_at']

        logger.info(f"Проверяю статью: '{title}'")

        # 1. Добавляем статью в БД (или получаем ее ID, если уже существует)
        article_id = add_article(url, title, published_at_iso=published_at)
        if not article_id:
            logger.error(f"Не удалось получить ID для статьи: {title}. Пропускаю.")
            continue

        # 2. Проверяем, есть ли уже резюме для этой статьи
        if has_summary(article_id):
            logger.info("Резюме для этой статьи уже существует. Пропускаю.")
            continue

        logger.info("Резюме не найдено. Начинаю генерацию...")

        # 3. Получаем полный текст
        full_text = get_article_text(url)
        if not full_text:
            logger.warning(f"Не удалось получить текст для статьи: {title}. Пропускаю.")
            continue

        # 4. Генерируем резюме
        summary = summarize_text_local(full_text)
        if not summary:
            logger.error(f"Не удалось создать резюме для статьи: {title}. Пропускаю.")
            continue
        
        # 5. Добавляем резюме в базу
        add_summary(article_id, summary)
        summaries_added_count += 1
        logger.info(f"Резюме для статьи '{title}' успешно создано и сохранено.")
        
        time.sleep(1) # Пауза между запросами к API

    logger.info(f"\nПроцесс завершен. Добавлено {summaries_added_count} новых резюме.")

if __name__ == "__main__":
    create_summaries_for_main_page()

