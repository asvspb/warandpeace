import google.generativeai as genai
import os

# Пытаемся импортировать ключ из конфига
try:
    from src.config import AI_API_KEY
except (ModuleNotFoundError, ImportError):
    print("Переменная AI_API_KEY не найдена в src/config.py")
    # Пытаемся получить ключ из переменных окружения как запасной вариант
    AI_API_KEY = os.getenv("AI_API_KEY")

# --- 1. Конфигурация Gemini ---
if AI_API_KEY:
    try:
        genai.configure(api_key=AI_API_KEY)
        print("SDK Google Gemini успешно сконфигурирован.")
        # --- 2. Создание модели ---
        # Используем Gemini 1.5 Flash - быстрая и мощная модель
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        print(f"Модель '{model.model_name}' готова к работе.")
    except Exception as e:
        print(f"Ошибка при конфигурации Gemini или создании модели: {e}")
        model = None
else:
    print("Ключ AI_API_KEY не найден. Суммаризация через Gemini не будет работать.")
    model = None

def create_summarization_prompt(full_text: str) -> str:
    """
    Создает четкий промпт для задачи суммаризации.
    """
    # Используем тройные кавычки для корректного многострочного f-string
    return f"""Сделай краткое и содержательное резюме (не более 100 слов) следующей новостной статьи на русском языке. Сохрани только ключевые факты и выводы. Не добавляй от себя никакой информации и не используй markdown-форматирование.

Текст статьи:
---
{full_text}
---"""

def summarize_text_local(full_text: str) -> str | None:
    """
    Суммирует текст с помощью Google Gemini API.
    (Имя функции сохранено для совместимости с парсером).
    """
    if not model:
        print("Ошибка: Модель Gemini не была инициализирована.")
        return None

    cleaned_text = full_text.strip()
    if not cleaned_text:
        print("Ошибка: Передан пустой текст для суммирования.")
        return None

    prompt = create_summarization_prompt(cleaned_text)

    try:
        print("Отправка запроса к Gemini API...")
        response = model.generate_content(prompt)
        
        if response.text:
            print("Резюме успешно получено.")
            return response.text.strip()
        else:
            # Обработка случая, когда ответ пустой или заблокирован
            print("API вернул пустой ответ. Возможно, сработали фильтры безопасности.")
            if response.prompt_feedback:
                print(f"Причина блокировки: {response.prompt_feedback}")
            return None

    except Exception as e:
        print(f"Произошла ошибка во время запроса к Gemini API: {e}")
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
    print("--- Запрос на суммирование через Gemini API ---")
    summary = summarize_text_local(test_text)

    print("\n" + "="*30 + "\n")
    print("--- Результат суммирования ---")
    if summary:
        print(summary)
    else:
        print("Не удалось получить резюме.")
