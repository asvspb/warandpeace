import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import logging
from urllib.parse import urljoin

from config import NEWS_URL
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ARCHIVE_SEARCH_BASE_URL = "https://www.warandpeace.ru/ru/archive/search/_/"

def _parse_custom_date(date_str: str) -> datetime:
    """
    Парсит строку с датой, пробуя несколько распространенных форматов.
    Поддерживает форматы 'ДД.ММ.ГГ ЧЧ:ММ' и 'ДД.ММ.ГГГГ ЧЧ:ММ'.
    """
    try:
        # Сначала пробуем формат с 4-значным годом, как более современный
        return datetime.strptime(date_str, '%d.%m.%Y %H:%M')
    except ValueError:
        # Если не получилось, пробуем с 2-значным годом
        return datetime.strptime(date_str, '%d.%m.%y %H:%M')

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
        
        content_div = soup.select_one('td.topic_text')
        
        if content_div:
            for s in content_div.select('script, style'):
                s.decompose()
            return content_div.get_text(separator='\n', strip=True)
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
    Получает список статей с заданной страницы новостей (для текущих новостей).
    """
    list_url = f"{NEWS_URL}?page={page}"
    base_url = "https://www.warandpeace.ru"
    try:
        response = requests.get(list_url, timeout=20)
        response.raise_for_status()
        response.encoding = 'windows-1251'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        articles = []
        # Находим все таблицы, которые являются обертками для новостей
        for item in soup.find_all('table', {'border': '0', 'align': 'center', 'cellspacing': '0', 'width': '100%'}):
            title_element = item.select_one('.topic_caption a')
            time_element = item.select_one('.topic_info_top')
            
            if title_element and time_element and title_element.has_attr('href'):
                article_url = urljoin(base_url, title_element['href'])
                
                # Извлечение и парсинг даты и времени
                time_str = time_element.get_text(strip=True)
                try:
                    # Используем новую функцию для большей гибкости
                    dt_object = _parse_custom_date(time_str)
                    published_at_iso = dt_object.isoformat()
                except ValueError:
                    logger.warning(f"Не удалось распарсить дату из '{time_str}'. Используется текущее время.")
                    published_at_iso = datetime.now().isoformat()

                articles.append({
                    "title": title_element.get_text(strip=True),
                    "link": article_url,
                    "published_at": published_at_iso
                })
        return articles
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка сети или HTTP при загрузке страницы новостей: {e}")
        return []
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка при парсинге страницы новостей: {e}")
        return []



