# src/llm_providers.py

import logging
import os
import json
import hashlib
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from abc import ABC, abstractmethod

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from mistralai.client import MistralClient

from config import (
    GOOGLE_API_KEYS, GEMINI_MODEL_NAME, MISTRAL_API_KEY, MISTRAL_MODEL_NAME,
    LLM_TIMEOUT_SEC, LLM_MAX_TOKENS
)
from metrics import LLM_REQUESTS_TOTAL, LLM_LATENCY_SECONDS

logger = logging.getLogger(__name__)

# --- Управление статусом ключей Gemini ---
KEY_STATUS_FILE = Path(__file__).parent.parent / "temp" / "gemini_key_status.json"
KEY_STATUS_FILE.parent.mkdir(exist_ok=True)

def _load_key_status() -> dict:
    if not KEY_STATUS_FILE.exists(): return {}
    try:
        with open(KEY_STATUS_FILE, 'r') as f: return json.load(f)
    except (json.JSONDecodeError, IOError): return {}

def _save_key_status(statuses: dict):
    try:
        with open(KEY_STATUS_FILE, 'w') as f: json.dump(statuses, f, indent=4)
    except IOError as e: logger.error(f"Не удалось сохранить файл статуса ключей: {e}")

def _is_key_disabled(key_hash: str, statuses: dict) -> bool:
    status = statuses.get(key_hash)
    if not status: return False
    if status.get("reason") == "geo_unsupported" and datetime.now() - datetime.fromisoformat(status.get("timestamp", "1970-01-01T00:00:00")) < timedelta(hours=24):
        return True
    if status.get("reason") == "quota_exceeded" and datetime.now() < datetime.fromisoformat(status.get("cooldown_until", "1970-01-01T00:00:00")):
        return True
    return False

def create_summarization_prompt(full_text: str) -> str:
    return f"""Сделай краткое и содержательное резюме (примерно 150 слов) следующей новостной статьи на русском языке. Сохрани только ключевые факты и выводы. Не добавляй от себя никакой информации и не используй markdown-форматирование.

Текст статьи:
---
{full_text}
---"""

class LLMProvider(ABC):
    @abstractmethod
    def summarize(self, text: str) -> Optional[str]:
        pass

    @property
    @abstractmethod
    def is_enabled(self) -> bool:
        pass

class GeminiProvider(LLMProvider):
    def __init__(self):
        self.current_key_index = 0

    @property
    def is_enabled(self) -> bool:
        return os.getenv("GEMINI_ENABLED", "true").lower() in {"1", "true", "yes"} and bool(GOOGLE_API_KEYS)

    def summarize(self, text: str) -> Optional[str]:
        if not self.is_enabled:
            return None

        prompt = create_summarization_prompt(text)
        key_statuses = _load_key_status()
        error_log_entries = []
        
        start_index = self.current_key_index
        for i in range(len(GOOGLE_API_KEYS)):
            idx = (start_index + i) % len(GOOGLE_API_KEYS)
            api_key = GOOGLE_API_KEYS[idx]
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()

            if _is_key_disabled(key_hash, key_statuses):
                logger.debug(f"Gemini ключ #{idx + 1} временно отключен.")
                continue

            self.current_key_index = idx
            
            start_time = time.time()
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(
                    GEMINI_MODEL_NAME,
                    generation_config={"max_output_tokens": LLM_MAX_TOKENS}
                )
                
                logger.debug(f"Запрос к Gemini API с ключом #{idx + 1}...")
                response = model.generate_content(
                    prompt,
                    request_options={'timeout': LLM_TIMEOUT_SEC}
                )
                
                if response.text:
                    logger.info(f"Ответ от Gemini успешно получен.")
                    LLM_REQUESTS_TOTAL.labels(provider="gemini", status="success", reason="ok").inc()
                    return response.text.strip()
                else:
                    error_log_entries.append(f"Ключ #{idx + 1}: Пустой ответ (safety block)")
                    LLM_REQUESTS_TOTAL.labels(provider="gemini", status="failure", reason="blocked").inc()
                    continue

            except ResourceExhausted as e:
                retry_delay_seconds = getattr(e, 'retry_delay', 300)
                cooldown_until = datetime.now() + timedelta(seconds=retry_delay_seconds)
                error_log_entries.append(f"Ключ #{idx + 1}: Квота исчерпана (отключен до {cooldown_until.isoformat()})")
                LLM_REQUESTS_TOTAL.labels(provider="gemini", status="failure", reason="quota_exceeded").inc()
                key_statuses[key_hash] = {"reason": "quota_exceeded", "cooldown_until": cooldown_until.isoformat()}
                _save_key_status(key_statuses)
                continue
            except Exception as e:
                message = str(e).lower()
                if 'location is not supported' in message:
                    error_log_entries.append(f"Ключ #{idx + 1}: Регион не поддерживается")
                    LLM_REQUESTS_TOTAL.labels(provider="gemini", status="failure", reason="geo_unsupported").inc()
                    key_statuses[key_hash] = {"reason": "geo_unsupported", "timestamp": datetime.now().isoformat()}
                    _save_key_status(key_statuses)
                else:
                    error_log_entries.append(f"Ключ #{idx + 1}: Неизвестная ошибка ({e})")
                    logger.error(f"Неизвестная ошибка с ключом Gemini #{idx + 1}: {e}", exc_info=True)
                    LLM_REQUESTS_TOTAL.labels(provider="gemini", status="failure", reason="unknown").inc()
                continue
            finally:
                duration = time.time() - start_time
                LLM_LATENCY_SECONDS.labels(provider="gemini", model=GEMINI_MODEL_NAME).observe(duration)
        
        if error_log_entries:
            logger.warning(f"Не удалось получить ответ от Gemini. Ошибки по ключам: {'; '.join(error_log_entries)}")
        else:
            logger.error("Не удалось получить ответ от Gemini после перебора всех ключей по неизвестной причине.")
            
        return None

class MistralProvider(LLMProvider):
    @property
    def is_enabled(self) -> bool:
        return os.getenv("MISTRAL_ENABLED", "true").lower() in {"1", "true", "yes"} and bool(MISTRAL_API_KEY)

    def summarize(self, text: str) -> Optional[str]:
        if not self.is_enabled:
            return None

        prompt = create_summarization_prompt(text)
        start_time = time.time()
        try:
            client = MistralClient(api_key=MISTRAL_API_KEY, timeout=LLM_TIMEOUT_SEC)
            messages = [{"role": "user", "content": prompt}]
            
            logger.info("Запрос к Mistral API...")
            chat_response = client.chat(
                model=MISTRAL_MODEL_NAME,
                messages=messages,
                # max_tokens is part of the generation config in the new API
            )
            
            summary = chat_response.choices[0].message.content
            logger.info("Ответ от Mistral успешно получен.")
            LLM_REQUESTS_TOTAL.labels(provider="mistral", status="success", reason="ok").inc()
            return summary.strip()
        except Exception as e:
            logger.error(f"Ошибка при запросе к Mistral: {e}")
            LLM_REQUESTS_TOTAL.labels(provider="mistral", status="failure", reason="unknown").inc()
            return None
        finally:
            duration = time.time() - start_time
            LLM_LATENCY_SECONDS.labels(provider="mistral", model=MISTRAL_MODEL_NAME).observe(duration)