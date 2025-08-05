
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime

# Добавляем корневой каталог проекта в sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import add_article, is_article_posted, init_db
from src.async_parser import fetch_articles_for_date

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/parse_specific_date.log"),
        logging.StreamHandler(),
    ],
)


async def main(date_str: str):
    """
    Главная функция для парсинга новостей за определенную дату и сохранения их в БД.
    """
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        logging.info(f"Начинаем парсинг новостей за {target_date.strftime('%d.%m.%Y')}")
    except ValueError:
        logging.error("Неверный формат даты. Используйте YYYY-MM-DD.")
        return

    # Инициализация БД
    await asyncio.to_thread(init_db)

    # Получение статей
    articles = await fetch_articles_for_date(target_date)

    if not articles:
        logging.warning(f"Не найдено статей за {target_date.strftime('%d.%m.%Y')}")
        return

    logging.info(f"Найдено {len(articles)} статей. Начинаем обработку.")

    added_count = 0
    for title, link in articles:
        is_posted = await asyncio.to_thread(is_article_posted, link)
        if not is_posted:
            # Для статей из архива устанавливаем время 00:00:00
            await asyncio.to_thread(add_article, link, title, target_date.strftime("%Y-%m-%d 00:00:00"))
            logging.info(f"Добавлена статья: {title}")
            added_count += 1
        else:
            logging.info(f"Статья уже существует в БД: {title}")

    logging.info(f"Завершено. Добавлено {added_count} новых статей.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Парсинг новостей за определенную дату."
    )
    parser.add_argument(
        "date", type=str, help="Дата в формате YYYY-MM-DD"
    )
    args = parser.parse_args()

    asyncio.run(main(args.date))
