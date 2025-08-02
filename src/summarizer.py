import asyncio
import requests
from config import HUGGINGFACE_API_KEY

# Адрес API и модель для суммаризации
API_URL = "https://api-inference.huggingface.co/models/csebuetnlp/mT5_multilingual_XLSum"
HEADERS = {"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"}

async def summarize_text_async(full_text: str) -> str | None:
    """
    Асинхронно суммирует переданный текст с помощью Hugging Face Inference API.

    Args:
        full_text: Текст новостной статьи для суммирования.

    Returns:
        Суммаризированный текст или None в случае ошибки.
    """
    cleaned_text = full_text.strip()
    if not cleaned_text:
        print("Ошибка: Передан пустой текст для суммирования.")
        return None

    payload = {
        "inputs": cleaned_text,
        "parameters": {
            "min_length": 30, 
            "max_length": 150,
            "do_sample": False
        }
    }

    loop = asyncio.get_event_loop()
    try:
        response = await loop.run_in_executor(
            None, 
            lambda: requests.post(API_URL, headers=HEADERS, json=payload, timeout=60)
        )
        response.raise_for_status()  # Проверка на HTTP ошибки (4xx, 5xx)
        
        result = response.json()
        if isinstance(result, list) and result and 'summary_text' in result[0]:
            return result[0]['summary_text']
        else:
            print(f"Ошибка: API вернуло неожиданный ответ: {result}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Произошла ошибка при обращении к API Hugging Face: {e}")
        return None
    except Exception as e:
        print(f"Произошла непредвиденная ошибка: {e}")
        return None

# Блок для проверки работы функции
if __name__ == "__main__":
    async def main():
        test_text = """
        Министерство обороны России сообщило, что в ночь на 2 августа силы ПВО перехватили 
        и уничтожили 15 беспилотных летательных аппаратов над территорией нескольких областей. 
        По данным ведомства, атака была пресечена над Брянской, Курской и Белгородской областями. 
        Губернаторы регионов подтвердили отсутствие пострадавших и разрушений на земле. 
        Отмечается, что это уже третья подобная атака за последнюю неделю, что свидетельствует 
        о возросшей активности на данном направлении. Эксперты анализируют тактику применения 
        дронов и разрабатывают контрмеры для повышения эффективности систем ПВО.
        """
        
        print("--- Исходный текст ---")
        print(test_text)
        print("\n" + "="*30 + "\n")
        
        print("--- Запрос на суммирование ---")
        summary = await summarize_text_async(test_text)
        
        print("\n" + "="*30 + "\n")
        print("--- Результат суммирования ---")
        if summary:
            print(summary)
        else:
            print("Не удалось получить резюме.")

    asyncio.run(main())
