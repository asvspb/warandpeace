

import sys
import os
import logging
import time
from datetime import date

# Добавляем корневую директорию проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection, add_summary, has_summary
from src.parser import get_article_text
from src.summarizer import summarize_text_local

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def backfill_summaries_for_date(target_date: date):
    """
    Находит статьи за определенную дату, у которых нет резюме, и генерирует их.
    """
    date_str = target_date.strftime('%Y-%m-%d')
    logger.info(f"--- Начинаю процесс создания недостающих резюме за {date_str} ---")

    articles_to_process = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            start_of_day = f"{date_str} 00:00:00"
            end_of_day = f"{date_str} 23:59:59"
            
            cursor.execute("""
                SELECT id, url, title FROM articles 
                WHERE published_at BETWEEN ? AND ?
            """, (start_of_day, end_of_day))
            articles_to_process = cursor.fetchall()
    except Exception as e:
        logger.error(f"Ошибка при получении статей из базы: {e}")
        return

    if not articles_to_process:
        logger.warning(f"В базе данных не найдено статей за {date_str}.")
        return

    logger.info(f"Найдено {len(articles_to_process)} статей за {date_str}. Проверяю наличие резюме...")

    summaries_added_count = 0
    for article_id, url, title in articles_to_process:
        if has_summary(article_id):
            logger.info(f"Резюме для '{title}' уже существует. Пропускаю.")
            continue

        logger.info(f"Генерирую резюме для статьи: '{title}'")

        full_text = get_article_text(url)
        if not full_text:
            logger.warning(f"Не удалось получить текст для '{title}'. Пропускаю.")
            continue

        summary = summarize_text_local(full_text)
        if not summary:
            logger.error(f"Не удалось создать резюме для '{title}'. Пропускаю.")
            continue
        
        add_summary(article_id, summary)
        summaries_added_count += 1
        logger.info(f"Резюме для '{title}' успешно создано и сохранено.")
        time.sleep(1)

    logger.info(f"\nПроцесс завершен. Добавлено {summaries_added_count} новых резюме за {date_str}.")

if __name__ == "__main__":
    # Указываем конкретную дату, для которой нужно создать резюме
    target_date_to_fix = date(2025, 8, 3)
    backfill_summaries_for_date(target_date_to_fix)

