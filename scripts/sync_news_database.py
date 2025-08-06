import logging
import os
import sys

# Настройка пути для импорта из родительских директорий
# Это делает скрипт более переносимым и позволяет запускать его из разных мест
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.insert(0, project_root)

from src.parser import get_articles_from_page, reconcile_archive_with_db
from src.database import init_db, add_article, is_article_posted, get_stats

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def _sync_from_main_feed() -> int:
    """
    Этап 1: Синхронизация с основной новостной лентой (страницы 1-15).
    Возвращает количество добавленных статей.
    """
    logger.info("--- ЭТАП 1: Синхронизация с основной новостной лентой (стр. 1-15) ---")
    added_count = 0
    for page_num in range(1, 16):
        logger.info(f"Обработка страницы {page_num}/15...")
        try:
            articles_on_page = get_articles_from_page(page=page_num)
            if not articles_on_page:
                logger.warning(f"Не удалось получить статьи со страницы {page_num}. Пропускаю.")
                continue

            for article in articles_on_page:
                if not is_article_posted(article['link']):
                    add_article(article['link'], article['title'], article['published_at'])
                    logger.info(f"  [+] Добавлена статья: \"{article['title']}\"")
                    added_count += 1
        except Exception as e:
            logger.error(f"Критическая ошибка при обработке страницы {page_num}: {e}")
    logger.info(f"--- ЭТАП 1 ЗАВЕРШЕН: Добавлено {added_count} новых статей из основной ленты. ---")
    return added_count

def _sync_from_archive() -> int:
    """
    Этап 2: Сверка с архивом для заполнения пробелов.
    Возвращает количество добавленных статей.
    """
    logger.info("\n--- ЭТАП 2: Полная сверка с архивом новостей ---")
    try:
        added_count = reconcile_archive_with_db()
        logger.info(f"--- ЭТАП 2 ЗАВЕРШЕН: Добавлено {added_count} новых статей из архива. ---")
        return added_count
    except Exception as e:
        logger.error(f"Критическая ошибка при сверке с архивом: {e}")
        return 0

def print_final_stats(initial_stats, total_added):
    """
    Выводит итоговую статистику после всех операций.
    """
    final_stats = get_stats()
    logger.info("\n--- ИТОГОВАЯ СТАТИСТИКА ---")
    logger.info(f"Новых статей добавлено за сессию: {total_added}")
    logger.info(f"Общее количество статей: {initial_stats.get('total_articles', 'N/A')} -> {final_stats.get('total_articles', 'N/A')}")
    last_article = final_stats.get('last_article')
    if last_article:
        logger.info(f"Последняя статья в базе: '{last_article.get('title', 'N/A')}' ({last_article.get('published_at', 'N/A')})")
    logger.info("--------------------------------")

def sync_news_database():
    """
    Выполняет полную синхронизацию базы данных: сначала по основной ленте,
    затем сверяется с архивом.
    """
    init_db()
    logger.info("*** НАЧАЛО ПОЛНОЙ СИНХРОНИЗАЦИИ БАЗЫ ДАННЫХ ***")
    
    initial_stats = get_stats()
    
    # Выполняем оба этапа
    added_from_feed = _sync_from_main_feed()
    added_from_archive = _sync_from_archive()
    
    total_added = added_from_feed + added_from_archive
    
    print_final_stats(initial_stats, total_added)
    
    logger.info("*** ПОЛНАЯ СИНХРОНИЗАЦИЯ БАЗЫ ДАННЫХ ЗАВЕРШЕНА ***")

if __name__ == "__main__":
    sync_news_database()