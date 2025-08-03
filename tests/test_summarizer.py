import pytest
import unittest.mock as mock
import os
import src.summarizer as summarizer
import src.config as config
import google.generativeai as genai
import requests
import importlib

# Мокируем переменные окружения и конфига для тестов
@pytest.fixture(autouse=True)
def mock_env_vars():
    with mock.patch.dict(os.environ, {
        "GOOGLE_API_KEY": "test_gemini_key_1",
        "GOOGLE_API_KEY_1": "test_gemini_key_2",
        "GOOGLE_API_KEY_2": "test_gemini_key_3",
        "OPENROUTER_API_KEY": "test_openrouter_key"
    }):
        # Перезагружаем конфиг, чтобы он подхватил мокнутые переменные
        importlib.reload(config)
        importlib.reload(summarizer)
        yield
        # Восстанавливаем исходное состояние после тестов
        importlib.reload(config)
        importlib.reload(summarizer)

@pytest.fixture
def mock_gemini_model():
    with mock.patch('google.generativeai.GenerativeModel') as mock_model_class:
        mock_model_instance = mock.Mock()
        mock_model_class.return_value = mock_model_instance
        yield mock_model_instance

@pytest.fixture
def mock_requests_post():
    with mock.patch('requests.post') as mock_post:
        yield mock_post

def test_create_summarization_prompt():
    text = "This is a test article."
    prompt = summarizer.create_summarization_prompt(text)
    assert "Сделай краткое и содержательное резюме" in prompt
    assert "This is a test article." in prompt

def test_summarize_text_local_gemini_success(mock_gemini_model):
    mock_gemini_model.generate_content.return_value.text = "Gemini Summary"
    summary = summarizer.summarize_text_local("Some text")
    assert summary == "Gemini Summary"
    mock_gemini_model.generate_content.assert_called_once()

def test_summarize_text_local_gemini_blocked_then_success(mock_gemini_model):
    # Первый вызов блокируется, второй успешен
    mock_gemini_model.generate_content.side_effect = [
        genai.types.BlockedPromptException("Blocked"),
        mock.Mock(text="Gemini Summary 2")
    ]
    
    # Убедимся, что current_gemini_key_index сброшен для теста
    summarizer.current_gemini_key_index = 0

    summary = summarizer.summarize_text_local("Some text")
    assert summary == "Gemini Summary 2"
    assert mock_gemini_model.generate_content.call_count == 2
    # Проверяем, что индекс ключа переключился
    assert summarizer.current_gemini_key_index == 1 # 0 -> 1

def test_summarize_text_local_gemini_all_blocked_then_openrouter_success(mock_gemini_model, mock_requests_post):
    # Все Gemini ключи блокируются
    mock_gemini_model.generate_content.side_effect = [
        genai.types.BlockedPromptException("Blocked 1"),
        genai.types.BlockedPromptException("Blocked 2"),
        genai.types.BlockedPromptException("Blocked 3")
    ]
    
    # OpenRouter успешен
    mock_requests_post.return_value.status_code = 200
    mock_requests_post.return_value.json.return_value = {
        "choices": [{"message": {"content": "OpenRouter Summary"}}]
    }

    # Убедимся, что current_gemini_key_index сброшен для теста
    summarizer.current_gemini_key_index = 0

    summary = summarizer.summarize_text_local("Some text")
    assert summary == "OpenRouter Summary"
    assert mock_gemini_model.generate_content.call_count == 3 # Попытки для всех 3 ключей Gemini
    mock_requests_post.assert_called_once()

def test_summarize_text_local_empty_text():
    summary = summarizer.summarize_text_local("")
    assert summary is None

def test_summarize_text_local_no_keys_available(mock_gemini_model, mock_requests_post):
    # Мокируем, что нет доступных ключей
    with mock.patch.object(config, 'GOOGLE_API_KEYS', []):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            importlib.reload(config)
            importlib.reload(summarizer)
            
            summary = summarizer.summarize_text_local("Some text")
            assert summary is None
            mock_gemini_model.generate_content.assert_not_called()
            mock_requests_post.assert_not_called()

def test_summarize_text_local_openrouter_failure(mock_gemini_model, mock_requests_post):
    # Все Gemini ключи блокируются
    mock_gemini_model.generate_content.side_effect = [
        genai.types.BlockedPromptException("Blocked 1"),
        genai.types.BlockedPromptException("Blocked 2"),
        genai.types.BlockedPromptException("Blocked 3")
    ]
    
    # OpenRouter возвращает ошибку
    mock_requests_post.return_value.status_code = 500
    mock_requests_post.return_value.raise_for_status.side_effect = requests.exceptions.RequestException("OpenRouter error")

    # Убедимся, что current_gemini_key_index сброшен для теста
    summarizer.current_gemini_key_index = 0

    summary = summarizer.summarize_text_local("Some text")
    assert summary is None
    assert mock_gemini_model.generate_content.call_count == 3
    mock_requests_post.assert_called_once()

def test_summarize_text_local_gemini_exception_then_success(mock_gemini_model):
    # Первый вызов вызывает общую ошибку, второй успешен
    mock_gemini_model.generate_content.side_effect = [
        Exception("General Gemini error"),
        mock.Mock(text="Gemini Summary 2")
    ]
    
    # Убедимся, что current_gemini_key_index сброшен для теста
    summarizer.current_gemini_key_index = 0

    summary = summarizer.summarize_text_local("Some text")
    assert summary == "Gemini Summary 2"
    assert mock_gemini_model.generate_content.call_count == 2
    assert summarizer.current_gemini_key_index == 1

def test_summarize_text_local_all_gemini_fail_no_openrouter(mock_gemini_model, mock_requests_post):
    # Все Gemini ключи блокируются
    mock_gemini_model.generate_content.side_effect = [
        genai.types.BlockedPromptException("Blocked 1"),
        genai.types.BlockedPromptException("Blocked 2"),
        genai.types.BlockedPromptException("Blocked 3")
    ]
    
    # OpenRouter ключ отсутствует
    with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
        importlib.reload(config)
        importlib.reload(summarizer)
        
        # Убедимся, что current_gemini_key_index сброшен для теста
        summarizer.current_gemini_key_index = 0

        summary = summarizer.summarize_text_local("Some text")
        assert summary is None
        assert mock_gemini_model.generate_content.call_count == 3
        mock_requests_post.assert_not_called()
