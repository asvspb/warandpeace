import os
from dotenv import load_dotenv, find_dotenv

# Ищем .env файл и загружаем переменные, перезаписывая существующие
load_dotenv(find_dotenv(), override=True)

# --- Основные переменные окружения ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID")

# --- Ключи API ---
# Динамически собираем все ключи Google API из переменных окружения
GOOGLE_API_KEYS = []
for i in range(1, 10): # Проверяем ключи от GOOGLE_API_KEY_1 до GOOGLE_API_KEY_9
    key = os.getenv(f"GOOGLE_API_KEY_{i}")
    if key:
        GOOGLE_API_KEYS.append(key)
# Добавляем основной ключ, если он есть
main_key = os.getenv("GOOGLE_API_KEY")
if main_key:
    GOOGLE_API_KEYS.insert(0, main_key) # Вставляем его в начало для приоритета

# --- Настройки парсера ---
NEWS_URL = "https://www.warandpeace.ru/ru/news/"

# --- Проверка ключевых переменных ---
if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_ADMIN_ID]):
    missing_vars = []
    if not TELEGRAM_BOT_TOKEN: missing_vars.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHANNEL_ID: missing_vars.append("TELEGRAM_CHANNEL_ID")
    if not TELEGRAM_ADMIN_ID: missing_vars.append("TELEGRAM_ADMIN_ID")
    raise ValueError(f"Ключевые переменные Telegram не заданы: {', '.join(missing_vars)}. Проверьте ваш .env файл.")

if not GOOGLE_API_KEYS:
    raise ValueError("Не найден ни один ключ Google API (GOOGLE_API_KEY, GOOGLE_API_KEY_1 и т.д.). Проверьте ваш .env файл.")