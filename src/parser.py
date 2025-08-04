import requests
from bs4 import BeautifulSoup
from datetime import datetime
import feedparser
import logging

from config import NEWS_URL
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=4, max=10),
       retry=retry_if_exception_type(requests.exceptions.RequestException))
def get_article_text(url: str) -> str | None:
    """
    Синхронно получает полный текст статьи по URL.
    """
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        response.encoding = 'windows-1251' 
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        content_div = soup.select_one('.content-item__text, .topic_text, .news-text, .article-text, .text')
        
        if content_div:
            for s in content_div.select('script, style'):
                s.decompose()
            parts = [p.get_text(separator=' ', strip=True) for p in content_div.find_all('p') if p.get_text(strip=True)]
            return '\n\n'.join(parts)
        else:
            logger.warning(f"Не удалось найти текст статьи для {url}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка сети или HTTP при загрузке статьи {url}: {e}")
        return None
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
    list_url = f"{NEWS_URL}?page={page}"
    try:
        response = requests.get(list_url, timeout=20)
        response.raise_for_status()
        response.encoding = 'windows-1251'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        articles = []
        for item in soup.select('.news-item'):
            title_element = item.select_one('.news-item__title a')
            time_element = item.select_one('.news-item__date')
            
            if title_element and time_element:
                articles.append({
                    "title": title_element.get_text(strip=True),
                    "link": "https://www.warandpeace.ru" + title_element['href'],
                    "date": datetime.now().date(), 
                    "time": time_element.get_text(strip=True)
                })
        return articles
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка сети или HTTP при загрузке страницы новостей: {e}")
        return []
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка при парсинге страницы новостей: {e}")
        return []

def get_articles_from_rss():
    """
    Получает статьи из RSS-ленты.
    """
    try:
        feed = feedparser.parse(NEWS_URL + "rss.xml")
        if feed.bozo:
            raise feed.bozo_exception
            
        articles = []
        for entry in feed.entries:
            articles.append({
                "title": entry.title,
                "link": entry.link,
                "date": datetime(*entry.published_parsed[:6]),
                "time": datetime(*entry.published_parsed[:6]).strftime('%H:%M')
            })
        return articles
    except Exception as e:
        logger.error(f"Ошибка при парсинге RSS: {e}")
        return []
