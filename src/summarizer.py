import google.generativeai as genai
import os
import requests
import logging
from tenacity import retry, stop_after_attempt, wait_exponential,     retry_if_exception_type, RetryError

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Пытаемся импортировать ключи из конфига
try:
    from src.config import GOOGLE_API_KEYS, OPENROUTER_API_KEY
except (ModuleNotFoundError, ImportError):
    print("Переменные GOOGLE_API_KEYS или OPENROUTER_API_KEY не найдены в src/config.py")
    # Пытаемся получить ключи из переменных окружения как запасной вариант
    # В данном случае, если конфиг не найден, то и ключи Gemini не будут доступны
    GOOGLE_API_KEYS = []
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# --- 1. Конфигурация Gemini ---
def configure_gemini_model(api_key: str):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        logger.info(f"Модель '{model.model_name}' успешно сконфигурирована с ключом.")
        return model
    except Exception as e:
        logger.error(f"Ошибка при конфигурации Gemini или создании модели с ключом: {e}")
        return None

current_gemini_key_index = 0

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

@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=4, max=10),
       retry=retry_if_exception_type((requests.exceptions.RequestException, genai.types.BlockedPromptException)))
def summarize_text_local(full_text: str) -> str | None:
    """
    Суммирует текст, сначала пытаясь использовать Google Gemini API, затем OpenRouter.
    """
    cleaned_text = full_text.strip()
    if not cleaned_text:
        logger.error("Ошибка: Передан пустой текст для суммирования.")
        return None

    prompt = create_summarization_prompt(cleaned_text)

    global current_gemini_key_index
    gemini_summary = None

    try:
        # Попытка суммирования через Gemini API с перебором ключей
        if GOOGLE_API_KEYS:
            for _ in range(len(GOOGLE_API_KEYS)):
                api_key = GOOGLE_API_KEYS[current_gemini_key_index]
                gemini_model = configure_gemini_model(api_key)

                if gemini_model:
                    try:
                        logger.info(f"Отправка запроса к Gemini API с ключом {current_gemini_key_index + 1}...")
                        response = gemini_model.generate_content(prompt)
                        
                        if response.text:
                            logger.info(f"Резюме успешно получено через Gemini с ключом {current_gemini_key_index + 1}.")
                            gemini_summary = response.text.strip()
                            break # Успех, выходим из цикла
                        else:
                            logger.warning(f"Gemini API с ключом {current_gemini_key_index + 1} вернул пустой ответ. Возможно, сработали фильтры безопасности.")
                            if response.prompt_feedback:
                                logger.warning(f"Причина блокировки: {response.prompt_feedback}")
                            # Продолжаем к следующему ключу
                    except genai.types.BlockedPromptException as e:
                        logger.error(f"Gemini API с ключом {current_gemini_key_index + 1} заблокировал промпт: {e}. Попытка использовать следующий ключ...")
                        # Продолжаем к следующему ключу
                    except Exception as e:
                        logger.error(f"Произошла ошибка во время запроса к Gemini API с ключом {current_gemini_key_index + 1}: {e}. Попытка использовать следующий ключ...")
                        # Продолжаем к следующему ключу
                
                # Переходим к следующему ключу (циклически)
                current_gemini_key_index = (current_gemini_key_index + 1) % len(GOOGLE_API_KEYS)

        if gemini_summary:
            return gemini_summary

        # Если Gemini не дал результат, пытаемся суммировать через OpenRouter
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
                logger.info("Отправка запроса к OpenRouter API...")
                response = requests.post(OPENROUTER_API_BASE, headers=headers, json=data)
                response.raise_for_status() # Вызовет исключение для ошибок HTTP
                
                openrouter_summary = response.json()["choices"][0]["message"]["content"]
                if openrouter_summary:
                    logger.info("Резюме успешно получено через OpenRouter.")
                    return openrouter_summary.strip()
                else:
                    logger.warning("OpenRouter API вернул пустой ответ.")
                    raise requests.exceptions.RequestException("OpenRouter API вернул пустой ответ.")
            except requests.exceptions.RequestException as e:
                logger.error(f"Произошла ошибка во время запроса к OpenRouter API: {e}")
                raise # Перевыбрасываем для tenacity
            except KeyError:
                logger.error("Не удалось распарсить ответ от OpenRouter API.")
                raise requests.exceptions.RequestException("Не удалось распарсить ответ от OpenRouter API.")
        else:
            logger.warning("Ключ OPENROUTER_API_KEY не найден. Суммаризация через OpenRouter не будет работать.")

        logger.error("Не удалось получить резюме ни через один из API.")
        return None
    except RetryError as e:
        logger.error(f"Все попытки суммирования завершились неудачей: {e}")
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
