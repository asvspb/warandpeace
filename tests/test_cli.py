import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock

# Важно: импортируем сам объект cli из скрипта
from scripts.manage import cli

@pytest.fixture
def runner():
    """Фикстура для создания экземпляра CliRunner."""
    return CliRunner()

# --- Тесты для команды status ---
@patch('scripts.manage.get_stats')
def test_status_command(mock_get_stats, runner):
    """Тестирует команду status, мокируя ответ от БД."""
    # 1. Подготовка: настраиваем мок
    mock_get_stats.return_value = {
        'total_articles': 100,
        'success': 80,
        'pending': 15,
        'failed': 5,
        'skipped': 0,
        'last_posted_article': {
            'title': "Тестовая статья",
            'published_at': "2025-01-01"
        }
    }

    # 2. Действие: вызываем команду
    result = runner.invoke(cli, ['status'])

    # 3. Проверка: убеждаемся, что все прошло успешно и данные выведены
    assert result.exit_code == 0
    assert "Статистика:" in result.output
    assert "Всего статей: 100" in result.output
    assert "Обработано успешно: 80" in result.output
    assert "Ошибок: 5" in result.output
    assert "Тестовая статья" in result.output
    mock_get_stats.assert_called_once() # Проверяем, что функция была вызвана

# --- Тесты для команды backfill ---
@patch('scripts.manage._process_articles')
@patch('scripts.manage.get_articles_for_backfill')
def test_backfill_command(mock_get_articles, mock_process, runner):
    """Тестирует команду backfill."""
    # 1. Подготовка
    mock_articles = [{'id': 1, 'url': 'http://test.com'}]
    mock_get_articles.return_value = mock_articles

    # 2. Действие: используем --force, чтобы избежать интерактивного запроса
    result = runner.invoke(cli, ['backfill', '--force'])

    # 3. Проверка
    assert result.exit_code == 0
    assert "Запуск процесса backfill..." in result.output
    # Проверяем, что get_articles_for_backfill была вызвана без аргументов (для всех статей)
    mock_get_articles.assert_called_once_with()
    # Проверяем, что основная функция обработки была вызвана с нужными статьями
    mock_process.assert_called_once_with(mock_articles)

# --- Тесты для команды retry_failed ---
@patch('scripts.manage.init_db') # Мокируем init_db, чтобы избежать создания БД
@patch('scripts.manage._process_articles')
@patch('scripts.manage.get_articles_for_backfill')
def test_retry_failed_command(mock_get_articles, mock_process, mock_init_db, runner):
    """Тестирует команду retry_failed."""
    # 1. Подготовка
    mock_failed_articles = [{'id': 2, 'url': 'http://failed.com'}]
    mock_get_articles.return_value = mock_failed_articles

    # 2. Действие
    result = runner.invoke(cli, ['retry-failed', '--force'])

    # 3. Проверка
    assert result.exit_code == 0, f"Команда завершилась с ошибкой: {result.output}"
    assert "Запуск повторной обработки ошибочных статей..." in result.output
    # Проверяем, что get_articles_for_backfill была вызвана со статусом 'failed'
    mock_get_articles.assert_called_once_with(status='failed')
    # Проверяем, что основная функция обработки была вызвана с нужными статьями
    mock_process.assert_called_once_with(mock_failed_articles)
    # Убедимся, что init_db не вызывалась в тесте (т.к. мы ее мокировали)
    mock_init_db.assert_called_once()
