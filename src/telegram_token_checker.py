import asyncio
import telegram
import os
from dotenv import load_dotenv, find_dotenv
import google.generativeai as genai
import httpx

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

async def check_openrouter_api_key(key: str):
    """Проверяет ключ OpenRouter API, делая тестовый запрос."""
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "google/gemini-flash-1.5",
        "messages": [{"role": "user", "content": "test"}]
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data, timeout=10)
            if response.status_code == 200:
                print("✅ Ключ OPENROUTER_API_KEY: Действителен.")
            elif response.status_code == 401:
                print("❌ Ключ OPENROUTER_API_KEY: Недействителен (Unauthorized).")
            else:
                print(f"❌ Ключ OPENROUTER_API_KEY: Проблема с ключом. Статус: {response.status_code}, Ответ: {response.text}")
        except httpx.RequestError as e:
            print(f"❌ Ключ OPENROUTER_API_KEY: Ошибка запроса. {e}")

async def main():
    print("--- Проверка токена Telegram ---")
    await check_telegram_token()
    print("\n--- Проверка ключей API ---")

    # Список всех имен переменных для ключей Google
    google_key_names = [
        "GOOGLE_API_KEY", "GOOGLE_API_KEY_1", "GOOGLE_API_KEY_2",
        "GOOGLE_API_KEY_3", "GOOGLE_API_KEY_4", "GOOGLE_API_KEY_5",
        "GOOGLE_API_KEY_6", "GOOGLE_API_KEY_7"
    ]
    openrouter_key = os.getenv("OPENROUTER_API_KEY")

    tasks = []
    found_keys = False

    # Создаем задачи для проверки каждого найденного ключа Google
    for key_name in google_key_names:
        key = os.getenv(key_name)
        if key:
            found_keys = True
            tasks.append(check_google_api_key(key, key_name))

    # Задача для проверки ключа OpenRouter
    if openrouter_key:
        found_keys = True
        tasks.append(check_openrouter_api_key(openrouter_key))

    if not found_keys:
        print("Не найдены ключи API для проверки.")
        return

    # Асинхронно запускаем все задачи на проверку
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())