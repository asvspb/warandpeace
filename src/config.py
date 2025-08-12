import os
import sys
from dotenv import load_dotenv

# Определяем абсолютный путь к директории, где находится этот файл (src)
src_dir = os.path.dirname(os.path.abspath(__file__))
# Определяем корень проекта (на один уровень выше)
project_root = os.path.dirname(src_dir)

# Явно указываем путь к .env файлу в корне проекта
dotenv_path = os.path.join(project_root, '.env')

# Загружаем переменные из найденного .env файла
# Этот подход надежнее, чем find_dotenv(), при запусках из разных директорий.
load_dotenv(dotenv_path=dotenv_path, override=True)

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

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

# --- Настройки парсера ---
NEWS_URL = "https://www.warandpeace.ru/ru/news/"

# --- Настройки AI моделей ---
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "models/gemini-1.5-flash-latest")
MISTRAL_MODEL_NAME = os.getenv("MISTRAL_MODEL_NAME", "mistral-large-latest")

# --- Проверка ключевых переменных ---
if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_ADMIN_ID]):
    missing_vars = []
    if not TELEGRAM_BOT_TOKEN: missing_vars.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHANNEL_ID: missing_vars.append("TELEGRAM_CHANNEL_ID")
    if not TELEGRAM_ADMIN_ID: missing_vars.append("TELEGRAM_ADMIN_ID")
    raise ValueError(f"Ключевые переменные Telegram не заданы: {', '.join(missing_vars)}. Проверьте ваш .env файл.")

if not GOOGLE_API_KEYS:
    raise ValueError("Не найден ни один ключ Google API (GOOGLE_API_KEY, GOOGLE_API_KEY_1 и т.д.). Проверьте ваш .env файл.")