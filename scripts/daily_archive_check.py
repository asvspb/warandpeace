import sys
import os

# Добавляем корневую директорию проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.parser import sync_archive
from src.database import get_stats

def print_statistics(new_articles_count: int):
    """
    Выводит общую статистику по базе данных.
    """
    print("\n--- Статистика ---")
    stats = get_stats()
    
    print(f"Новых статей за последнюю проверку: {new_articles_count}")
    print(f"Всего статей в базе: {stats.get('total_articles', 'N/A')}")
    print(f"Всего резюме в базе: {stats.get('total_summaries', 'N/A')}")
    
    last_article = stats.get('last_article')
    if last_article:
        print(f"Последняя добавленная статья: '{last_article.get('title', 'N/A')}' ({last_article.get('published_at', 'N/A')})")
    else:
        print("Последняя добавленная статья: Нет данных")
    print("--------------------\n")

if __name__ == "__main__":
    newly_added = sync_archive()
    print_statistics(newly_added)
