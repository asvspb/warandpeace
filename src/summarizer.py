import google.generativeai as genai
import os
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryError

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Импорт ключей из обновленного конфига
from config import (
    GOOGLE_API_KEYS,
    GEMINI_MODEL_NAME,
    MISTRAL_API_KEY,
    MISTRAL_MODEL_NAME,
    LLM_PRIMARY,
    GEMINI_ENABLED,
    MISTRAL_ENABLED,
    # Service prompts
    SERVICE_PROMPTS_ENABLED,
)

# --- Metrics (optional) ---
try:
    from metrics import (
        TOKENS_CONSUMED_PROMPT_TOTAL,
        TOKENS_CONSUMED_COMPLETION_TOTAL,
        TOKENS_CONSUMED_PROMPT_BY_KEY_TOTAL,
        TOKENS_CONSUMED_COMPLETION_BY_KEY_TOTAL,
        LLM_REQUESTS_BY_KEY_TOTAL,
        EXTERNAL_HTTP_REQUESTS_TOTAL,
        EXTERNAL_HTTP_REQUEST_DURATION_SECONDS,
    )
except Exception:  # pragma: no cover
    class _NoopMetric:
        def labels(self, *args, **kwargs):
            return self
        def inc(self, *args, **kwargs):
            return None
        def observe(self, *args, **kwargs):
            return None
    TOKENS_CONSUMED_PROMPT_TOTAL = _NoopMetric()
    TOKENS_CONSUMED_COMPLETION_TOTAL = _NoopMetric()
    TOKENS_CONSUMED_PROMPT_BY_KEY_TOTAL = _NoopMetric()
    TOKENS_CONSUMED_COMPLETION_BY_KEY_TOTAL = _NoopMetric()
    LLM_REQUESTS_BY_KEY_TOTAL = _NoopMetric()
    EXTERNAL_HTTP_REQUESTS_TOTAL = _NoopMetric()
    EXTERNAL_HTTP_REQUEST_DURATION_SECONDS = _NoopMetric()
# --- API usage persistence (optional) ---
try:
    from api_usage import record_api_event, estimate_event_cost_usd, hash_api_key_to_id
except Exception:  # pragma: no cover
    def record_api_event(_e):
        return None
    def estimate_event_cost_usd(_p, _m, _ti, _to):
        return 0.0
    def hash_api_key_to_id(_s):
        return None

# --- Optional SSE broadcast for web UI updates ---
try:  # pragma: no cover
    from src.webapp.server import _sse_broadcast  # type: ignore
except Exception:  # pragma: no cover
    def _sse_broadcast(_obj):  # type: ignore
        return None

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


# --- 2. Модифицированный код суммаризации для фоновой обработки ---
def summarize_text_background(full_text: str, article_id: int = None) -> str | None:
    """
    Суммирует текст в фоновом режиме, используя ту же логику, что и summarize_text_local,
    но с дополнительной оберткой для фоновой обработки.
    
    Args:
        full_text: Текст для суммаризации
        article_id: ID статьи (опционально, для логирования)
    
    Returns:
        str | None: Результат суммаризации или None в случае ошибки
    """
    if article_id:
        logger.info(f"Начинаю фоновую суммаризацию для статьи {article_id}")
    
    cleaned_text = full_text.strip()
    if not cleaned_text:
        logger.error(f"Ошибка: Передан пустой текст для суммирования. Article ID: {article_id}")
        return None

    prompt = create_summarization_prompt(cleaned_text)
    
    # 1) Явный приоритет Mistral
    if LLM_PRIMARY == "mistral" and MISTRAL_ENABLED and MISTRAL_API_KEY:
        result = summarize_with_mistral(cleaned_text)
        if result:
            if article_id:
                logger.info(f"Суммаризация для статьи {article_id} завершена с помощью Mistral")
            return result
        # Если не удалось, пробуем Gemini
        if GEMINI_ENABLED and GOOGLE_API_KEYS:
            try:
                result = _make_gemini_request(prompt)
                if result:
                    if article_id:
                        logger.info(f"Суммаризация для статьи {article_id} завершена с помощью Gemini")
                    return result
            except RetryError as e:
                logger.error(f"Не удалось получить резюме от Gemini для статьи {article_id}: {e}")
                return None
        return None

    # 2) По умолчанию — Gemini с фолбэком на Mistral
    if GEMINI_ENABLED and GOOGLE_API_KEYS:
        try:
            result = _make_gemini_request(prompt)
            if result:
                if article_id:
                    logger.info(f"Суммаризация для статьи {article_id} завершена с помощью Gemini")
                return result
        except RetryError as e:
            logger.error(f"Не удалось получить резюме от Gemini для статьи {article_id}: {e}")
    if MISTRAL_ENABLED and MISTRAL_API_KEY:
        result = summarize_with_mistral(cleaned_text)
        if article_id and result:
            logger.info(f"Суммаризация для статьи {article_id} завершена с помощью Mistral (фолбэк)")
        return result
    
    logger.error(f"Ни один из провайдеров LLM не доступен для суммаризации статьи {article_id}")
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
        import time as _t
        logger.info(f"Отправка запроса к Gemini API с ключом #{current_gemini_key_index + 1}...")
        _start = _t.time()
        response = gemini_model.generate_content(prompt)
        
        if response.text:
            logger.info(f"Ответ успешно получен с ключом #{current_gemini_key_index + 1}.")
            # Metrics: duration + request count
            try:
                _dur = max(0.0, _t.time() - _start)
                EXTERNAL_HTTP_REQUEST_DURATION_SECONDS.labels("llm").observe(_dur)
                EXTERNAL_HTTP_REQUESTS_TOTAL.labels("llm", "POST", "2xx").inc()
            except Exception:
                pass
            # Token usage if available
            try:
                usage = getattr(response, "usage_metadata", None)
                if usage:
                    prompt_tokens = getattr(usage, "prompt_token_count", None) or getattr(usage, "input_token_count", None)
                    completion_tokens = getattr(usage, "candidates_token_count", None) or getattr(usage, "output_token_count", None)
                    if isinstance(prompt_tokens, int) and prompt_tokens > 0:
                        TOKENS_CONSUMED_PROMPT_TOTAL.labels("google", GEMINI_MODEL_NAME).inc(prompt_tokens)
                        # per-key breakdown by index (gemini1..N)
                        key_id = f"gemini{current_gemini_key_index + 1}"
                        TOKENS_CONSUMED_PROMPT_BY_KEY_TOTAL.labels("google", key_id).inc(prompt_tokens)
                    if isinstance(completion_tokens, int) and completion_tokens > 0:
                        TOKENS_CONSUMED_COMPLETION_TOTAL.labels("google", GEMINI_MODEL_NAME).inc(completion_tokens)
                        key_id = f"gemini{current_gemini_key_index + 1}"
                        TOKENS_CONSUMED_COMPLETION_BY_KEY_TOTAL.labels("google", key_id).inc(completion_tokens)
                    # Ensure per-key series exist even if one of the parts is zero
                    try:
                        key_id = f"gemini{current_gemini_key_index + 1}"
                        if not (isinstance(prompt_tokens, int) and prompt_tokens > 0):
                            TOKENS_CONSUMED_PROMPT_BY_KEY_TOTAL.labels("google", key_id).inc(0)
                        if not (isinstance(completion_tokens, int) and completion_tokens > 0):
                            TOKENS_CONSUMED_COMPLETION_BY_KEY_TOTAL.labels("google", key_id).inc(0)
                    except Exception:
                        pass
                else:
                    # Usage not provided by provider; register per-key with zero so UI shows the key
                    try:
                        key_id = f"gemini{current_gemini_key_index + 1}"
                        TOKENS_CONSUMED_PROMPT_BY_KEY_TOTAL.labels("google", key_id).inc(0)
                        TOKENS_CONSUMED_COMPLETION_BY_KEY_TOTAL.labels("google", key_id).inc(0)
                    except Exception:
                        pass
                    # Count request per key
                    try:
                        key_id = f"gemini{current_gemini_key_index + 1}"
                        LLM_REQUESTS_BY_KEY_TOTAL.labels("google", key_id).inc()
                    except Exception:
                        pass
            except Exception:
                pass
            # Persisted API usage event (success)
            try:
                _dur_ms = int(max(0.0, _t.time() - _start) * 1000.0)
                usage = getattr(response, "usage_metadata", None)
                pt = None
                ct = None
                if usage:
                    pt = getattr(usage, "prompt_token_count", None) or getattr(usage, "input_token_count", None)
                    ct = getattr(usage, "candidates_token_count", None) or getattr(usage, "output_token_count", None)
                tokens_in = int(pt or 0)
                tokens_out = int(ct or 0)
                cost_usd = estimate_event_cost_usd("gemini", GEMINI_MODEL_NAME, tokens_in, tokens_out)
                api_key_hash = hash_api_key_to_id(api_key)
                record_api_event({
                    "ts_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                    "provider": "gemini",
                    "model": GEMINI_MODEL_NAME,
                    "api_key_hash": api_key_hash,
                    "endpoint": "generate_content",
                    "req_count": 1,
                    "success": True,
                    "http_status": None,
                    "latency_ms": _dur_ms,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "cost_usd": float(cost_usd),
                    "error_code": None,
                    "extra_json": None,
                })
            except Exception:
                pass
            # Always count a successful Gemini request per key
            try:
                key_id = f"gemini{current_gemini_key_index + 1}"
                LLM_REQUESTS_BY_KEY_TOTAL.labels("google", key_id).inc()
            except Exception:
                pass
            # Notify web UI that metrics likely changed
            try:
                _sse_broadcast({"type": "metrics_updated"})
            except Exception:
                pass
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
        try:
            EXTERNAL_HTTP_REQUESTS_TOTAL.labels("llm", "POST", "5xx").inc()
        except Exception:
            pass
        # Persist failed event
        try:
            import time as _t2
            _dur_ms = int(max(0.0, (_t2.time() - _start) if ' _start' in locals() else 0.0) * 1000.0)
            api_key_hash = hash_api_key_to_id(api_key)
            record_api_event({
                "ts_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                "provider": "gemini",
                "model": GEMINI_MODEL_NAME,
                "api_key_hash": api_key_hash,
                "endpoint": "generate_content",
                "req_count": 1,
                "success": False,
                "http_status": None,
                "latency_ms": _dur_ms,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
                "error_code": type(e).__name__,
                "extra_json": None,
            })
        except Exception:
            pass
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


def _load_service_template(path_in_prompts: str) -> str | None:
    """Загружает шаблон из подпапки service (относительно PROMPTS_DIR)."""
    return _load_prompt_template(path_in_prompts)


def create_service_summarization_prompt(article_json: str) -> str:
    """Создаёт служебный промпт (строгий JSON) для суммаризации одной статьи (фиксированный v1)."""
    filename = "service/summarization_service_v1_ru.txt"
    template = _load_service_template(filename)
    if template:
        return template.replace("{{ARTICLE_JSON}}", article_json)
    # Фолбэк: минимальный жёсткий JSON-промпт
    return (
        "Вы — аналитик WP Pulse. Верните ТОЛЬКО валидный JSON по схеме из служебного мануала.\n\n"
        "Вход:\n" + article_json
    )


def create_service_digest_prompt(
    articles_jsonl: str,
    period_name: str,
    previous_summary_json: str | None = None,
) -> str:
    """Создаёт служебный промпт для дайджеста (суточный/недельный/месячный).

    period_name: строка, содержащая daily/weekly/monthly или русские аналоги.
    previous_summary_json: JSON предыдущего окна (для дельт), если применимо.
    """
    lower = period_name.lower()
    is_daily = any(k in lower for k in ["вчера", "сут", "day", "daily"])
    is_weekly = any(k in lower for k in ["недел", "week", "weekly"])
    is_monthly = any(k in lower for k in ["месяц", "month", "monthly"])

    if not (is_daily or is_weekly or is_monthly):
        # по умолчанию — daily
        is_daily = True

    if is_daily:
        filename = "service/digest_daily_service_v1_ru.txt"
    elif is_weekly:
        filename = "service/digest_weekly_service_v1_ru.txt"
    else:
        filename = "service/digest_monthly_service_v1_ru.txt"

    template = _load_service_template(filename)

    # Подстановка плейсхолдеров
    if template:
        prompt = template.replace("{{ARTICLES_JSONL}}", articles_jsonl)
        if previous_summary_json is not None:
            prompt = prompt.replace("{{Y_SUMMARY_JSON_OR_NULL}}", previous_summary_json)
            prompt = prompt.replace("{{LW_SUMMARY_JSON_OR_NULL}}", previous_summary_json)
            prompt = prompt.replace("{{LM_SUMMARY_JSON_OR_NULL}}", previous_summary_json)
        else:
            prompt = prompt.replace("{{Y_SUMMARY_JSON_OR_NULL}}", "null")
            prompt = prompt.replace("{{LW_SUMMARY_JSON_OR_NULL}}", "null")
            prompt = prompt.replace("{{LM_SUMMARY_JSON_OR_NULL}}", "null")
        return prompt

    # Фолбэк: минимальный JSON-ориентированный промпт
    return (
        "Сформируйте служебный JSON-дайджест WP Pulse. Верните ТОЛЬКО JSON.\n\n"
        f"Период: {period_name}\n"
        "Входные статьи (JSON Lines):\n" + articles_jsonl + "\n"
        "Предыдущий сводный JSON:\n" + (previous_summary_json or "null")
    )


# --- 2b. Публичные генераторы служебного вывода ---
def generate_service_summary(article_json: str) -> str | None:
    """Генерирует служебный JSON-резюме одной статьи, с приоритетом провайдера по LLM_PRIMARY."""
    prompt = create_service_summarization_prompt(article_json)
    try:
        if LLM_PRIMARY == "mistral" and MISTRAL_ENABLED and MISTRAL_API_KEY:
            # Непосредственный вызов Mistral на сыром промпте
            out = _mistral_generate_raw_prompt(prompt)
            try:
                LLM_REQUESTS_BY_KEY_TOTAL.labels("mistral", "mistral").inc()
            except Exception:
                pass
            return out
        # По умолчанию Gemini с фолбэком
        if GEMINI_ENABLED and GOOGLE_API_KEYS:
            result = _make_gemini_request(prompt)
            if result:
                return result
        if MISTRAL_ENABLED and MISTRAL_API_KEY:
            return _mistral_generate_raw_prompt(prompt)
        return None
    except RetryError as e:
        logger.error(f"Не удалось получить служебное резюме: {e}")
        return None


def generate_service_digest(
    articles_jsonl: str,
    period_name: str,
    previous_summary_json: str | None = None,
) -> str | None:
    """Генерирует служебный JSON-дайджест для периода."""
    prompt = create_service_digest_prompt(
        articles_jsonl=articles_jsonl,
        period_name=period_name,
        previous_summary_json=previous_summary_json,
    )
    try:
        if LLM_PRIMARY == "mistral" and MISTRAL_ENABLED and MISTRAL_API_KEY:
            result = _mistral_generate_raw_prompt(prompt)
            if result:
                return result
            if GEMINI_ENABLED and GOOGLE_API_KEYS:
                return _make_gemini_request(prompt)
            return None
        if GEMINI_ENABLED and GOOGLE_API_KEYS:
            result = _make_gemini_request(prompt)
            if result:
                return result
        if MISTRAL_ENABLED and MISTRAL_API_KEY:
            res = _mistral_generate_raw_prompt(prompt)
            try:
                LLM_REQUESTS_BY_KEY_TOTAL.labels("mistral", "mistral").inc()
            except Exception:
                pass
            return res
        return None
    except RetryError as e:
        logger.error(f"Не удалось получить служебный дайджест: {e}")
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
    """Суммирует текст, выбирая провайдера по настройке LLM_PRIMARY.

    Логика:
    - Если LLM_PRIMARY = 'mistral' и провайдер доступен — используем Mistral.
    - Иначе используем Gemini (при наличии ключей), затем фолбэк на Mistral.
    """
    cleaned_text = full_text.strip()
    if not cleaned_text:
        logger.error("Ошибка: Передан пустой текст для суммирования.")
        return None

    prompt = create_summarization_prompt(cleaned_text)
    # 1) Явный приоритет Mistral
    if LLM_PRIMARY == "mistral" and MISTRAL_ENABLED and MISTRAL_API_KEY:
        result = summarize_with_mistral(cleaned_text)
        if result:
            return result
        # Если не удалось, пробуем Gemini
        if GEMINI_ENABLED and GOOGLE_API_KEYS:
            try:
                return _make_gemini_request(prompt)
            except RetryError as e:
                logger.error(f"Не удалось получить резюме от Gemini: {e}")
                return None
        return None

    # 2) По умолчанию — Gemini с фолбэком на Mistral
    if GEMINI_ENABLED and GOOGLE_API_KEYS:
        try:
            result = _make_gemini_request(prompt)
            if result:
                return result
        except RetryError as e:
            logger.error(f"Не удалось получить резюме от Gemini: {e}")
    if MISTRAL_ENABLED and MISTRAL_API_KEY:
        return summarize_with_mistral(cleaned_text)
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
        if LLM_PRIMARY == "mistral" and MISTRAL_ENABLED and MISTRAL_API_KEY:
            result = _mistral_generate_raw_prompt(prompt)
            if result:
                return result
            if GEMINI_ENABLED and GOOGLE_API_KEYS:
                return _make_gemini_request(prompt)
            return None
        if GEMINI_ENABLED and GOOGLE_API_KEYS:
            result = _make_gemini_request(prompt)
            if result:
                return result
        if MISTRAL_ENABLED and MISTRAL_API_KEY:
            ret = _mistral_generate_raw_prompt(prompt)
            try:
                LLM_REQUESTS_BY_KEY_TOTAL.labels("mistral", "mistral").inc()
            except Exception:
                pass
            return ret
        return None
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
        if LLM_PRIMARY == "mistral" and MISTRAL_ENABLED and MISTRAL_API_KEY:
            result = _mistral_generate_raw_prompt(prompt)
            if result:
                return result
            if GEMINI_ENABLED and GOOGLE_API_KEYS:
                return _make_gemini_request(prompt)
            return None
        if GEMINI_ENABLED and GOOGLE_API_KEYS:
            result = _make_gemini_request(prompt)
            if result:
                return result
        if MISTRAL_ENABLED and MISTRAL_API_KEY:
            return _mistral_generate_raw_prompt(prompt)
        return None
    except RetryError as e:
        logger.error(f"Не удалось создать годовой дайджест: {e}")
        return None

def _mistral_generate_raw_prompt(prompt: str) -> str | None:
    """Отправляет сырой промпт в Mistral и учитывает токены."""
    from mistralai.client import MistralClient
    if not MISTRAL_API_KEY:
        logger.error("API-ключ для Mistrал не найден.")
        return None
    try:
        import time as _t
        client = MistralClient(api_key=MISTRAL_API_KEY)
        messages = [{"role": "user", "content": prompt}]
        _start = _t.time()
        chat_response = client.chat(model=MISTRAL_MODEL_NAME, messages=messages)
        try:
            _dur = max(0.0, _t.time() - _start)
            EXTERNAL_HTTP_REQUEST_DURATION_SECONDS.labels("llm").observe(_dur)
            EXTERNAL_HTTP_REQUESTS_TOTAL.labels("llm", "POST", "2xx").inc()
            # Count request per key for Mistral
            try:
                LLM_REQUESTS_BY_KEY_TOTAL.labels("mistral", "mistral").inc()
            except Exception:
                pass
        except Exception:
            pass
        try:
            usage = getattr(chat_response, "usage", None)
            pt = (getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", None) or (isinstance(usage, dict) and (usage.get("prompt_tokens") or usage.get("input_tokens"))))
            ct = (getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", None) or (isinstance(usage, dict) and (usage.get("completion_tokens") or usage.get("output_tokens"))))
            if isinstance(pt, int) and pt > 0:
                TOKENS_CONSUMED_PROMPT_TOTAL.labels("mistral", MISTRAL_MODEL_NAME).inc(pt)
                TOKENS_CONSUMED_PROMPT_BY_KEY_TOTAL.labels("mistral", "mistral").inc(pt)
            else:
                TOKENS_CONSUMED_PROMPT_BY_KEY_TOTAL.labels("mistral", "mistral").inc(0)
            if isinstance(ct, int) and ct > 0:
                TOKENS_CONSUMED_COMPLETION_TOTAL.labels("mistral", MISTRAL_MODEL_NAME).inc(ct)
                TOKENS_CONSUMED_COMPLETION_BY_KEY_TOTAL.labels("mistral", "mistral").inc(ct)
            else:
                TOKENS_CONSUMED_COMPLETION_BY_KEY_TOTAL.labels("mistral", "mistral").inc(0)
        except Exception:
            pass
        # Persisted API usage event (success)
        try:
            tokens_in = int(pt or 0) if 'pt' in locals() else 0
            tokens_out = int(ct or 0) if 'ct' in locals() else 0
            cost_usd = estimate_event_cost_usd("mistral", MISTRAL_MODEL_NAME, tokens_in, tokens_out)
            _dur_ms = int(max(0.0, _t.time() - _start) * 1000.0)
            api_key_hash = hash_api_key_to_id(MISTRAL_API_KEY)
            record_api_event({
                "ts_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                "provider": "mistral",
                "model": MISTRAL_MODEL_NAME,
                "api_key_hash": api_key_hash,
                "endpoint": "chat",
                "req_count": 1,
                "success": True,
                "http_status": None,
                "latency_ms": _dur_ms,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": float(cost_usd),
                "error_code": None,
                "extra_json": None,
            })
        except Exception:
            pass
        text = chat_response.choices[0].message.content
        return (text or "").strip()
    except Exception as e:
        logger.error(f"Ошибка при запросе к Mistral (raw): {e}")
        try:
            EXTERNAL_HTTP_REQUESTS_TOTAL.labels("llm", "POST", "5xx").inc()
        except Exception:
            pass
        # Persist failed event
        try:
            import time as _t2
            _dur_ms = int(max(0.0, (_t2.time() - _start) if ' _start' in locals() else 0.0) * 1000.0)
            api_key_hash = hash_api_key_to_id(MISTRAL_API_KEY)
            record_api_event({
                "ts_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                "provider": "mistral",
                "model": MISTRAL_MODEL_NAME,
                "api_key_hash": api_key_hash,
                "endpoint": "chat",
                "req_count": 1,
                "success": False,
                "http_status": None,
                "latency_ms": _dur_ms,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
                "error_code": type(e).__name__,
                "extra_json": None,
            })
        except Exception:
            pass
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
        import time as _t
        client = MistralClient(api_key=MISTRAL_API_KEY)

        prompt = create_summarization_prompt(text_to_summarize)
        # Используем универсальный формат сообщений без зависимости от моделей SDK
        messages = [{"role": "user", "content": prompt}]

        _start = _t.time()
        chat_response = client.chat(
            model=MISTRAL_MODEL_NAME,
            messages=messages,
        )
        try:
            _dur = max(0.0, _t.time() - _start)
            EXTERNAL_HTTP_REQUEST_DURATION_SECONDS.labels("llm").observe(_dur)
            EXTERNAL_HTTP_REQUESTS_TOTAL.labels("llm", "POST", "2xx").inc()
            try:
                LLM_REQUESTS_BY_KEY_TOTAL.labels("mistral", "mistral").inc()
            except Exception:
                pass
        except Exception:
            pass

        # Token usage if available
        try:
            usage = getattr(chat_response, "usage", None)
            prompt_tokens = None
            completion_tokens = None
            if usage is not None:
                if isinstance(usage, dict):
                    prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
                    completion_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
                else:
                    prompt_tokens = getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", None)
                    completion_tokens = getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", None)
            if isinstance(prompt_tokens, int) and prompt_tokens > 0:
                TOKENS_CONSUMED_PROMPT_TOTAL.labels("mistral", MISTRAL_MODEL_NAME).inc(prompt_tokens)
                TOKENS_CONSUMED_PROMPT_BY_KEY_TOTAL.labels("mistral", "mistral").inc(prompt_tokens)
            if isinstance(completion_tokens, int) and completion_tokens > 0:
                TOKENS_CONSUMED_COMPLETION_TOTAL.labels("mistral", MISTRAL_MODEL_NAME).inc(completion_tokens)
                TOKENS_CONSUMED_COMPLETION_BY_KEY_TOTAL.labels("mistral", "mistral").inc(completion_tokens)
            # Ensure per-key series exist even if usage is missing/zero
            if not (isinstance(prompt_tokens, int) and prompt_tokens > 0):
                try:
                    TOKENS_CONSUMED_PROMPT_BY_KEY_TOTAL.labels("mistral", "mistral").inc(0)
                except Exception:
                    pass
            if not (isinstance(completion_tokens, int) and completion_tokens > 0):
                try:
                    TOKENS_CONSUMED_COMPLETION_BY_KEY_TOTAL.labels("mistral", "mistral").inc(0)
                except Exception:
                    pass
        except Exception:
            pass

        summary = chat_response.choices[0].message.content
        logger.info("Резюме успешно получено от Mistral.")
        # Notify web UI that metrics likely changed
        try:
            _sse_broadcast({"type": "metrics_updated"})
        except Exception:
            pass
        return summary.strip()

    except Exception as e:
        logger.error(f"Ошибка при получении резюме от Mistral: {e}")
        try:
            EXTERNAL_HTTP_REQUESTS_TOTAL.labels("llm", "POST", "5xx").inc()
        except Exception:
            pass
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