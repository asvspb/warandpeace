import sys
import os
from datetime import datetime
import time
import argparse

# Добавляем корневую директорию проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.parser import get_article_text, fetch_articles_in_date_range, get_articles_from_page
from src.summarizer import summarize_text_local
from src.database import init_db, add_article, is_article_posted

def backfill_articles(start_date: datetime, end_date: datetime, source: str = 'archive'):
    """
    Заполняет базу данных статьями из архива или главной страницы за указанный период.
    """
    print(f"Начинаю заполнение базы данных статьями с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')} из источника: {source}...")
    init_db()

    all_articles = []
    if source == 'archive':
        all_articles = fetch_articles_in_date_range(start_date, end_date)
    elif source == 'main_page':
        page = 1
        while True:
            print(f"Загружаю страницу {page} с главной страницы...")
            articles_on_page = get_articles_from_page(page)
            if not articles_on_page:
                print("На странице нет статей, останавливаюсь.")
                break

            found_older_article = False
            for article in articles_on_page:
                published_at_dt = datetime.fromisoformat(article['published_at'])
                if published_at_dt >= start_date:
                    all_articles.append(article)
                else:
                    found_older_article = True
            
            if found_older_article:
                print("Найдены статьи старше указанной даты, останавливаюсь.")
                break
            
            page += 1
    else:
        print(f"Неизвестный источник: {source}. Используйте 'archive' или 'main_page'.")
        return
    
    if not all_articles:
        print("Не найдено статей для заполнения в указанном диапазоне.")
        return

    # Сортируем статьи от старых к новым, чтобы избежать проблем с зависимостями или порядком
    all_articles.sort(key=lambda x: datetime.fromisoformat(x['published_at']))

    processed_count = 0
    for article in all_articles:
        url = article['link']
        title = article['title']
        published_at = article['published_at']

        if is_article_posted(url):
            print(f"Статья уже в базе: {title} ({published_at})")
            continue

        print(f"Обрабатываю статью: {title} ({published_at})")
        full_text = get_article_text(url)
        if not full_text:
            print(f"Не удалось получить полный текст для статьи: {title}. Пропускаю.")
            continue

        # summary = summarize_text_local(full_text) # Отключаем суммаризацию
        summary = None # Заполняем summary как None
        # if not summary:
        #     print(f"Не удалось получить резюме для статьи: {title}. Пропускаю.")
        #     continue

        add_article(url, title, published_at_iso=published_at)
        processed_count += 1
        print(f"Добавлена статья: {title} ({published_at}) (без суммаризации)")
        time.sleep(0.1) # Уменьшаем задержку для быстрого заполнения

    print(f"\nЗаполнение завершено. Всего добавлено {processed_count} новых статей.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Заполнение базы данных статьями из архива или главной страницы.")
    parser.add_argument("--start_date", type=str, required=True, help="Начальная дата в формате ДД.ММ.ГГГГ")
    parser.add_argument("--end_date", type=str, help="Конечная дата в формате ДД.ММ.ГГГГ (по умолчанию - текущая дата)")
    parser.add_argument("--source", type=str, default="archive", choices=["archive", "main_page"], help="Источник статей: 'archive' или 'main_page' (по умолчанию 'archive')")

    args = parser.parse_args()

    start_date_dt = datetime.strptime(args.start_date, "%d.%m.%Y")
    end_date_dt = datetime.now()
    if args.end_date:
        end_date_dt = datetime.strptime(args.end_date, "%d.%m.%Y")

    backfill_articles(start_date_dt, end_date_dt, args.source)
