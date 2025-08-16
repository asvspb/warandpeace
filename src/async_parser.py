import asyncio
import httpx
from url_utils import canonicalize_url
from bs4 import BeautifulSoup
from datetime import datetime, date, timedelta
import logging
from urllib.parse import urljoin
import re

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%d/%m-%y - [%H:%M]'
)
logger = logging.getLogger(__name__)

ARCHIVE_SEARCH_BASE_URL = "https://www.warandpeace.ru/ru/archive/search/_/"
NEWS_URL = "https://www.warandpeace.ru/ru/news/"
BASE_URL = "https://www.warandpeace.ru"

@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=4, max=10),
       retry=retry_if_exception_type(httpx.RequestError))
async def get_articles_from_main_page(client: httpx.AsyncClient, page: int = 1):
    """
    Асинхронно получает список статей с главной страницы новостей.
    """
    url = f"{NEWS_URL}?page={page}"
    try:
        response = await client.get(url, timeout=20)
        response.raise_for_status()
        response.encoding = 'windows-1251'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        articles = []
        news_tables = soup.find_all('table', {'border': '0', 'align': 'center', 'cellspacing': '0', 'width': '100%'})[1:]

        for item in news_tables:
            title_element = item.select_one('.topic_caption a')
            time_element = item.select_one('.topic_info_top')
            
            if title_element and time_element and title_element.has_attr('href'):
                article_url = canonicalize_url(urljoin(BASE_URL, title_element['href']))
                title = title_element.get_text(strip=True)
                time_str = time_element.get_text(strip=True)
                try:
                    # Формат: 14.07.24 11:09
                    dt_object = datetime.strptime(time_str, '%d.%m.%y %H:%M')
                    # Отсекаем заведомо неверные даты в будущем
                    if dt_object.date() > date.today() + timedelta(days=1):
                        logger.warning(f"Найдена статья с датой в будущем: {dt_object}. Пропуск.")
                        continue
                except ValueError:
                    logger.warning(f"Не удалось распарсить дату '{time_str}'. Пропуск статьи.")
                    continue
                
                articles.append({"title": title, "link": article_url, "published_at": dt_object})
        return articles
    except httpx.RequestError as e:
        logger.error(f"Ошибка сети или HTTP при загрузке страницы новостей {url}: {e}")
        return []
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка при парсинге страницы новостей {url}: {e}")
        return []

@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=4, max=10),
       retry=retry_if_exception_type(httpx.RequestError))
async def get_articles_from_archive(client: httpx.AsyncClient, target_date_str: str, page: int = 1):
    """
    Асинхронно получает список статей из архива.
    """
    search_url = (
        f"{ARCHIVE_SEARCH_BASE_URL}page={page}/?"
        f"text_header=&author=&topic=&"
        f"date_st={target_date_str}&sselect=0&"
        f"date_en={target_date_str}&archive_sort="
    )
    try:
        response = await client.get(search_url, timeout=30)
        response.raise_for_status()
        response.encoding = 'windows-1251'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        articles = []
        news_tables = soup.find_all('table', {'border': '0', 'align': 'center', 'cellspacing': '0', 'width': '100%'})[1:]

        for item in news_tables:
            title_element = item.select_one('.topic_caption a')
            if title_element and title_element.has_attr('href'):
                article_url = canonicalize_url(urljoin(BASE_URL, title_element['href']))
                title = title_element.get_text(strip=True)
                articles.append({"title": title, "link": article_url})

        total_pages = 1
        pagination_info = soup.find('span', class_='menu_1', string=lambda text: text and 'Страница' in text)
        if pagination_info:
            match = re.search(r'из\s+(\d+)', pagination_info.get_text())
            if match:
                total_pages = int(match.group(1))

        return articles, total_pages
    except httpx.RequestError as e:
        logger.error(f"Ошибка сети или HTTP при загрузке страницы архива {search_url}: {e}")
        return [], 0
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка при парсинге страницы архива {search_url}: {e}")
        return [], 0

async def fetch_articles_for_date(target_date: date, archive_only: bool = False) -> list[tuple[str, str]]:
    """
    Универсальная функция для сбора всех статей за определенную дату.
    Сначала ищет на главной странице, затем в архиве.
    """
    mode = "archive-only" if archive_only else "universal"
    logger.info(f"Начинаю сбор статей за {target_date.strftime('%d.%m.%Y')} (mode={mode})")
    all_articles = {}

    async with httpx.AsyncClient() as client:
        # 1. Поиск на главной странице (если не архив-онли)
        if not archive_only:
            logger.info("Этап 1: Поиск на главных страницах новостей...")
            page = 1
            stop_search = False
            while not stop_search:
                logger.info(f"Загружаю главную страницу {page}...")
                articles_on_page = await get_articles_from_main_page(client, page)
                if not articles_on_page:
                    logger.info("На главной странице больше нет статей. Завершаю поиск.")
                    break

                for article in articles_on_page:
                    article_date = article["published_at"].date()
                    logger.info(f"Найдена статья: {article['title']} с датой {article_date.strftime('%Y-%m-%d')}. Сравнение с {target_date.strftime('%Y-%m-%d')}: Равно? {article_date == target_date}")
                    if article_date == target_date:
                        all_articles[article["link"]] = article["title"]
                    elif article_date < target_date:
                        # Если пошли статьи за предыдущие дни, останавливаем поиск
                        logger.info("Достигнуты статьи за предыдущие даты. Завершаю поиск на главных страницах.")
                        stop_search = True
                        break
                
                await asyncio.sleep(1)
                page += 1

        # 2. Поиск в архиве для полноты
        logger.info("Этап 2: Поиск в архиве...")
        page = 1
        total_pages = 1
        target_date_str = target_date.strftime("%d.%m.%Y")
        while page <= total_pages:
            logger.info(f"Загружаю страницу архива {page} из {total_pages}...")
            articles_on_page, current_total_pages = await get_articles_from_archive(client, target_date_str, page)
            
            if not articles_on_page and page == 1:
                logger.warning(f"В архиве не найдено статей за {target_date_str}.")
                break
            
            if current_total_pages > total_pages:
                total_pages = current_total_pages

            for article in articles_on_page:
                all_articles[article["link"]] = article["title"]
            
            await asyncio.sleep(1)
            page += 1

    logger.info(f"Универсальный сбор завершен. Всего найдено {len(all_articles)} уникальных статей.")
    return [(title, link) for link, title in all_articles.items()]
