

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from database import get_stats

if __name__ == "__main__":
    stats = get_stats()
    print("Статистика базы данных:")
    print(f"- Всего статей: {stats['total_articles']}")
    print(f"- Всего резюме: {stats['total_summaries']}")
    print(f"- Последняя статья: \"{stats['last_article']['title']}\" ({stats['last_article']['published_at']})")

