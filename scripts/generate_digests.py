

import sys
import os
import logging
from datetime import datetime

# Добавляем корневую директорию проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import init_db, get_summaries_for_period, add_digest, get_db_connection
from src.summarizer import create_digest

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def generate_and_save_digest(days: int, period_name: str):
    """
    Общая функция для генерации и сохранения дайджеста за определенный период.
    
    Args:
        days (int): Количество дней для сбора резюме.
        period_name (str): Название периода для сохранения в БД (e.g., 'daily', 'weekly').
    """
    logger.info(f"--- Начинаю создание дайджеста за период: {period_name} ({days} дней) ---")
    
    # 1. Получаем резюме за указанный период
    summaries = get_summaries_for_period(days=days)
    if not summaries:
        logger.warning(f"Не найдено резюме за последние {days} дней. Дайджест для '{period_name}' не будет создан.")
        return

    logger.info(f"Найдено {len(summaries)} резюме для анализа.")

    # 2. Создаем аналитический дайджест (Вариант 2)
    digest_content = create_digest(summaries, f"{days} дней")
    if not digest_content:
        logger.error(f"Не удалось сгенерировать контент дайджеста для периода '{period_name}'.")
        return

    # 3. Сохраняем дайджест в базу данных
    add_digest(period=period_name, content=digest_content)
    logger.info(f"Дайджест за период '{period_name}' успешно создан и сохранен в базе данных.")

def show_digests_summary():
    """Выводит краткую сводку о количестве дайджестов каждого типа в базе."""
    logger.info("--- Сводка по дайджестам в базе данных ---")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT period, COUNT(*) FROM digests GROUP BY period")
            stats = cursor.fetchall()
            if not stats:
                print("В базе данных пока нет сохраненных дайджестов.")
                return
            
            print("Количество сохраненных дайджестов по типам:")
            for period, count in stats:
                print(f"- {period.capitalize()}: {count}")
    except Exception as e:
        logger.error(f"Ошибка при получении статистики по дайджестам: {e}")


if __name__ == "__main__":
    # Инициализируем БД на всякий случай
    init_db()

    # Генерируем и сохраняем каждый тип дайджеста
    generate_and_save_digest(days=1, period_name="daily")
    generate_and_save_digest(days=7, period_name="weekly")
    generate_and_save_digest(days=30, period_name="monthly")

    print("\nПроцесс создания дайджестов завершен.\n")

    # Показываем итоговую статистику
    show_digests_summary()

