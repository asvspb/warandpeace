import os
import pytest
import sys
from unittest.mock import patch
import dotenv # Импортируем dotenv здесь, чтобы убедиться, что он загружен до патчинга

def reload_config():
    """Перезагружает модуль config, чтобы применить новые переменные окружения."""
    if 'src.config' in sys.modules:
        del sys.modules['src.config']
    import src.config
    return src.config

@pytest.fixture(autouse=True)
def mock_dotenv_load(monkeypatch):
    """Мокает load_dotenv, чтобы она не загружала реальный .env файл во время тестов."""
    # Патчим load_dotenv из модуля dotenv
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *args, **kwargs: None)
    
    # Очищаем переменные окружения, которые могут быть установлены извне
    test_vars = [
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID", "TELEGRAM_ADMIN_ID",
        "TELEGRAM_ADMIN_IDS", "GOOGLE_API_KEY", "GOOGLE_API_KEYS"
    ]
    for i in range(1, 10):
        test_vars.append(f"GOOGLE_API_KEY_{i}")

    for var in test_vars:
        monkeypatch.delenv(var, raising=False)
    
    yield

# --- Тесты для Telegram ID ---

def test_telegram_config_success_no_admin(monkeypatch):
    """Тест: приложение должно успешно запускаться без TELEGRAM_ADMIN_ID."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "test_channel")
    monkeypatch.setenv("GOOGLE_API_KEY", "test_api_key")
    
    config = reload_config()
    
    assert config.TELEGRAM_BOT_TOKEN == "test_token"
    assert config.TELEGRAM_CHANNEL_ID == "test_channel"
    assert config.TELEGRAM_ADMIN_ID is None
    assert config.TELEGRAM_ADMIN_IDS == []

def test_telegram_admin_id_single(monkeypatch):
    """Тест: TELEGRAM_ADMIN_ID корректно считывается."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "test_channel")
    monkeypatch.setenv("TELEGRAM_ADMIN_ID", "12345")
    monkeypatch.setenv("GOOGLE_API_KEY", "test_api_key")

    config = reload_config()
    assert config.TELEGRAM_ADMIN_ID == "12345"
    assert config.TELEGRAM_ADMIN_IDS == ["12345"]

def test_telegram_admin_ids_csv(monkeypatch):
    """Тест: TELEGRAM_ADMIN_IDS корректно парсится из CSV."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "test_channel")
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123, 456, 789")
    monkeypatch.setenv("GOOGLE_API_KEY", "test_api_key")

    config = reload_config()
    # Сортируем для стабильности теста, так как set не гарантирует порядок
    assert sorted(config.TELEGRAM_ADMIN_IDS) == sorted(["123", "456", "789"])

def test_telegram_admin_ids_combined_and_deduplicated(monkeypatch):
    """Тест: ID из TELEGRAM_ADMIN_ID и TELEGRAM_ADMIN_IDS объединяются и дедуплицируются."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "test_channel")
    monkeypatch.setenv("TELEGRAM_ADMIN_ID", "123")
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123, 456, 789")
    monkeypatch.setenv("GOOGLE_API_KEY", "test_api_key")

    config = reload_config()
    assert len(config.TELEGRAM_ADMIN_IDS) == 3 # Проверка дедупликации
    assert sorted(config.TELEGRAM_ADMIN_IDS) == sorted(["123", "456", "789"])

# --- Тесты для Google API ключей ---

def test_google_api_keys_from_csv(monkeypatch):
    """Тест: Ключи корректно парсятся из GOOGLE_API_KEYS (CSV)."""
    monkeypatch.setenv("GOOGLE_API_KEYS", "key_csv_1, key_csv_2")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "test_channel")
    config = reload_config()
    assert config.GOOGLE_API_KEYS == ["key_csv_1", "key_csv_2"]

def test_google_api_keys_from_single_and_numbered(monkeypatch):
    """Тест: Ключи корректно собираются из GOOGLE_API_KEY и GOOGLE_API_KEY_n."""
    monkeypatch.setenv("GOOGLE_API_KEY", "main_key")
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key_1")
    monkeypatch.setenv("GOOGLE_API_KEY_3", "key_3")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "test_channel")
    config = reload_config()
    assert config.GOOGLE_API_KEYS == ["main_key", "key_1", "key_3"]

def test_google_api_keys_combined_and_deduplicated(monkeypatch):
    """Тест: Все источники ключей объединяются и дедуплицируются с правильным приоритетом."""
    monkeypatch.setenv("GOOGLE_API_KEYS", "csv_key, main_key")
    monkeypatch.setenv("GOOGLE_API_KEY", "main_key")
    monkeypatch.setenv("GOOGLE_API_KEY_1", "key_1")
    monkeypatch.setenv("GOOGLE_API_KEY_2", "csv_key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "test_channel")

    config = reload_config()
    # Ожидаемый порядок: сначала из CSV, потом основной, потом нумерованные. Дубликаты удаляются.
    assert config.GOOGLE_API_KEYS == ["csv_key", "main_key", "key_1"]

def test_missing_telegram_variables_raises_error(monkeypatch):
    """Тест: Падение при отсутствии обязательных переменных Telegram."""
    # Устанавливаем только ключ API, но не Telegram
    monkeypatch.setenv("GOOGLE_API_KEY", "test_api_key")
    # Удаляем переменные, если они были установлены где-то еще
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)

    with pytest.raises(ValueError, match="Ключевые переменные Telegram не заданы"):
        reload_config()

def test_missing_google_keys_raises_error(monkeypatch):
    """Тест: Падение при отсутствии ключей Google API."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "test_channel")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEYS", raising=False)

    with pytest.raises(ValueError, match="Не найден ни один ключ Google API"):
        reload_config()