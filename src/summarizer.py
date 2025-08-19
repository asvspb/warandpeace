import google.generativeai as genai
import os
import logging
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
from config import (
    GOOGLE_API_KEYS,
    GEMINI_MODEL_NAME,
    MISTRAL_API_KEY,
    MISTRAL_MODEL_NAME,
    LLM_PRIMARY,
    GEMINI_ENABLED,
    MISTRAL_ENABLED,
)

# --- Gemini helpers ---
current_gemini_key_index = 0

def configure_gemini_model(api_key: str):
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
    global current_gemini_key_index
    if not GOOGLE_API_KEYS:
        logger.error("Список ключей Google API пуст. Запрос невозможен.")
        return None

    api_key = GOOGLE_API_KEYS[current_gemini_key_index]
    gemini_model = configure_gemini_model(api_key)

    if not gemini_model:
        current_gemini_key_index = (current_gemini_key_index + 1) % len(GOOGLE_API_KEYS)
        raise Exception("Не удалось сконфигурировать модель Gemini, пробую следующий ключ.")

    try:
        logger.info(f"Отправка запроса к Gemini API с ключом #{current_gemini_key_index + 1}...")
        response = gemini_model.generate_content(prompt)
        if response.text:
            logger.info("Ответ успешно получен от Gemini.")
            return response.text.strip()
        else:
            logger.warning("Gemini вернул пустой ответ.")
            if getattr(response, 'prompt_feedback', None):
                logger.warning(f"Причина блокировки: {response.prompt_feedback}")
            raise genai.types.BlockedPromptException("Пустой ответ или блокировка по безопасности.")
    except Exception as e:
        message_text = str(e)
        logger.error(f"Ошибка с ключом #{current_gemini_key_index + 1}: {message_text}")
        if 'location is not supported' in message_text.lower():
            logger.warning("Регион не поддерживается для Gemini API.")
            return None
        current_gemini_key_index = (current_gemini_key_index + 1) % len(GOOGLE_API_KEYS)
        raise

# --- Prompt loading ---
def _load_prompt_template(filename: str) -> str | None:
    try:
        prompts_dir = os.getenv("PROMPTS_DIR", "prompts")
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
    template = _load_prompt_template("summarization_ru.txt")
    if template:
        return template.replace("{{FULL_TEXT}}", full_text)
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
        return template.replace("{PERIOD_NAME}", period_name).replace("{SUMMARIES_BULLETS}", bullets)
    return (
        f"Ты — профессиональный новостной аналитик. Ниже представлен список кратких сводок новостей за последние {period_name}.\n"
        "Твоя задача — написать целостную аналитическую сводку на русском языке (200–250 слов).\n\n"
        "Требования:\n1. Не перечисляй просто факты из сводок.\n2. Определи 2–4 ключевых тренда или тематических блока.\n3. Напиши связный текст без markdown и списков.\n\n"
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

# --- Public API ---
def summarize_text_local(full_text: str) -> str | None:
    cleaned_text = full_text.strip()
    if not cleaned_text:
        logger.error("Ошибка: Передан пустой текст для суммирования.")
        return None
    prompt = create_summarization_prompt(cleaned_text)

    # Read runtime switches from environment with config defaults
    truthy = {"1", "true", "yes", "on"}
    gemini_enabled = os.getenv("GEMINI_ENABLED", "true" if GEMINI_ENABLED else "false").strip().lower() in truthy
    mistral_enabled = os.getenv("MISTRAL_ENABLED", "true" if MISTRAL_ENABLED else "false").strip().lower() in truthy
    llm_primary = os.getenv("LLM_PRIMARY", (LLM_PRIMARY or "gemini")).strip().lower()

    # If primary is mistral, honor it strictly: no fallback to Gemini unless Mistral is disabled
    if llm_primary == "mistral":
        if mistral_enabled and MISTRAL_API_KEY:
            return summarize_with_mistral(cleaned_text)
        # If Mistral is not available, allow Gemini as a backup
        if not mistral_enabled or not MISTRAL_API_KEY:
            if gemini_enabled and GOOGLE_API_KEYS:
                try:
                    return _make_gemini_request(prompt)
                except RetryError as e:
                    logger.error(f"Не удалось получить резюме от Gemini: {e}")
        return None

    if gemini_enabled and GOOGLE_API_KEYS:
        try:
            result = _make_gemini_request(prompt)
            if result:
                return result
        except RetryError as e:
            logger.error(f"Не удалось получить резюме от Gemini: {e}")

    if mistral_enabled and MISTRAL_API_KEY:
        return summarize_with_mistral(cleaned_text)
    return None

def create_digest(summaries: list[str], period_name: str) -> str | None:
    if not summaries:
        logger.warning("Передан пустой список сводок для создания дайджеста.")
        return None
    
    prompt = create_digest_prompt(summaries, period_name)
    try:
        return _make_gemini_request(prompt)
    except RetryError as e:
        logger.error(f"Не удалось создать дайджест: {e}")
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

def summarize_with_mistral(text_to_summarize: str) -> Optional[str]:
    try:
        from mistralai.client import MistralClient
    except Exception:
        logger.error("SDK Mistral недоступен.")
        return None
    if not MISTRAL_API_KEY:
        logger.error("API-ключ для Mistral не найден.")
        return None
    try:
        client = MistralClient(api_key=MISTRAL_API_KEY)
        prompt = create_summarization_prompt(text_to_summarize)
        messages = [{"role": "user", "content": prompt}]
        chat_response = client.chat(model=MISTRAL_MODEL_NAME, messages=messages)
        summary = chat_response.choices[0].message.content
        logger.info("Резюме успешно получено от Mistral.")
        return summary.strip()
    except Exception as e:
        logger.error(f"Ошибка при получении резюме от Mistrал: {e}")
        return None

def summarize_with_fallback(text: str) -> Optional[str]:
    """Публичная обертка, ожидаемая CLI и тестами.

    Делегирует на summarize_text_local, которая учитывает LLM_PRIMARY,
    GEMINI_ENABLED и MISTRAL_ENABLED и выполняет фолбэк.
    """
    return summarize_text_local(text)
