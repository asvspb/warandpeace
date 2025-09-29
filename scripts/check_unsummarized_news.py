#!/usr/bin/env python3
"""
Скрипт для проверки количества нерезюмированных новостей за определённую дату.
"""

import sys
from datetime import datetime
from src.database import get_db_connection

def count_unsummarized_news(target_date: str) -> int:
    """Возвращает количество новостей за определённую дату, у которых нет резюме."""
    try:
        # Проверим формат даты
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        print(f"Ошибка: Неправильный формат даты '{target_date}'. Ожидается формат YYYY-MM-DD.")
        return -1

    with get_db_connection() as conn:
        cursor = conn.cursor()
        sql = """
        SELECT COUNT(*) 
        FROM articles 
        WHERE DATE(published_at) = ? 
        AND (summary_text IS NULL OR summary_text = '');
        """
        cursor.execute(sql, (target_date,))
        result = cursor.fetchone()
        return result[0] if result else 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python check_unsummarized_news.py <дата в формате YYYY-MM-DD>")
        sys.exit(1)

    target_date = sys.argv[1]
    count = count_unsummarized_news(target_date)

    if count >= 0:
        print(f"Количество нерезюмированных новостей за {target_date}: {count}")
        sys.exit(0)
    else:
        sys.exit(1)