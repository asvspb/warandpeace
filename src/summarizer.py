import google.generativeai as genai
import os
import requests

# Пытаемся импортировать ключи из конфига
try:
    from src.config import GOOGLE_API_KEY, OPENROUTER_API_KEY
except (ModuleNotFoundError, ImportError):
    print("Переменные GOOGLE_API_KEY или OPENROUTER_API_KEY не найдены в src/config.py")
    # Пытаемся получить ключи из переменных окружения как запасной вариант
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# --- 1. Конфигурация Gemini ---
gemini_model = None
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        print("SDK Google Gemini успешно сконфигурирован.")
        # --- 2. Создание модели ---
        # Используем Gemini 1.5 Flash - быстрая и мощная модель
        gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        print(f"Модель '{gemini_model.model_name}' готова к работе.")
    except Exception as e:
        print(f"Ошибка при конфигурации Gemini или создании модели: {e}")
else:
    print("Ключ GOOGLE_API_KEY не найден. Суммаризация через Gemini не будет работать.")

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "google/gemini-flash-1.5"

def create_summarization_prompt(full_text: str) -> str:
    """
    Создает четкий промпт для задачи суммаризации.
    """
    return f"""Сделай краткое и содержательное резюме (примерно 150 слов) следующей новостной статьи на русском языке. Сохрани только ключевые факты и выводы. Не добавляй от себя никакой информации и не используй markdown-форматирование.

Текст статьи:
---
{full_text}
---"""

def summarize_text_local(full_text: str) -> str | None:
    """
    Суммирует текст, сначала пытаясь использовать Google Gemini API, затем OpenRouter.
    """
    cleaned_text = full_text.strip()
    if not cleaned_text:
        print("Ошибка: Передан пустой текст для суммирования.")
        return None

    prompt = create_summarization_prompt(cleaned_text)

    # Попытка суммирования через Gemini API
    if gemini_model:
        try:
            print("Отправка запроса к Gemini API...")
            response = gemini_model.generate_content(prompt)
            
            if response.text:
                print("Резюме успешно получено через Gemini.")
                return response.text.strip()
            else:
                print("Gemini API вернул пустой ответ. Возможно, сработали фильтры безопасности.")
                if response.prompt_feedback:
                    print(f"Причина блокировки: {response.prompt_feedback}")
        except Exception as e:
            print(f"Произошла ошибка во время запроса к Gemini API: {e}. Попытка использовать OpenRouter...")

    # Попытка суммирования через OpenRouter
    if OPENROUTER_API_KEY:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": OPENROUTER_MODEL,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        try:
            print("Отправка запроса к OpenRouter API...")
            response = requests.post(OPENROUTER_API_BASE, headers=headers, json=data)
            response.raise_for_status() # Вызовет исключение для ошибок HTTP
            
            openrouter_summary = response.json()["choices"][0]["message"]["content"]
            if openrouter_summary:
                print("Резюме успешно получено через OpenRouter.")
                return openrouter_summary.strip()
            else:
                print("OpenRouter API вернул пустой ответ.")
        except requests.exceptions.RequestException as e:
            print(f"Произошла ошибка во время запроса к OpenRouter API: {e}")
        except KeyError:
            print("Не удалось распарсить ответ от OpenRouter API.")
    else:
        print("Ключ OPENROUTER_API_KEY не найден. Суммаризация через OpenRouter не будет работать.")

    print("Не удалось получить резюме ни через один из API.")
    return None

# Блок для проверки работы функции
if __name__ == "__main__":
    test_text = """
    Министерство обороны России сообщило, что в ночь на 2 августа силы ПВО перехватили
    и уничтожили 15 беспилотных летательных аппаратов над территорией нескольких областей.
    По данным ведомства, атака была пресечена над Брянской, Курской и Белгородской областями.
    Губернаторы регионов подтвердили отсутствие пострадавших и разрушений на земле.
    Отмечается, что это уже третья подобная атака за последнюю неделю, что свидетельствует
    о возросшей активности на данном направлении. Эксперты анализируют тактику применения
    дронов и разрабатывают контрмеры для повышения эффективности систем ПВО.
    """

    print("\n" + "="*30 + "\n")
    print("--- Запрос на суммирование через Gemini API / OpenRouter ---")
    summary = summarize_text_local(test_text)

    print("\n" + "="*30 + "\n")
    print("--- Результат суммирования ---")
    if summary:
        print(summary)
    else:
        print("Не удалось получить резюме.")
