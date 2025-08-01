import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
AI_API_KEY = os.getenv("AI_API_KEY")

# Проверяем, что все переменные были загружены
if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, AI_API_KEY]):
    raise ValueError("Одна или несколько переменных окружения не заданы! Проверьте ваш .env файл.")