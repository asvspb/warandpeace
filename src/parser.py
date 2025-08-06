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

# Относительный импорт, так как database.py находится в том же каталоге src
from database import (
    init_db, 
    add_article, 
    get_latest_article_timestamp,
    get_article_urls_in_range
)

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

@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=4, max=10),
       retry=retry_if_exception_type(requests.exceptions.RequestException))
def get_articles_from_archive_search(start_date_str: str, end_date_str: str, page: int = 1):
    """
    Получает список статей из архива по заданным датам и номеру страницы.
    Возвращает список статей и общее количество страниц результатов поиска.
    """
    search_url = (
        f"{ARCHIVE_SEARCH_BASE_URL}page={page}/?" 
        f"text_header=&author=&topic=&" 
        f"date_st={start_date_str}&sselect=0&" 
        f"date_en={end_date_str}&archive_sort="
    )
    base_url = "https://www.warandpeace.ru"
    
    try:
        response = requests.get(search_url, timeout=20)
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
        
        # Извлечение общего количества страниц
        total_pages = 1
        pagination_info = soup.find('span', class_='menu_1', string=lambda text: text and 'Страница' in text)
        if pagination_info:
            import re
            match = re.search(r'из\s+(\d+)', pagination_info.get_text())
            if match:
                total_pages = int(match.group(1))

        return articles, total_pages
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка сети или HTTP при загрузке страницы архива: {e}")
        return [], 0
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка при парсинге страницы архива: {e}")
        return [], 0

def fetch_articles_in_date_range(start_date: datetime, end_date: datetime) -> list:
    """
    Собирает все статьи из архива в заданном диапазоне дат.
    """
    all_articles = []
    page = 1
    total_pages = 1 # Инициализируем для первого прохода

    start_date_str = start_date.strftime("%d.%m.%Y")
    end_date_str = end_date.strftime("%d.%m.%Y")

    logger.info(f"Начинаю сбор статей из архива с {start_date_str} по {end_date_str}...")

    while page <= total_pages:
        logger.info(f"Загружаю страницу {page} из {total_pages}...")
        articles_on_page, current_total_pages = get_articles_from_archive_search(start_date_str, end_date_str, page)
        
        if not articles_on_page and page == 1:
            logger.warning("Не найдено статей в указанном диапазоне дат или ошибка при загрузке первой страницы.")
            break
        
        if current_total_pages > total_pages:
            total_pages = current_total_pages # Обновляем общее количество страниц

        for article in articles_on_page:
            # Проверяем, что дата статьи находится в нужном диапазоне
            # Это важно, так как get_articles_from_archive_search может вернуть статьи за пределами диапазона
            # из-за особенностей пагинации или если последняя страница содержит статьи за пределами диапазона
            article_date = datetime.fromisoformat(article['published_at'])
            if start_date <= article_date <= end_date:
                all_articles.append(article)
            else:
                # Если статья вне диапазона, и мы уже прошли нужный диапазон, можно прервать
                # (предполагая, что статьи на странице отсортированы по дате)
                if article_date < start_date:
                    logger.info(f"Найдена статья {article['title']} ({article['published_at']}) раньше начальной даты. Завершаю сбор.")
                    page = total_pages + 1 # Выход из цикла
                    break

        page += 1

    logger.info(f"Сбор статей из архива завершен. Всего найдено {len(all_articles)} статей.")
    return all_articles

def reconcile_archive_with_db():
    """
    Сверяет архив новостей с базой данных и добавляет недостающие статьи.
    Начинает с даты последней статьи в БД и идет до текущего момента.
    """
    init_db()
    
    latest_timestamp_str = get_latest_article_timestamp()
    if latest_timestamp_str:
        start_date = datetime.fromisoformat(latest_timestamp_str)
    else:
        # Если база пуста, начинаем с какой-то разумной даты, например, 30 дней назад
        start_date = datetime.now() - timedelta(days=30)
        logger.info("База данных пуста. Начинаю сверку за последние 30 дней.")

    end_date = datetime.now()
    
    # Получаем все URL из БД в этом диапазоне для быстрой проверки
    existing_urls = get_article_urls_in_range(start_date.isoformat(), end_date.isoformat())
    logger.info(f"В базе данных уже есть {len(existing_urls)} статей в диапазоне с {start_date.strftime('%Y-%m-%d')} по {end_date.strftime('%Y-%m-%d')}.")

    # Собираем статьи из архива
    archive_articles = fetch_articles_in_date_range(start_date, end_date)
    
    added_count = 0
    for article in archive_articles:
        if article['link'] not in existing_urls:
            add_article(article['link'], article['title'], article['published_at'])
            added_count += 1
            logger.info(f"Добавлена новая статья: {article['title']}")
    
    logger.info(f"Сверка завершена. Добавлено {added_count} новых статей.")
    return added_count
