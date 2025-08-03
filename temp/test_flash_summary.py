import os
import sys
import asyncio
import google.generativeai as genai
import logging
import requests

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Добавляем корневую директорию проекта в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from src.config import GOOGLE_API_KEYS, OPENROUTER_API_KEY
except (ModuleNotFoundError, ImportError) as e:
    logging.error(f"Ошибка: Не удалось импортировать ключи из src.config.py: {e}")
    # Устанавливаем в None, чтобы скрипт мог продолжить работу и сообщить о проблеме
    GOOGLE_API_KEYS = []
    OPENROUTER_API_KEY = None

# Текст для тестирования
TEST_TEXT = """
Пентагон охвачен внутренними распрями из-за ошибок его главы Пита Хегсета, который, по мнению некоторых чиновников, возможно, не справляется со своими обязанностями по причине неопытности, сообщает газета Wall Street Journal со ссылкой на бывших и нынешних чиновников.

"Череда оплошностей министра обороны Пита Хегсета привела к внутренним распрям в Пентагоне и вызвала беспокойство среди некоторых республиканцев на Капитолийском холме относительно того, может ли он управлять министерством. Корень проблем заключается в отсутствии у Хегсета административного опыта в управлении такой масштабной организацией, как Пентагон", – пишет издание.

Газета сообщает, что в Белом доме были недовольны тем, что Хегсет отказался уволить главу своего аппарата, невзирая на сомнения чиновников в компетенции подчиненного. Кроме того, по мнению некоторых официальных лиц, в том, что президент США Дональд Трамп был не проинформирован о приостановке поставок вооружения Украине, виновна некачественная работа сотрудников Пентагона.

"Хегсет конфликтует с высшими офицерскими чинами и уволил троих высокопоставленных помощников, которые имели хорошую связь с Белым домом", - напоминает Wall Street Journal.

Газета также сообщает, что за время скандалов с утечками шеф Пентагона стал все меньше и меньше доверять военной верхушке ведомства, возлагая вину за утечки на нее.

В конце апреля издание Politico сообщало, что Пентагон охвачен конфликтом из-за борьбы окружения его главы Пита Хегсета за власть, в ведомстве царит "полный хаос". По данным собеседников Politico, конфликт в ведомстве носит исключительно личностный характер. Издание пишет, что из-за конфликта Хегсет стал подозревать своих старших подчиненных в утечках, связанных с мессенджером Signal, считая, что они таким образом могли намеренно подставить своих коллег-конкурентов.

Ранее газета New York Times со ссылкой на источники написала, что глава Пентагона в марте опубликовал данные о предстоящих ударах по Йемену в закрытый групповой чат в мессенджере Signal, участниками были не только люди из его профессионального окружения, но и его жена, а также брат и адвокат. Позже Белый дом заявил, что президент США Дональд Трамп "решительно поддерживает" американского министра обороны.

Главный редактор Atlantic Джеффри Голдберг 24 марта заявил, что 11 марта получил запрос в мессенджере Signal и попал в чат, где американские власти обсуждали удары по правящему на севере Йемена движению "Ансар Алла" (хуситам). По словам Голдберга, в группе под названием "Хуситы ПК тесная группа" проходила "увлекательная политическая дискуссия" с участием аккаунтов под именами вице-президента США Джей Ди Вэнса, министра обороны Штатов Пита Хегсета, советника Белого дома по национальной безопасности Майка Уолтца и других чиновников. Многие из них подтвердили, что состояли в чате, но настаивали на том, что не обменивались секретной информацией в мессенджере. Голдберг представил скриншоты переписки, на которых шеф Пентагона за несколько часов до начала операции сообщает о типах самолетов и целях, что, по мнению журналиста, в случае утечки могло бы угрожать военнослужащим.

Голдберг обвинил чиновников в серьезном нарушении правил безопасности. Также отмечалось, что в чате было настроено автоматическое удаление сообщений, что нарушает требования к хранению официальной информации.
"""

PROMPT = f"""Сделай краткое и содержательное резюме (примерно 150 слов) следующей новостной статьи на русском языке. Сохрани только ключевые факты и выводы. Не добавляй от себя никакой информации и не используй markdown-форматирование.

Текст статьи:
---
{TEST_TEXT}
---"""

async def test_key_with_flash_model(api_key: str, key_index: int):
    key_identifier = f"Ключ Google #{key_index + 1} (начинается с '{api_key[:4]}...')"
    model_name = 'gemini-1.5-flash-latest'
    print(f"--- Тестирование {key_identifier} с моделью {model_name} ---")
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        response = await model.generate_content_async(PROMPT)
        if response.text and response.text.strip():
            print(f"✅ {key_identifier}: Успешно сгенерировал резюме.")
            print("Результат:", response.text.strip())
            return True
        else:
            feedback = response.prompt_feedback if response.prompt_feedback else "Нет деталей"
            print(f"⚠️ {key_identifier}: Не вернул контент. Причина: {feedback}")
            return False
    except Exception as e:
        print(f"❌ {key_identifier}: Не работает. Ошибка: {type(e).__name__} - {e}")
        return False

def test_openrouter():
    print("--- Тестирование OpenRouter ---")
    if not OPENROUTER_API_KEY:
        print("❌ Ключ OPENROUTER_API_KEY не найден в конфигурации.")
        return False

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    data = {"model": "google/gemini-flash-1.5", "messages": [{"role": "user", "content": PROMPT}]}
    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data, timeout=30)
        response.raise_for_status()
        summary = response.json()["choices"][0]["message"]["content"]
        if summary and summary.strip():
            print("✅ OpenRouter: Успешно сгенерировал резюме.")
            print("Результат:", summary.strip())
            return True
        else:
            print("⚠️ OpenRouter: API вернул пустой ответ.")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ OpenRouter: Не работает. Ошибка: {type(e).__name__} - {e}")
        return False
    except (KeyError, IndexError):
        print("❌ OpenRouter: Не удалось разобрать ответ от API.")
        return False

async def main():
    if GOOGLE_API_KEYS:
        print(f"Начинаю тестирование суммирования для {len(GOOGLE_API_KEYS)} ключей Google...")
        for i, key in enumerate(GOOGLE_API_KEYS):
            await test_key_with_flash_model(key, i)
            print("-" * 20)
    else:
        logging.warning("Ключи Google API не найдены. Пропускаю их проверку.")

    print("\n" + "="*30 + "\n")
    
    test_openrouter()
    
    print("\n" + "="*30 + "\n")
    print("Тестирование завершено.")

if __name__ == "__main__":
    # Установка зависимости, если ее нет
    try:
        import requests
    except ImportError:
        print("Устанавливаю библиотеку requests...")
        os.system(f'{sys.executable} -m pip install requests')
        print("Установка завершена.")

    asyncio.run(main())