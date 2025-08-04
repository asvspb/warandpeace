import os
import sys
import time
import logging
import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Добавляем путь к src для импорта конфига
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID, NEWS_URL

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@retry(stop=stop_after_attempt(3), 
       wait=wait_exponential(multiplier=1, min=4, max=10),
       retry=retry_if_exception_type(requests.exceptions.RequestException))
def send_telegram_alert(message):
    """Отправляет сообщение в Telegram.

    Args:
        message (str): Текст сообщения для отправки.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_ID:
        logger.error("Токен бота или ID администратора не найдены. Не могу отправить сообщение.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_ADMIN_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Оповещение успешно отправлено администратору.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Не удалось отправить оповещение в Telegram: {e}")

def check_parser_health():
    """
    Проверяет работоспособность селекторов парсера на сайте.
    Возвращает True, если селекторы работают, иначе False.
    """
    try:
        response = requests.get(NEWS_URL, timeout=20)
        response.raise_for_status()
        response.encoding = 'windows-1251'
        soup = BeautifulSoup(response.text, 'html.parser')

        # Ищем хотя бы один новостной блок
        item = soup.find('table', {'border': '0', 'align': 'center', 'cellspacing': '0', 'width': '100%'})
        if not item:
            logger.error("Не удалось найти ни одного новостного блока. Селектор для контейнера устарел.")
            return False

        # Проверяем наличие заголовка и даты в найденном блоке
        title_element = item.select_one('.topic_caption a')
        time_element = item.select_one('.topic_info_top')

        if title_element and time_element and title_element.get_text(strip=True) and time_element.get_text(strip=True):
            logger.info("Проверка селекторов прошла успешно. Найдена как минимум одна статья.")
            return True
        else:
            logger.error("Селекторы для заголовка или даты не сработали. Структура статьи изменилась.")
            return False

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка сети при проверке работоспособности парсера: {e}")
        # В случае сетевой ошибки не отправляем алерт, т.к. это временная проблема
        return True # Считаем, что с парсером все в порядке
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при проверке парсера: {e}")
        return False

def run_daily_check():
    """
    Запускает ежедневную проверку работоспособности парсера.
    """
    logger.info("Запуск ежедневной проверки работоспособности парсера...")
    while True:
        if not check_parser_health():
            alert_message = (
                "*ВНИМАНИЕ! Обнаружена проблема с парсером!\n\n"
                "Не удалось найти статьи на сайте `warandpeace.ru`. "
                "Вероятно, изменилась структура HTML-кода страницы.\n\n"
                "Рекомендуется срочно проверить и обновить селекторы в `src/parser.py`."
            )
            send_telegram_alert(alert_message)
        
        logger.info("Проверка завершена. Следующая проверка через 24 часа.")
        time.sleep(24 * 60 * 60) # Пауза на 24 часа

if __name__ == "__main__":
    run_daily_check()