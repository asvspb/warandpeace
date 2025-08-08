import os
import sys

from dotenv import load_dotenv

# Определяем абсолютный путь к директории, где находится этот файл (src)
src_dir = os.path.dirname(os.path.abspath(__file__))
# Определяем корень проекта (на один уровень выше)
project_root = os.path.dirname(src_dir)

# Явно указываем путь к .env файлу в корне проекта
dotenv_path = os.path.join(project_root, ".env")

# Загружаем переменные из найденного .env файла
# Этот подход надежнее, чем find_dotenv(), при запусках из разных директорий.
load_dotenv(dotenv_path=dotenv_path, override=True)

# --- Основные переменные окружения ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

# --- Администраторы ---
# Собираем ID администраторов из разных переменных для гибкости.
# Используем set для автоматического удаления дубликатов.
admin_ids_set = set()

# 1. Из переменной со списком через запятую (приоритет)
admin_ids_csv = os.getenv("TELEGRAM_ADMIN_IDS")
if admin_ids_csv:
    for admin_id in admin_ids_csv.split(","):
        if admin_id.strip():
            admin_ids_set.add(admin_id.strip())

# 2. Из одиночной переменной (для обратной совместимости)
admin_id_single = os.getenv("TELEGRAM_ADMIN_ID")
if admin_id_single:
    admin_ids_set.add(admin_id_single.strip())

# Итоговый список администраторов
TELEGRAM_ADMIN_IDS = list(admin_ids_set)

# Оставляем одиночную переменную для обратной совместимости со старым кодом.
# Если список админов пуст, эта переменная будет None.
# Если не пуст, будет взят первый элемент из списка.
TELEGRAM_ADMIN_ID = TELEGRAM_ADMIN_IDS[0] if TELEGRAM_ADMIN_IDS else None


# --- Ключи API ---
# Динамически собираем все ключи Google API из переменных окружения.
# Используем set для удаления дубликатов, сохраняя порядок добавления.
seen_keys = set()
GOOGLE_API_KEYS = []


def add_key(key):
    """Добавляет ключ в список, если он не пустой и еще не был добавлен."""
    if key and key not in seen_keys:
        seen_keys.add(key)
        GOOGLE_API_KEYS.append(key)


# 1. Приоритет: переменная GOOGLE_API_KEYS с CSV
keys_from_csv = os.getenv("GOOGLE_API_KEYS")
if keys_from_csv:
    for k in keys_from_csv.split(","):
        add_key(k.strip())

# 2. Основной ключ GOOGLE_API_KEY (для обратной совместимости)
add_key(os.getenv("GOOGLE_API_KEY"))

# 3. Нумерованные ключи GOOGLE_API_KEY_1..9 (для обратной совместимости)
for i in range(1, 10):
    add_key(os.getenv(f"GOOGLE_API_KEY_{i}"))

# --- Настройки парсера ---
NEWS_URL = "https://www.warandpeace.ru/ru/news/"

# --- Настройки AI моделей ---
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "models/gemini-1.5-flash-latest")

# --- Проверка ключевых переменных ---
# TELEGRAM_ADMIN_ID больше не является обязательным для запуска.
if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID]):
    missing_vars = []
    if not TELEGRAM_BOT_TOKEN:
        missing_vars.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHANNEL_ID:
        missing_vars.append("TELEGRAM_CHANNEL_ID")

    # Сообщение об ошибке будет вызвано только если есть недостающие переменные.
    if missing_vars:
        raise ValueError(f"Ключевые переменные Telegram не заданы: {', '.join(missing_vars)}. Проверьте ваш .env файл.")

if not GOOGLE_API_KEYS:
    raise ValueError(
        "Не найден ни один ключ Google API (GOOGLE_API_KEYS, GOOGLE_API_KEY, GOOGLE_API_KEY_1 и т.д.). Проверьте ваш .env файл."
    )
