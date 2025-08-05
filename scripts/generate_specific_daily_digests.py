

import sys
import os
import logging
import asyncio
from datetime import date
from telegram import Bot
from telegram.constants import ParseMode

# Добавляем корневую директорию проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection
from src.summarizer import create_digest
from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_summaries_for_specific_date(target_date: date) -> list[str]:
    """
    Извлекает все резюме для статей, опубликованных в конкретный день.
    """
    logger.info(f"Запрашиваю резюме за конкретную дату: {target_date.strftime('%Y-%m-%d')}")
    summaries = []
    start_of_day = f"{target_date.strftime('%Y-%m-%d')} 00:00:00"
    end_of_day = f"{target_date.strftime('%Y-%m-%d')} 23:59:59"
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.summary_text 
                FROM summaries s
                JOIN articles a ON s.article_id = a.id
                WHERE a.published_at BETWEEN ? AND ?
                ORDER BY a.published_at DESC
            """, (start_of_day, end_of_day))
            summaries = [row[0] for row in cursor.fetchall()]
            logger.info(f"Найдено {len(summaries)} резюме за {target_date.strftime('%Y-%m-%d')}.")
    except Exception as e:
        logger.error(f"Ошибка при получении резюме из базы данных за {target_date}: {e}")
    return summaries

async def send_message_to_admin(bot: Bot, title: str, content: str):
    """Отправляет одно сообщение администратору."""
    if not content:
        content = "Не удалось сгенерировать текст дайджеста."
    
    message = f"*{title}*\n\n{content}"
    await bot.send_message(chat_id=TELEGRAM_ADMIN_ID, text=message, parse_mode=ParseMode.MARKDOWN)
    logger.info(f"Сообщение '{title}' отправлено администратору.")

async def main():
    """Основная асинхронная функция."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_ID:
        logger.error("Токен бота или ID администратора не найдены. Отправка невозможна.")
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dates_to_process = [date(2025, 8, 3), date(2025, 8, 4)]

    for target_date in dates_to_process:
        date_str = target_date.strftime("%d %B %Y")
        title = f"Суточный аналитический дайджест за {date_str}"
        
        summaries = get_summaries_for_specific_date(target_date)
        if not summaries:
            logger.warning(f"Резюме за {date_str} не найдены, отправляю уведомление.")
            await send_message_to_admin(bot, title, "Статьи для анализа за этот день не найдены.")
            continue

        logger.info(f"Генерирую дайджест для {date_str}...")
        digest_content = create_digest(summaries, f"статьи за {date_str}")
        
        await send_message_to_admin(bot, title, digest_content)
        await asyncio.sleep(1) # Пауза между отправками

    logger.info("Процесс завершен.")

if __name__ == "__main__":
    asyncio.run(main())

