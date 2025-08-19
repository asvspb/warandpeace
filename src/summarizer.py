import google.generativeai as genai
import os
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryError

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Импорт ключей из обновленного конфига
from config import GOOGLE_API_KEYS, GEMINI_MODEL_NAME, MISTRAL_API_KEY, MISTRAL_MODEL_NAME

# Глобальный индекс для перебора ключей
current_gemini_key_index = 0

# --- 1. Конфигурация и работа с Gemini ---
def configure_gemini_model(api_key: str):
    """Конфигурирует модель Gemini с заданным ключом."""
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        logger.info(f"Модель '{model.model_name}' успешно сконфигурирована.")
        return model
    except Exception as e:
        logger.error(f"Ошибка при конфигурации Gemini или создании модели: {e}")
        return None

@retry(stop=stop_after_attempt(len(GOOGLE_API_KEYS) if GOOGLE_API_KEYS else 1),
       wait=wait_exponential(multiplier=1, min=4, max=10),
       retry=retry_if_exception_type((genai.types.BlockedPromptException, Exception)))
def _make_gemini_request(prompt: str) -> str | None:
    """
    Выполняет запрос к Gemini API с использованием циклического перебора ключей.
    Декоратор retry обрабатывает ошибки и переключает ключи.
    """
    global current_gemini_key_index
    if not GOOGLE_API_KEYS:
        logger.error("Список ключей Google API пуст. Запрос невозможен.")
        return None

    api_key = GOOGLE_API_KEYS[current_gemini_key_index]
    gemini_model = configure_gemini_model(api_key)

    if not gemini_model:
        # Если модель не создалась, переключаем ключ и вызываем ошибку для retry
        current_gemini_key_index = (current_gemini_key_index + 1) % len(GOOGLE_API_KEYS)
        raise Exception("Не удалось сконфигурировать модель Gemini, пробую следующий ключ.")

    try:
        logger.info(f"Отправка запроса к Gemini API с ключом #{current_gemini_key_index + 1}...")
        response = gemini_model.generate_content(prompt)
        
        if response.text:
            logger.info(f"Ответ успешно получен с ключом #{current_gemini_key_index + 1}.")
            return response.text.strip()
        else:
            logger.warning(f"Gemini API с ключом #{current_gemini_key_index + 1} вернул пустой ответ.")
            if response.prompt_feedback:
                logger.warning(f"Причина блокировки: {response.prompt_feedback}")
            # Вызываем ошибку, чтобы retry попробовал следующий ключ
            raise genai.types.BlockedPromptException("Пустой ответ или блокировка по безопасности.")

    except Exception as e:
        message_text = str(e)
        logger.error(f"Ошибка с ключом #{current_gemini_key_index + 1}: {message_text}")
        # Если регион недоступен для Gemini — нет смысла перебирать ключи
        if 'location is not supported' in message_text.lower():
            logger.warning("Регион не поддерживается для Gemini API. Переходим к запасному провайдеру без повторов.")
            return None
        # Переключаем ключ и перевыбрасываем исключение для retry
        current_gemini_key_index = (current_gemini_key_index + 1) % len(GOOGLE_API_KEYS)
        raise

# --- 2. Создание промптов ---
def _load_prompt_template(filename: str) -> str | None:
    """Пытается загрузить шаблон промпта из файла относительно корня репо.

    Ищет путь в переменной окружения PROMPTS_DIR (по умолчанию 'prompts').
    Возвращает содержимое файла или None при ошибке.
    """
    try:
        prompts_dir = os.getenv("PROMPTS_DIR", "prompts")
        # Ищем относительно текущего рабочего каталога, затем относительно файла
        candidate_paths = [
            os.path.join(os.getcwd(), prompts_dir, filename),
            os.path.join(os.path.dirname(__file__), os.pardir, prompts_dir, filename),
        ]
        for path in candidate_paths:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
    except Exception:
        return None
    return None


def create_summarization_prompt(full_text: str) -> str:
    """Создает промпт для суммаризации из внешнего шаблона, если он есть."""
    template = _load_prompt_template("summarization_ru.txt")
    if template:
        return template.replace("{{FULL_TEXT}}", full_text)
    # Фолбэк на встроённый шаблон
    return (
        "Сделай краткое и содержательное резюме (примерно 150 слов) следующей новостной статьи на русском языке. "
        "Сохрани только ключевые факты и выводы. Не добавляй от себя никакой информации и не используй markdown-форматирование.\n\n"
        "Текст статьи:\n---\n"
        f"{full_text}\n"
        "---"
    )

def _format_summaries_bullets(summaries: list[str]) -> str:
    return "\n".join(f"- {s}" for s in summaries)


def create_digest_prompt(summaries: list[str], period_name: str) -> str:
    """Создаёт промпт для дайджеста, подхватывая внешний шаблон по периоду.

    Порядок поиска файла:
    - Для периодов, содержащих ключевые слова, ищем специальные шаблоны:
      daily → digest_daily_ru.txt; week/недел → digest_weekly_ru.txt; month/месяц → digest_monthly_ru.txt
    - Иначе используем общий встроенный шаблон.
    """
    lower = period_name.lower()
    filename = None
    if any(k in lower for k in ["вчера", "day", "daily"]):
        filename = "digest_daily_ru.txt"
    elif any(k in lower for k in ["недел", "week", "weekly"]):
        filename = "digest_weekly_ru.txt"
    elif any(k in lower for k in ["месяц", "month", "monthly"]):
        filename = "digest_monthly_ru.txt"

    template = _load_prompt_template(filename) if filename else None
    bullets = _format_summaries_bullets(summaries)
    if template:
        return (
            template
            .replace("{PERIOD_NAME}", period_name)
            .replace("{SUMMARIES_BULLETS}", bullets)
        )

    # Фолбэк на встроённый общий шаблон
    return (
        f"Ты — профессиональный новостной аналитик. Ниже представлен список кратких сводок новостей за последние {period_name}.\n"
        "Твоя задача — написать целостную аналитическую сводку на русском языке (200–250 слов).\n\n"
        "Требования:\n"
        "1. Не перечисляй просто факты из сводок.\n"
        "2. Определи 2–4 ключевых тренда или тематических блока.\n"
        "3. Напиши связный текст без markdown и списков.\n\n"
        "Список сводок:\n"
        f"{bullets}\n"
    )

def create_annual_digest_prompt(digest_contents: list[str]) -> str:
    """
    Создает промпт для генерации годового "мега-дайджеста".
    """
    digests_text = "\n\n---\n\n".join(digest_contents)
    return f"""Ты — главный редактор и ведущий аналитик. Перед тобой подборка еженедельных и ежемесячных аналитических дайджестов за прошедший год.
Твоя задача — написать итоговую годовую аналитическую статью (400-500 слов).

Требования:
1.  Выяви и опиши главные, долгосрочные тенденции и события года.
2.  Проанализируй, как развивались ключевые сюжеты в течение года.
3.  Сделай выводы о последствиях этих событий.
4.  Текст должен быть написан в авторитетном, аналитическом стиле.
5.  Придумай яркий и емкий заголовок для годового отчета.

Материалы для анализа (дайджесты за год):
{digests_text}
"""

# --- 3. Публичные функции ---
def summarize_text_local(full_text: str) -> str | None:
    """
    Суммирует текст, используя Gemini API с перебором ключей.
    """
    cleaned_text = full_text.strip()
    if not cleaned_text:
        logger.error("Ошибка: Передан пустой текст для суммирования.")
        return None

    prompt = create_summarization_prompt(cleaned_text)
    try:
        return _make_gemini_request(prompt)
    except RetryError as e:
        logger.error(f"Не удалось получить резюме после исчерпания всех ключей: {e}")
        return None

def create_digest(summaries: list[str], period_name: str) -> str | None:
    """
    Создает аналитический дайджест на основе списка сводок.
    """
    if not summaries:
        logger.warning("Передан пустой список сводок для создания дайджеста.")
        return None
    
    prompt = create_digest_prompt(summaries, period_name)
    try:
        return _make_gemini_request(prompt)
    except RetryError as e:
        logger.error(f"Не удалось создать дайджест после исчерпания всех ключей: {e}")
        return None

def create_annual_digest(digest_contents: list[str]) -> str | None:
    """
    Создает годовой "мега-дайджест" на основе других дайджестов.
    """
    if not digest_contents:
        logger.warning("Передан пустой список дайджестов для создания годового отчета.")
        return None

    prompt = create_annual_digest_prompt(digest_contents)
    try:
        return _make_gemini_request(prompt)
    except RetryError as e:
        logger.error(f"Не удалось создать годовой дайджест: {e}")
        return None

def summarize_with_mistral(text_to_summarize: str) -> str | None:
    """
    Суммирует предоставленный текст с помощью модели Mistral.
    """
    from mistralai.client import MistralClient

    if not MISTRAL_API_KEY:
        logger.error("API-ключ для Mistral не найден.")
        return None

    try:
        client = MistralClient(api_key=MISTRAL_API_KEY)

        prompt = create_summarization_prompt(text_to_summarize)
        # Используем универсальный формат сообщений без зависимости от моделей SDK
        messages = [{"role": "user", "content": prompt}]

        chat_response = client.chat(
            model=MISTRAL_MODEL_NAME,
            messages=messages,
        )

        summary = chat_response.choices[0].message.content
        logger.info("Резюме успешно получено от Mistral.")
        return summary.strip()

    except Exception as e:
        logger.error(f"Ошибка при получении резюме от Mistral: {e}")
        return None

# --- Блок для проверки ---
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