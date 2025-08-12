
import sys
import os
import json
from datetime import datetime, date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from parser import get_articles_from_page

class DateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, date):
            return obj.isoformat()
        return super().default(obj)

def fetch_and_save_todays_articles():
    """
    Собирает все статьи за сегодня и сохраняет их в JSON-файл.
    """
    today_str = datetime.now().strftime('%d.%m.%y')
    all_articles = []
    todays_articles = []
    page = 1
    
    print("Начинаю сбор статей...")

    while True:
        print(f"Загружаю страницу {page}...")
        articles_on_page = get_articles_from_page(page)
        if not articles_on_page:
            print("На странице нет статей, останавливаюсь.")
            break

        all_articles.extend(articles_on_page)
        
        # Проверяем, есть ли на странице статьи с датой, отличающейся от сегодняшней
        found_older_article = False
        for article in articles_on_page:
            # Ожидаем, что дата в формате 'dd.mm.yy hh:mm'
            if today_str not in article.get('time', ''):
                found_older_article = True
                break
        
        if found_older_article:
            print("Найдены статьи за предыдущие дни, останавливаюсь.")
            break
            
        page += 1

    # Фильтруем статьи, чтобы оставить только сегодняшние
    for article in all_articles:
        if today_str in article.get('time', ''):
            todays_articles.append(article)

    # Убираем дубликаты, если они есть
    unique_articles = {each['link']: each for each in todays_articles}.values()

    output_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../temp/todays_articles.json'))
    
    print(f"Найдено {len(list(unique_articles))} уникальных статей за сегодня.")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(list(unique_articles), f, cls=DateEncoder, ensure_ascii=False, indent=4)
        
    print(f"Статьи сохранены в {output_path}")

if __name__ == "__main__":
    fetch_and_save_todays_articles()
