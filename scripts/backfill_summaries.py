import asyncio
import logging
import os
import sys
from datetime import datetime

# Добавляем корневой каталог проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_articles_without_summary, add_summary, init_db
from src.parser import get_article_text
from src.summarizer import summarize_text_local

# Создаем папку для логов, если она не существует
if not os.path.exists('logs'):
    os.makedirs('logs')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"logs/backfill_summaries_{datetime.now().strftime('%Y-%m-%d')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

async def main():
    """
    Основная функция для поиска статей без резюме и создания их.
    """
    init_db()
    logger.info("Поиск статей без резюме...")

    articles_to_process = get_articles_without_summary()

    if not articles_to_process:
        logger.info("Все статьи уже имеют резюме. Работа завершена.")
        return

    logger.info(f"Найдено {len(articles_to_process)} статей для обработки.")

    for index, article in enumerate(articles_to_process):
        article_id, article_url, article_title = article
        logger.info(f"Обработка статьи {index + 1}/{len(articles_to_process)}: '{article_title}'")

        try:
            # 1. Получаем полный текст статьи
            full_text = await asyncio.to_thread(get_article_text, article_url)
            if not full_text:
                logger.warning(f"Не удалось получить текст для статьи ID {article_id}. Пропускаем.")
                continue

            # 2. Генерируем резюме
            summary = await asyncio.to_thread(summarize_text_local, full_text)
            if not summary:
                logger.warning(f"Не удалось сгенерировать резюме для статьи ID {article_id}. Пропускаем.")
                continue

            # 3. Сохраняем резюме в БД
            add_summary(article_id, summary)
            logger.info(f"Успешно сохранено резюме для статьи ID {article_id}.")

            # 4. Пауза, чтобы не перегружать API
            await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"Произошла ошибка при обработке статьи ID {article_id}: {e}", exc_info=True)

    logger.info("Процесс заполнения резюме завершен.")

if __name__ == "__main__":
    asyncio.run(main())
