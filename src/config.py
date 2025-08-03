import os
from dotenv import load_dotenv, find_dotenv

# Ищем .env файл и загружаем переменные, перезаписывая существующие
load_dotenv(find_dotenv(), override=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_API_KEY_1 = os.getenv("GOOGLE_API_KEY_1")
GOOGLE_API_KEY_2 = os.getenv("GOOGLE_API_KEY_2")
GOOGLE_API_KEY_3 = os.getenv("GOOGLE_API_KEY_3")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Настройки парсера
NEWS_URL = "https://www.warandpeace.ru/ru/news/"

# Собираем все ключи Gemini в список
GOOGLE_API_KEYS = [key for key in [GOOGLE_API_KEY, GOOGLE_API_KEY_1, GOOGLE_API_KEY_2, GOOGLE_API_KEY_3] if key]

# Проверяем, что все ключевые переменные были загружены
if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_ADMIN_ID]) or not (GOOGLE_API_KEYS or OPENROUTER_API_KEY):
    # Формируем сообщение об ошибке
    missing_vars = []
    if not TELEGRAM_BOT_TOKEN: missing_vars.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHANNEL_ID: missing_vars.append("TELEGRAM_CHANNEL_ID")
    if not TELEGRAM_ADMIN_ID: missing_vars.append("TELEGRAM_ADMIN_ID")
    if not GOOGLE_API_KEYS and not OPENROUTER_API_KEY: missing_vars.append("Хотя бы один из GOOGLE_API_KEY, GOOGLE_API_KEY_1, GOOGLE_API_KEY_2, GOOGLE_API_KEY_3 или OPENROUTER_API_KEY")
    
    raise ValueError(f"Переменные окружения не заданы: {', '.join(missing_vars)}. Проверьте ваш .env файл.")
