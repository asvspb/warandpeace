import os
import sys
try:
    from dotenv import load_dotenv
except Exception:  # optional dependency in local runs/tests
    def load_dotenv(*args, **kwargs):  # type: ignore
        return False
from zoneinfo import ZoneInfo

# Определяем абсолютный путь к директории, где находится этот файл (src)
src_dir = os.path.dirname(os.path.abspath(__file__))
# Определяем корень проекта (на один уровень выше)
project_root = os.path.dirname(src_dir)

# Явно указываем путь к .env файлу в корне проекта
dotenv_path = os.path.join(project_root, '.env')

# Загружаем переменные из найденного .env файла.
# Это нужно для локальных запусков скриптов. В Docker Compose переменные
# подставляются напрямую из env_file, и override=True гарантирует,
# что они будут иметь приоритет над локальным .env.
load_dotenv(dotenv_path=dotenv_path, override=True)

# --- Путь к БД ---
DB_SQLITE_PATH = os.getenv("DB_SQLITE_PATH", "/app/database/articles.db")

# --- Основные переменные окружения ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID")

# --- Ключи API и провайдеры ---
# Управление провайдерами LLM
LLM_PRIMARY = os.getenv("LLM_PRIMARY", "gemini").strip().lower()
GEMINI_ENABLED = os.getenv("GEMINI_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
MISTRAL_ENABLED = os.getenv("MISTRAL_ENABLED", "true").strip().lower() in {"1", "true", "yes"}

# Ключи API
# Динамически собираем все ключи Google API из переменных окружения
GOOGLE_API_KEYS = []

# Сначала пытаемся прочитать переменную GOOGLE_API_KEYS, которая может содержать несколько ключей через запятую
keys_from_env = os.getenv("GOOGLE_API_KEYS")
if keys_from_env:
    GOOGLE_API_KEYS = [key.strip() for key in keys_from_env.split(',') if key.strip()]

# Если переменная GOOGLE_API_KEYS не найдена, используем старый метод для обратной совместимости
if not GOOGLE_API_KEYS:
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

# --- Настройки времени ---
APP_TZ_NAME = os.getenv("TIMEZONE", "Europe/Moscow")
try:
    APP_TZ = ZoneInfo(APP_TZ_NAME)
except Exception:
    print(f"ERROR: Invalid timezone '{APP_TZ_NAME}'. Defaulting to UTC.", file=sys.stderr)
    APP_TZ = ZoneInfo("UTC")


# --- Проверка ключевых переменных (мягкая) ---
# Не прерываем импорт модулей при отсутствии переменных — это важно для тестов и
# для использования библиотечных функций вне основного процесса бота.
MISSING_TG_VARS = not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_ADMIN_ID])
MISSING_GOOGLE_KEYS = not bool(GOOGLE_API_KEYS)