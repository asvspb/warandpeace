# src/summarizer.py

import logging
import os
from typing import Optional

from llm_providers import GeminiProvider, MistralProvider
from metrics import LLM_FALLBACKS_TOTAL

logger = logging.getLogger(__name__)

# --- Инициализация провайдеров ---
gemini_provider = GeminiProvider()
mistral_provider = MistralProvider()

# --- Логика оркестрации ---
def get_primary_provider():
    """Определяет первичного провайдера на основе .env."""
    primary = os.getenv("LLM_PRIMARY", "gemini").lower()
    if primary == "mistral" and mistral_provider.is_enabled:
        return mistral_provider, gemini_provider
    # По умолчанию или если Mistral недоступен, Gemini — первый
    return gemini_provider, mistral_provider

def summarize_with_fallback(full_text: str) -> Optional[str]:
    """
    Главная функция-оркестратор.
    Выбирает провайдера на основе настроек и выполняет фолбэк.
    """
    primary, secondary = get_primary_provider()

    if not primary.is_enabled and not secondary.is_enabled:
        logger.error("Все LLM-провайдеры отключены или не настроены.")
        return None

    # 1. Попытка с первичным провайдером
    if primary.is_enabled:
        logger.info(f"Попытка #1: Суммаризация через {type(primary).__name__}.")
        summary = primary.summarize(full_text)
        if summary:
            return summary
    else:
        logger.warning(f"Первичный провайдер {type(primary).__name__} отключен.")

    # 2. Попытка с вторичным провайдером (фолбэк)
    if secondary.is_enabled:
        logger.warning(f"Попытка #1 не удалась. Попытка #2 (фолбэк): Суммаризация через {type(secondary).__name__}.")
        LLM_FALLBACKS_TOTAL.labels(
            from_provider=type(primary).__name__.replace("Provider", "").lower(),
            to_provider=type(secondary).__name__.replace("Provider", "").lower(),
            reason="primary_failure"
        ).inc()
        summary = secondary.summarize(full_text)
        if summary:
            return summary
    else:
        logger.warning(f"Вторичный провайдер {type(secondary).__name__} отключен.")

    logger.error("Не удалось получить резюме ни от одного из провайдеров.")
    return None

# --- Функции для дайджестов (оставлены здесь для совместимости) ---
# В будущем их можно перенести в отдельный модуль `digest_generator.py`

def create_digest_prompt(summaries: list[str], period_name: str) -> str:
    summaries_text = "\n- ".join(summaries)
    return f"""Ты — профессиональный новостной аналитик. Ниже представлен список кратких сводок новостей за последние {period_name}.
Твоя задача — написать целостную аналитическую сводку на русском языке (200-250 слов).
Требования:
1.  Не перечисляй просто факты из сводок.
2.  Определи 2-4 ключевых тренда или тематических блока на основе этих новостей.
3.  Напиши связный текст, который описывает эти тенденции, объединяя информацию из разных новостей.
4.  Начни с общего заголовка, например: "Главные события за {period_name}".
5.  Структурируй текст, используя абзацы для каждого тренда.
Список сводок:
- {summaries_text}
"""

def create_annual_digest_prompt(digest_contents: list[str]) -> str:
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

def create_digest(summaries: list[str], period_name: str) -> Optional[str]:
    if not summaries:
        logger.warning("Передан пустой список сводок для создания дайджеста.")
        return None
    prompt = create_digest_prompt(summaries, period_name)
    # Дайджесты всегда генерируем через первичного провайдера для консистентности
    primary, _ = get_primary_provider()
    if not primary.is_enabled:
        logger.error(f"Невозможно создать дайджест: первичный провайдер {type(primary).__name__} отключен.")
        return None
    return primary.summarize(prompt) # Используем summarize, т.к. промпт уже специфичен

def create_annual_digest(digest_contents: list[str]) -> Optional[str]:
    if not digest_contents:
        logger.warning("Передан пустой список дайджестов для годового отчета.")
        return None
    prompt = create_annual_digest_prompt(digest_contents)
    primary, _ = get_primary_provider()
    if not primary.is_enabled:
        logger.error(f"Невозможно создать годовой дайджест: первичный провайдер {type(primary).__name__} отключен.")
        return None
    return primary.summarize(prompt)