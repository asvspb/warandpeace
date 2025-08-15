# tests/test_llm_providers.py

import pytest
from unittest.mock import MagicMock, patch
import os

# Нужно установить переменные окружения до импорта модулей
os.environ['GEMINI_ENABLED'] = 'true'
os.environ['MISTRAL_ENABLED'] = 'true'
os.environ['GOOGLE_API_KEYS'] = 'test_key_1,test_key_2'
os.environ['MISTRAL_API_KEY'] = 'test_mistral_key'

from src.llm_providers import GeminiProvider, MistralProvider
from src.summarizer import summarize_with_fallback

# --- Фикстуры ---

@pytest.fixture
def mock_gemini():
    """Мокает ответ от Gemini API."""
    with patch('google.generativeai.GenerativeModel') as mock_model:
        mock_response = MagicMock()
        mock_response.text = "Резюме от Gemini"
        mock_model.return_value.generate_content.return_value = mock_response
        yield mock_model

@pytest.fixture
def mock_mistral():
    """Мокает ответ от Mistral API."""
    with patch('mistralai.client.MistralClient.chat') as mock_chat:
        mock_choice = MagicMock()
        mock_choice.message.content = "Резюме от Mistral"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_chat.return_value = mock_response
        yield mock_chat

# --- Тесты GeminiProvider ---

def test_gemini_provider_success(mock_gemini):
    """Тест успешного получения резюме от Gemini."""
    provider = GeminiProvider()
    summary = provider.summarize("Тестовый текст")
    assert summary == "Резюме от Gemini"
    mock_gemini.return_value.generate_content.assert_called_once()

# --- Тесты MistralProvider ---

def test_mistral_provider_success(mock_mistral):
    """Тест успешного получения резюме от Mistral."""
    provider = MistralProvider()
    summary = provider.summarize("Тестовый текст")
    assert summary == "Резюме от Mistral"
    mock_mistral.assert_called_once()

# --- Тесты summarize_with_fallback (оркестратор) ---

def test_fallback_gemini_to_mistral(mock_gemini, mock_mistral):
    """Тест фолбэка с Gemini на Mistral при ошибке."""
    mock_gemini.return_value.generate_content.side_effect = Exception("Gemini API error")
    
    os.environ['LLM_PRIMARY'] = 'gemini'
    summary = summarize_with_fallback("Тестовый текст")
    
    assert summary == "Резюме от Mistral"
    assert mock_gemini.return_value.generate_content.call_count > 0
    mock_mistral.assert_called_once()

def test_fallback_primary_mistral(mock_gemini, mock_mistral):
    """Тест, когда Mistral является первичным провайдером."""
    os.environ['LLM_PRIMARY'] = 'mistral'
    summary = summarize_with_fallback("Тестовый текст")
    
    assert summary == "Резюме от Mistral"
    mock_mistral.assert_called_once()
    mock_gemini.return_value.generate_content.assert_not_called()

def test_fallback_both_disabled():
    """Тест, когда оба провайдера отключены."""
    os.environ['GEMINI_ENABLED'] = 'false'
    os.environ['MISTRAL_ENABLED'] = 'false'
    
    summary = summarize_with_fallback("Тестовый текст")
    assert summary is None
    
    # Возвращаем значения для других тестов
    os.environ['GEMINI_ENABLED'] = 'true'
    os.environ['MISTRAL_ENABLED'] = 'true'