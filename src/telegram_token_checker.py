import asyncio
import telegram
import os
from dotenv import load_dotenv, find_dotenv
import google.generativeai as genai

# Загружаем переменные окружения из .env файла
load_dotenv(find_dotenv())

async def check_telegram_token():
    """Проверяет токен Telegram бота."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ Токен Telegram: Переменная окружения TELEGRAM_BOT_TOKEN не найдена.")
        return

    try:
        bot = telegram.Bot(token.strip())
        bot_info = await bot.get_me()
        print(f"✅ Токен Telegram: Действителен. Имя бота: {bot_info.username}")
    except telegram.error.Unauthorized:
        print("❌ Токен Telegram: Недействителен (Unauthorized).")
    except Exception as e:
        print(f"❌ Токен Telegram: Произошла ошибка: {e}")

async def check_google_api_key(key: str, key_name: str):
    """Проверяет ключ Google API, используя его имя для вывода."""
    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        # Небольшой тестовый вызов для проверки аутентификации
        await model.generate_content_async("test", generation_config=genai.types.GenerationConfig(max_output_tokens=1))
        print(f"✅ Ключ {key_name}: Действителен.")
    except Exception as e:
        print(f"❌ Ключ {key_name}: Недействителен или истек. Ошибка: {e}")

async def main():
    print("--- Проверка токена Telegram ---")
    await check_telegram_token()
    print("\n--- Проверка ключей Google API ---")

    # Список всех имен переменных для ключей Google
    google_key_names = [
        "GOOGLE_API_KEY", "GOOGLE_API_KEY_1", "GOOGLE_API_KEY_2",
        "GOOGLE_API_KEY_3", "GOOGLE_API_KEY_4", "GOOGLE_API_KEY_5",
        "GOOGLE_API_KEY_6", "GOOGLE_API_KEY_7", "GOOGLE_API_KEY_8"
    ]

    tasks = []
    found_keys = False

    # Создаем задачи для проверки каждого найденного ключа Google
    for key_name in google_key_names:
        key = os.getenv(key_name)
        if key:
            found_keys = True
            tasks.append(check_google_api_key(key, key_name))

    if not found_keys:
        print("Не найдено ни одного ключа Google API для проверки.")
        return

    # Асинхронно запускаем все задачи на проверку
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
