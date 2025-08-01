import requests
from bs4 import BeautifulSoup

def get_full_article_text(url):
    """
    Загружает полный текст статьи по URL.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()  # Проверка на ошибки HTTP
        soup = BeautifulSoup(response.content, 'html.parser')
        news_text_div = soup.find('body')
        if news_text_div:
            # Извлечение текста и очистка от лишних пробелов
            text = ' '.join(news_text_div.stripped_strings)
            return text
        else:
            return "Текст статьи не найден."
    except requests.exceptions.RequestException as e:
        return f"Ошибка при загрузке страницы: {e}"
    except Exception as e:
        return f"Произошла ошибка: {e}"

def get_latest_articles():
    """
    Парсит страницу новостей и возвращает последние статьи с полным текстом.
    """
    list_url = "https://warandpeace.ru/ru/news/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
    }
    try:
        response = requests.get(list_url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        articles_data = []
        found_articles = 0
        for item in soup.find_all('a'):
            link = item.get('href')
            if link and '/ru/news/' in link and not link.endswith('/ru/news/'):
                # Убедимся, что ссылка полная
                if not link.startswith('http'):
                    link = f"https://warandpeace.ru{link}"
                
                title = item.text.strip()
                if not title:
                    continue # Пропускаем ссылки без текста

                print(f"Обрабатывается: {title}")
                full_text = get_full_article_text(link)
                articles_data.append({
                    'title': title,
                    'link': link,
                    'full_text': full_text
                })
                found_articles += 1
                if found_articles >= 5:
                    break
        return articles_data
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при загрузке страницы новостей: {e}")
        return []
    except Exception as e:
        print(f"Произошла ошибка при парсинге страницы новостей: {e}")
        return []

if __name__ == "__main__":
    latest_articles = get_latest_articles()
    if latest_articles:
        for article in latest_articles:
            print("\n---")
            print(f"Заголовок: {article['title']}")
            print(f"Ссылка: {article['link']}")
            print(f"Текст: {article['full_text'][:200]}...") # Выводим первые 200 символов для краткости
    else:
        print("Не удалось получить статьи.")
    print("\nПарсер завершил работу.")
