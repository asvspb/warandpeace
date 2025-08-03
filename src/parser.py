import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
from summarizer import summarize_text_local
from config import NEWS_URL
from tenacity import retry, stop_after_attempt, wait_exponential, \
    retry_if_exception_type
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=4, max=10),
       retry=retry_if_exception_type(requests.exceptions.RequestException))
def get_article_text(url: str) -> str | None:
    """
    Синхронно получает полный текст статьи по URL, перебирая список селекторов.
    """
    # Список потенциальных селекторов для текста статьи. 
    # Порядок важен: от наиболее вероятного к менее вероятным.
    selectors = [
        'td.topic_text',      # Текущий рабочий селектор
        'td.topic_text',      # Текущий рабочий селектор
        'div.news-text',      # Старый селектор, на всякий случай
        'div.article-text',   # Еще один распространенный вариант
        'div.text',           # Общий селектор
    ]

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        response.encoding = 'windows-1251'
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        article_body = None
        for selector in selectors:
            article_body = soup.select_one(selector)
            if article_body:
                # logger.info(f"Найден текст статьи с использованием селектора: {selector}") # Для отладки
                break

        if article_body:
            for s in article_body.select('script, style'):
                s.decompose()
            
            clean_text = '\n'.join(line.strip() for line in article_body.get_text(separator='\n').split('\n') if line.strip())
            return clean_text
        else:
            logger.warning(f"Не удалось найти текст статьи для {url} ни с одним из селекторов.")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка сети или HTTP при загрузке статьи {url}: {e}")
        raise # Перевыбрасываем исключение для tenacity
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка при парсинге статьи {url}: {e}")
        return None

@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=4, max=10),
       retry=retry_if_exception_type(requests.exceptions.RequestException))
def get_articles_from_page(page=1):
    """
    Получает список статей с заданной страницы новостей.
    """
    if page == 1:
        list_url = NEWS_URL
    else:
        list_url = f"{NEWS_URL}_/_/page={page}/"
    
    try:
        response = requests.get(list_url, timeout=20)
        response.raise_for_status()
        response.encoding = 'windows-1251'
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        articles_data = []
        tables = soup.find_all('table', border="0", align="center", cellspacing="0", width="100%")

        for table in tables:
            if table.find('td', class_='topic_caption'):
                title_tag = table.find('a', class_='a_header_article')
                time_tag = table.find('td', class_='topic_info_top')

                if title_tag and time_tag:
                    title = title_tag.text.strip()
                    link = title_tag['href']
                    if not link.startswith('http'):
                        base_url = "https://www.warandpeace.ru"
                        link = base_url + link if link.startswith('/') else base_url + '/' + link

                    time_text = time_tag.text.strip()
                    time_match = re.search(r'(\d{2}\.\d{2}\.\d{2}) (\d{2}:\d{2})', time_text)
                    date_str, time_str = time_match.groups() if time_match else ('??.??.??', '??:??')

                    if title and link:
                        if not any(d['link'] == link for d in articles_data):
                            articles_data.append({
                                'date': date_str,
                                'time': time_str,
                                'title': title,
                                'link': link
                            })
        return articles_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка сети или HTTP при загрузке страницы новостей: {e}")
        raise # Перевыбрасываем исключение для tenacity
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка при парсинге страницы новостей: {e}")
        return []

def main():
    """
    Тестовая функция для проверки работы парсера.
    """
    print("--- Запуск парсера для теста ---")
    latest_articles = get_articles_from_page(1)
    
    if latest_articles:
        latest_articles.sort(key=lambda x: (
            datetime.strptime(x['date'], '%d.%m.%y'), 
            datetime.strptime(x['time'], '%H:%M')
        ), reverse=True)
        
        latest_article = latest_articles[0]
        
        print(f"\n--- Найдена последняя новость ---")
        print(f"Заголовок: {latest_article['title']}")
        print(f"Ссылка: {latest_article['link']}")
        
        print("\n--- Получение полного текста статьи... ---")
        full_text = get_article_text(latest_article['link'])
        
        if full_text:
            print("--- Полный текст статьи получен. ---")
            
            print("\n--- Суммаризация текста... ---")
            summary = summarize_text_local(full_text)
            if summary:
                print("\n--- РЕЗЮМЕ НОВОСТИ ---")
                print(summary)
            else:
                print("Не удалось получить резюме.")
        else:
            print("Не удалось получить полный текст статьи.")
    else:
        print("Не удалось найти последние новости.")

    print("\n--- Парсер завершил работу ---")

if __name__ == "__main__":
    main()
