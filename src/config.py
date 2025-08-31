import os
import sys
try:
    from dotenv import load_dotenv
except Exception:  # optional dependency in local runs/tests
    def load_dotenv(*args, **kwargs):  # type: ignore
        return False
from zoneinfo import ZoneInfo
from datetime import datetime

# Определяем абсолютный путь к директории, где находится этот файл (src)
src_dir = os.path.dirname(os.path.abspath(__file__))
# Определяем корень проекта (на один уровень выше)
project_root = os.path.dirname(src_dir)

# Явно указываем путь к .env файлу в корне проекта
dotenv_path = os.path.join(project_root, '.env')

# Загружаем переменные из найденного .env файла.
# Примечание: во время pytest избегаем жёсткого override, чтобы тесты могли
# управлять окружением через patch.dict без влияния локального .env.
_running_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
load_dotenv(dotenv_path=dotenv_path, override=(not _running_pytest))

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


# --- Служебные промпты (без ротации) ---
# Флаг включения служебных промптов (JSON-строгих шаблонов). Используются фиксированные шаблоны v1.
SERVICE_PROMPTS_ENABLED = os.getenv("SERVICE_PROMPTS_ENABLED", "true").strip().lower() in {"1", "true", "yes"}

# --- Telegram канал для служебных прогнозов ---
SERVICE_TG_ENABLED = os.getenv("SERVICE_TG_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
SERVICE_TG_CHANNEL_ID = os.getenv("SERVICE_TG_CHANNEL_ID")

# --- Автообновление и авто-суммаризация ---
# Режимы: auto|manual. По умолчанию manual (ничего не запускаем автоматически)
BASE_AUTO_UPDATE = os.getenv("BASE_AUTO_UPDATE", "manual").strip().lower()
BASE_AUTO_SUM = os.getenv("BASE_AUTO_SUM", "manual").strip().lower()

# Модель для авто-суммаризации: gemini|mistral (по умолчанию gemini)
BASE_AUTO_SUM_MODEL = os.getenv("BASE_AUTO_SUM_MODEL", "gemini").strip().lower()

# Целевая дата (нижняя граница), до которой идем «от настоящего к прошлому».
# Ожидаемый формат: "ДД.ММ.ГГГГ". Если не задано или неверно — используем 01.01.1970.
_date_str = os.getenv("BASE_AUTO_UPDATE_DATE_TARGET", "01.01.1970").strip()
def _parse_target_date(date_str: str) -> datetime:
    try:
        # Начало суток в таймзоне приложения
        dt = datetime.strptime(date_str, "%d.%m.%Y").replace(hour=0, minute=0, second=0, microsecond=0)
        # Преобразуем в aware с таймзоной приложения
        return dt.replace(tzinfo=APP_TZ)
    except Exception:
        # Фолбэк на эпоху, чтобы не блокировать работу
        return datetime(1970, 1, 1, tzinfo=APP_TZ)

BASE_AUTO_UPDATE_TARGET_DT = _parse_target_date(_date_str)

# Optional explicit period string: "DD.MM.YYYY-DD.MM.YYYY" (left=upper bound/to, right=lower bound/from)
BASE_AUTO_UPDATE_PERIOD = os.getenv("BASE_AUTO_UPDATE_PERIOD", "").strip()
def _parse_period(period_str: str):
    try:
        if not period_str:
            return None, None, None
        parts = [p.strip() for p in period_str.split("-")]
        if len(parts) != 2:
            return None, None, None
        to_dt = datetime.strptime(parts[0], "%d.%m.%Y").replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=APP_TZ)
        from_dt = datetime.strptime(parts[1], "%d.%m.%Y").replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=APP_TZ)
        return period_str, to_dt, from_dt
    except Exception:
        return None, None, None

_period_str, BASE_AUTO_UPDATE_FROM_DT, _from_dt_override = _parse_period(BASE_AUTO_UPDATE_PERIOD)
# If period provided, prefer its lower bound for target; otherwise keep original target
if _from_dt_override is not None:
    BASE_AUTO_UPDATE_TARGET_DT = _from_dt_override

def _compute_period_string() -> str:
    try:
        # If explicit period string provided and parsed, reuse as-is
        if _period_str:
            return _period_str
        # Else construct from now (upper bound) to target (lower bound)
        now_str = datetime.now(APP_TZ).strftime("%d.%m.%Y")
        from_str = BASE_AUTO_UPDATE_TARGET_DT.strftime("%d.%m.%Y")
        return f"{now_str}-{from_str}"
    except Exception:
        return ""

BASE_AUTO_UPDATE_PERIOD_STRING = _compute_period_string()

# --- Backfill performance knobs ---
BACKFILL_CONCURRENCY = int(os.getenv("BACKFILL_CONCURRENCY", "4").strip() or "4")
BACKFILL_SLEEP_ITEM_MS = int(os.getenv("BACKFILL_SLEEP_ITEM_MS", "50").strip() or "50")
BACKFILL_SLEEP_PAGE_MS = int(os.getenv("BACKFILL_SLEEP_PAGE_MS", "200").strip() or "200")

# --- API usage persistence config ---
API_USAGE_PERSISTENCE_ENABLED = os.getenv("API_USAGE_PERSISTENCE_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
API_USAGE_FLUSH_INTERVAL_SEC = int(os.getenv("API_USAGE_FLUSH_INTERVAL_SEC", "60").strip() or "60")
API_USAGE_INCLUDE_TELEGRAM = os.getenv("API_USAGE_INCLUDE_TELEGRAM", "false").strip().lower() in {"1", "true", "yes"}
API_USAGE_EVENTS_TTL_DAYS = int(os.getenv("API_USAGE_EVENTS_TTL_DAYS", "30").strip() or "30")

# --- Session stats persistence (per-day) ---
# When enabled, selected runtime counters (HTTP requests, articles processed)
# are persisted into SQLite per calendar day and available in web UI history.
SESSION_STATS_ENABLED = os.getenv("SESSION_STATS", "false").strip().lower() in {"1", "true", "yes"}