import os
from dotenv import load_dotenv, find_dotenv

# Ищем .env файл и загружаем переменные, перезаписывая существующие
load_dotenv(find_dotenv(), override=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
AI_API_KEY = os.getenv("AI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Проверяем, что все ключевые переменные были загружены
if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, AI_API_KEY, OPENROUTER_API_KEY]):
    # Формируем сообщение об ошибке
    missing_vars = []
    if not TELEGRAM_BOT_TOKEN: missing_vars.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHANNEL_ID: missing_vars.append("TELEGRAM_CHANNEL_ID")
    if not AI_API_KEY: missing_vars.append("AI_API_KEY")
    if not OPENROUTER_API_KEY: missing_vars.append("OPENROUTER_API_KEY")
    
    raise ValueError(f"Переменные окружения не заданы: {', '.join(missing_vars)}. Проверьте ваш .env файл.")
