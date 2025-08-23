import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import logging
from urllib.parse import urljoin
from url_utils import canonicalize_url

from config import NEWS_URL, APP_TZ
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Import metrics
try:
    from metrics import EXTERNAL_HTTP_REQUESTS_TOTAL, EXTERNAL_HTTP_REQUEST_DURATION_SECONDS
except ImportError:
    # Fallback if metrics module is not available
    class _NoopMetric:
        def __init__(self, *args, **kwargs):
            pass
        def inc(self, *args, **kwargs):
            return None
        def observe(self, *args, **kwargs):
            return None
        def labels(self, *args, **kwargs):
            return self
    EXTERNAL_HTTP_REQUESTS_TOTAL = _NoopMetric()
    EXTERNAL_HTTP_REQUEST_DURATION_SECONDS = _NoopMetric()

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ARCHIVE_SEARCH_BASE_URL = "https://www.warandpeace.ru/ru/archive/search/_/"

def _parse_custom_date(date_str: str) -> datetime:
    """
    Парсит строку с датой, пробуя несколько распространенных форматов.
    Поддерживает форматы 'ДД.ММ.ГГ ЧЧ:ММ' и 'ДД.ММ.ГГГГ ЧЧ:ММ'.
    Возвращает timezone-aware datetime объект (Europe/Moscow).
    """
    dt_naive = None
    try:
        # Сначала пробуем формат с 4-значным годом, как более современный
        dt_naive = datetime.strptime(date_str, '%d.%m.%Y %H:%M')
    except ValueError:
        # Если не получилось, пробуем с 2-значным годом
        dt_naive = datetime.strptime(date_str, '%d.%m.%y %H:%M')
    
    # Делаем наивный datetime aware с таймзоной приложения
    return dt_naive.replace(tzinfo=APP_TZ)

@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=4, max=10),
       retry=retry_if_exception_type(requests.exceptions.RequestException))
def get_article_text(url: str) -> str | None:
    """
    Синхронно получает полный текст статьи по URL.
    """
    try:
        start = time.time()
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        duration = max(0.0, time.time() - start)
        # Observe duration and increment counters
        try:
            EXTERNAL_HTTP_REQUEST_DURATION_SECONDS.labels("rss").observe(duration)
            status_group = f"{response.status_code // 100}xx"
            EXTERNAL_HTTP_REQUESTS_TOTAL.labels("rss", "GET", status_group).inc()
        except Exception:
            pass
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
        try:
            EXTERNAL_HTTP_REQUESTS_TOTAL.labels("rss", "GET", "timeout" if isinstance(e, requests.Timeout) else "5xx").inc()
        except Exception:
            pass
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
    Возвращает 'published_at' как timezone-aware datetime объект.
    """
    list_url = f"{NEWS_URL}?page={page}"
    base_url = "https://www.warandpeace.ru"
    try:
        start = time.time()
        response = requests.get(list_url, timeout=20)
        response.raise_for_status()
        duration = max(0.0, time.time() - start)
        try:
            EXTERNAL_HTTP_REQUEST_DURATION_SECONDS.labels("rss").observe(duration)
            status_group = f"{response.status_code // 100}xx"
            EXTERNAL_HTTP_REQUESTS_TOTAL.labels("rss", "GET", status_group).inc()
        except Exception:
            pass
        response.encoding = 'windows-1251'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        articles = []
        # Находим все таблицы, которые являются обертками для новостей
        for item in soup.find_all('table', {'border': '0', 'align': 'center', 'cellspacing': '0', 'width': '100%'}):
            title_element = item.select_one('.topic_caption a')
            time_element = item.select_one('.topic_info_top')
            
            if title_element and time_element and title_element.has_attr('href'):
                raw_url = urljoin(base_url, title_element['href'])
                article_url = canonicalize_url(raw_url)
                
                # Извлечение и парсинг даты и времени
                time_str = time_element.get_text(strip=True)
                try:
                    # dt_object теперь будет timezone-aware
                    dt_object = _parse_custom_date(time_str)
                except ValueError:
                    logger.warning(f"Не удалось распарсить дату из '{time_str}'. Используется текущее время.")
                    # now_msk() вернет aware datetime
                    dt_object = datetime.now(APP_TZ)

                articles.append({
                    "title": title_element.get_text(strip=True),
                    "link": article_url,
                    "published_at": dt_object  # Возвращаем datetime объект
                })
        return articles
    except requests.exceptions.RequestException as e:
        try:
            EXTERNAL_HTTP_REQUESTS_TOTAL.labels("rss", "GET", "timeout" if isinstance(e, requests.Timeout) else "5xx").inc()
        except Exception:
            pass
        logger.error(f"Ошибка сети или HTTP при загрузке страницы новостей: {e}")
        return []
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка при парсинге страницы новостей: {e}")
        return []



