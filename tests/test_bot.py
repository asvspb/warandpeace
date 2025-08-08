
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Добавляем путь к src для импорта модулей
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

# Мокируем конфиг перед импортом bot
with patch.dict(os.environ, {'TELEGRAM_ADMIN_ID': '12345'}):
    from bot import start, status, check_now, check_and_post_news, send_admin_notification
    from config import TELEGRAM_ADMIN_ID

@pytest.fixture
def mock_update():
    """Фикстура для создания мока объекта Update."""
    update = MagicMock()
    update.message = AsyncMock()
    update.effective_user.id = 12345
    return update

@pytest.fixture
def mock_context():
    """Фикстура для создания мока объекта Context."""
    context = MagicMock()
    context.bot = AsyncMock()
    context.job_queue = MagicMock()
    context.job_queue.run_once = MagicMock()
    context.bot_data = {}
    context.job = MagicMock()
    context.job.user_id = None
    return context

@pytest.mark.asyncio
async def test_start_command(mock_update, mock_context):
    await start(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    assert "Приветствую Вас, сударь!" in call_args[0][0]

@pytest.mark.asyncio
async def test_status_command_with_job(mock_update, mock_context):
    """Тестирует команду /status при наличии запланированной задачи."""
    mock_job = MagicMock()
    mock_job.next_t = datetime(2025, 8, 8, 12, 30, 0)
    mock_context.job_queue.jobs.return_value = [mock_job]
    mock_context.bot_data["last_check_time"] = "2025-08-08 12:00:00"

    await status(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    text = mock_update.message.reply_text.call_args[0][0]
    assert "Последняя проверка новостей: 2025-08-08 12:00:00" in text
    assert "Следующая проверка новостей: 2025-08-08 12:30:00" in text

@pytest.mark.asyncio
async def test_check_now_command(mock_update, mock_context):
    await check_now(mock_update, mock_context)
    mock_update.message.reply_text.assert_called_once_with("Начинаю принудительную проверку новостей...")
    mock_context.job_queue.run_once.assert_called_once()

# --- Тесты для send_admin_notification ---

@pytest.mark.asyncio
@patch('bot.TELEGRAM_ADMIN_ID', '12345')
async def test_send_admin_notification_success(mock_context):
    """Тест успешной отправки уведомления администратору."""
    await send_admin_notification(mock_context, "Test message")
    mock_context.bot.send_message.assert_called_once_with(chat_id='12345', text="[УВЕДОМЛЕНИЕ]\n\nTest message")

@pytest.mark.asyncio
@patch('bot.TELEGRAM_ADMIN_ID', None)
async def test_send_admin_notification_no_id(mock_context):
    """Тест: отправка не происходит, если TELEGRAM_ADMIN_ID не задан."""
    await send_admin_notification(mock_context, "Test message")
    mock_context.bot.send_message.assert_not_called()

@pytest.mark.asyncio
@patch('bot.TELEGRAM_ADMIN_ID', '12345')
async def test_send_admin_notification_failure(mock_context):
    """Тест: обработка ошибки при отправке уведомления."""
    mock_context.bot.send_message.side_effect = Exception("Test error")
    # Убеждаемся, что исключение не пробрасывается наружу
    await send_admin_notification(mock_context, "Test message")
    mock_context.bot.send_message.assert_called_once()

# --- Тесты для check_and_post_news ---

@pytest.mark.asyncio
@patch('bot.get_articles_from_page', return_value=[
    {'link': f'link{i}', 'title': f'title{i}', 'date': '01.01.2025', 'time': f'{12+i}:00'} for i in range(5)
])
@patch('bot.is_article_posted', return_value=False)
@patch('bot.get_article_text', return_value="Full text")
@patch('bot.summarize_text_local', return_value="Summary")
@patch('bot.add_article')
@patch('asyncio.sleep', new_callable=AsyncMock)
async def test_check_news_publish_limit_3(mock_sleep, mock_add, mock_summarize, mock_get_text, mock_is_posted, mock_get_articles, mock_context):
    """Тест: публикуется не более 3 статей, даже если новых больше."""
    mock_context.bot.get_chat.return_value.username = 'test_channel'
    await check_and_post_news(mock_context)
    # Проверяем, что было ровно 3 публикации
    assert mock_context.bot.send_message.call_count == 3

@pytest.mark.asyncio
@patch('bot.get_articles_from_page', return_value=[
    {'link': 'link1', 'title': 'title1', 'date': '01.01.2025', 'time': '12:00'}
])
@patch('bot.is_article_posted', return_value=False)
@patch('bot.get_article_text', return_value=None) # Сбой получения текста
@patch('bot.summarize_text_local')
@patch('bot.add_article')
async def test_check_news_get_text_fails(mock_add, mock_summarize, mock_get_text, mock_is_posted, mock_get_articles, mock_context):
    """Тест: статья пропускается, если не удалось получить ее текст."""
    await check_and_post_news(mock_context)
    mock_summarize.assert_not_called()
    mock_add.assert_not_called()
    mock_context.bot.send_message.assert_not_called()

@pytest.mark.asyncio
@patch('bot.get_articles_from_page', side_effect=Exception("Critical error!"))
@patch('bot.send_admin_notification', new_callable=AsyncMock)
async def test_check_news_critical_exception(mock_send_admin, mock_get_articles, mock_context):
    """Тест: обработка критического исключения в основной функции."""
    mock_context.job.user_id = 12345
    await check_and_post_news(mock_context)
    # Проверяем отправку уведомления администратору
    mock_send_admin.assert_called_once()
    assert "Critical error!" in mock_send_admin.call_args[0][1]
    # Проверяем отправку сообщения пользователю
    mock_context.bot.send_message.assert_called_once_with(chat_id=12345, text="Произошла ошибка: Critical error!")

@pytest.mark.asyncio
@patch('bot.get_articles_from_page', return_value=[
    {'link': 'link1', 'title': 'title1', 'date': '01.01.2025', 'time': '12:00'}
])
@patch('bot.is_article_posted', return_value=False)
@patch('bot.get_article_text', return_value="Full text")
@patch('bot.summarize_text_local', return_value=None) # Сбой суммаризации
@patch('bot.add_article')
async def test_check_news_summarize_fails(mock_add, mock_summarize, mock_get_text, mock_is_posted, mock_get_articles, mock_context):
    """Тест: статья пропускается, если не удалось создать резюме."""
    await check_and_post_news(mock_context)
    mock_add.assert_not_called()
    mock_context.bot.send_message.assert_not_called()

@pytest.mark.asyncio
@patch('bot.get_articles_from_page', return_value=None) # Парсер вернул None
async def test_check_news_parser_returns_none(mock_get_articles, mock_context):
    """Тест: обработка случая, когда парсер возвращает None."""
    mock_context.job.user_id = 12345
    await check_and_post_news(mock_context)
    mock_context.bot.send_message.assert_called_once_with(chat_id=12345, text="Не удалось получить список статей.")

